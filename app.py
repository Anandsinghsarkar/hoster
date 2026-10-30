import os, sqlite3, secrets, subprocess, sys, time, threading, zipfile, shutil, ast, urllib.request, hashlib, json
from datetime import timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, render_template, abort, Response
from werkzeug.utils import secure_filename
from contextlib import contextmanager
from urllib.parse import quote
from werkzeug.security import generate_password_hash, check_password_hash

BASE = Path(__file__).resolve().parent

def _prepare_writable_dir(path: Path) -> Path:
    """Create a directory and verify that the current process can write to it."""
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".write-test-{os.getpid()}"
    with probe.open("w", encoding="utf-8") as handle:
        handle.write("ok")
    probe.unlink(missing_ok=True)
    return path

def _select_data_dir() -> Path:
    # Prefer DATA_DIR when configured, but gracefully fall back when a Render
    # persistent disk is not attached or the path is not writable.
    configured = os.getenv("DATA_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path("/tmp/cyberhost-data"))
    # Final local-development fallback. On Render, /tmp is normally writable.
    candidates.append(BASE / "data")
    errors = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            return _prepare_writable_dir(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("No writable data directory available. " + " | ".join(errors))

DATA = _select_data_dir()
UPLOADS = DATA / "uploads"
RUNTIMES = DATA / "runtimes"
LOGS = DATA / "logs"
for p in (UPLOADS, RUNTIMES, LOGS):
    p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
# Keep browser sessions signed and persistent until logout or expiry (365 days).
# Render's generated SECRET_KEY must remain stable between deploys.
app.config.update(
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("RENDER_EXTERNAL_URL", "").startswith("https://"),
)
DB = DATA / "hosting.db"
ALLOWED = {".py", ".js", ".zip"}
processes = {}
process_lock = threading.Lock()

# Supabase Storage persistence. The bucket must be PRIVATE. The SQLite database
# is stored as a single object for this single-instance starter; do not run
# multiple web instances against this snapshot-based database.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "bot-files").strip()
_storage_db_lock = threading.RLock()
_db_sync_lock = threading.Lock()

def _storage_enabled():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and SUPABASE_STORAGE_BUCKET)

def _storage_url(object_path):
    bucket = quote(SUPABASE_STORAGE_BUCKET, safe="")
    path = quote(object_path.lstrip("/"), safe="/")
    return f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"

def _storage_request(method, object_path, data=None, content_type="application/octet-stream"):
    if not _storage_enabled():
        return None
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": "Bearer " + SUPABASE_SERVICE_KEY,
        "Content-Type": content_type,
        "Cache-Control": "no-cache",
    }
    if method == "POST":
        headers["x-upsert"] = "true"
    req = urllib.request.Request(_storage_url(object_path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read()
    except Exception as exc:
        # A 404 while restoring a not-yet-uploaded object is normal; callers
        # decide whether a missing object is fatal.
        try:
            sys.stderr.write(f"[supabase-storage] {method} {object_path} failed: {type(exc).__name__}: {exc}\\n")
        except Exception:
            pass
        return None

def _storage_upload_bytes(object_path, data, content_type="application/octet-stream"):
    if not _storage_enabled():
        return False
    return _storage_request("POST", object_path, data=data, content_type=content_type) is not None

def _storage_upload_file(local_path, object_path):
    try:
        with open(local_path, "rb") as handle:
            data = handle.read()
        return _storage_upload_bytes(object_path, data)
    except OSError as exc:
        sys.stderr.write(f"[supabase-storage] read failed: {exc}\\n")
        return False

def _storage_download_file(object_path, local_path):
    if not _storage_enabled():
        return False
    data = _storage_request("GET", object_path)
    if data is None:
        return False
    destination = Path(local_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    try:
        temporary.write_bytes(data)
        temporary.replace(destination)
        return True
    except OSError as exc:
        sys.stderr.write(f"[supabase-storage] save failed: {exc}\\n")
        temporary.unlink(missing_ok=True)
        return False

def _storage_delete(object_path):
    if not _storage_enabled():
        return False
    # Supabase Storage's DELETE response can be empty; a non-None byte string
    # (including b"") means the HTTP request succeeded.
    return _storage_request("DELETE", object_path) is not None

def _restore_database_snapshot():
    if _storage_enabled() and not DB.exists():
        _storage_download_file("_system/hosting.db", DB)

# Restore the last database snapshot before creating tables or serving requests.
_restore_database_snapshot()

@contextmanager
def db():
    # A process-local lock prevents two requests in this single web instance
    # from uploading competing snapshots at the same time.
    with _storage_db_lock:
        conn = sqlite3.connect(DB, timeout=30)
        conn.row_factory = sqlite3.Row
        before = conn.total_changes
        changed = False
        try:
            yield conn
            conn.commit()
            changed = conn.total_changes > before
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            if changed and _storage_enabled():
                # Synchronous snapshot makes successful writes durable before
                # the request returns. Supabase failures are logged; local app
                # operations continue, so check Render logs for storage errors.
                with _db_sync_lock:
                    if not _storage_upload_file(DB, "_system/hosting.db"):
                        sys.stderr.write("[supabase-storage] database snapshot sync failed; latest changes may not survive a restart.\\n")

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
          is_admin INTEGER DEFAULT 0, credits INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS bots(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, filename TEXT NOT NULL,
          status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_error TEXT DEFAULT '',
          FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS plans(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL NOT NULL, credits INTEGER NOT NULL,
          bot_limit INTEGER NOT NULL, days INTEGER NOT NULL, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS payments(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, utr TEXT NOT NULL,
          status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS api_tokens(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
          token_prefix TEXT NOT NULL, scopes TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          expires_at TEXT, last_used_at TEXT, revoked_at TEXT);
        """)
        if not c.execute("SELECT id FROM users WHERE is_admin=1").fetchone():
            admin_user = os.getenv("ADMIN_USERNAME", "admin")
            admin_pass = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
            c.execute("INSERT OR IGNORE INTO users(username,password,is_admin,credits) VALUES(?,?,1,9999)",
                      (admin_user, generate_password_hash(admin_pass)))
        if not c.execute("SELECT id FROM plans").fetchone():
            c.executemany("INSERT INTO plans(name,price,credits,bot_limit,days) VALUES(?,?,?,?,?)", [
                ("Starter", 30, 10, 2, 30), ("Pro", 99, 40, 10, 30), ("Power", 199, 100, 25, 90)])
        defaults = {"site_name":"CYBER HOST", "support_text":"Contact support through your official support channel.",
                    "upi_id":"your-upi@bank", "payment_qr_url":"", "payment_qr_storage_path":"",
                    "payment_qr_content_type":"image/png", "payment_qr_filename":"", "maintenance":"0"}
        for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
init_db()

def setting(key):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""

@app.context_processor
def inject_globals():
    return {"site_name": setting("site_name"), "support_text": setting("support_text"),
            "current_user": get_user(), "maintenance": setting("maintenance") == "1",
            "payment_qr_url": setting("payment_qr_url"), "payment_upi_id": setting("upi_id"),
            "payment_qr_filename": setting("payment_qr_filename"),
            "session_days": 365, "keep_alive_enabled": _keep_alive_base_url() is not None,
            "keep_alive_interval": _keep_alive_interval_minutes()}

def _keep_alive_interval_minutes():
    try:
        return max(5, min(14, int(os.getenv("KEEP_ALIVE_INTERVAL_MINUTES", "10"))))
    except (TypeError, ValueError):
        return 10

def _keep_alive_base_url():
    if os.getenv("KEEP_ALIVE_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    base = (os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not base.startswith(("https://", "http://")):
        return None
    return base

@app.get("/health")
@app.get("/ping")
def health():
    return Response("ok\n", status=200, mimetype="text/plain", headers={"Cache-Control": "no-store"})

def _keep_alive_loop():
    base = _keep_alive_base_url()
    if not base:
        return
    interval = _keep_alive_interval_minutes() * 60
    target = base + "/health?source=keepalive"
    time.sleep(min(60, interval))
    while True:
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "CyberHost-KeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=15) as response:
                response.read(128)
        except Exception as exc:
            try:
                sys.stderr.write("[keepalive] Ping failed: " + type(exc).__name__ + ": " + str(exc) + "\n")
            except Exception:
                pass
        time.sleep(interval)

def _start_keep_alive():
    if _keep_alive_base_url():
        threading.Thread(target=_keep_alive_loop, name="keep-alive", daemon=True).start()

API_SCOPES = {
    "site:read": "Read basic website settings",
    "users:read": "List registered users",
    "bots:read": "List bots and read statuses",
    "bots:control": "Approve, reject, stop or restart bots",
    "bots:delete": "Delete bots and their stored files",
    "payments:read": "Read payment requests and statuses",
}

def api_json_error(message, status):
    return Response(json.dumps({"error": message}, ensure_ascii=False), status=status,
                    mimetype="application/json", headers={"Cache-Control": "no-store"})

def _api_token_from_request():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    raw = auth[7:].strip()
    if not raw or len(raw) > 300:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with db() as c:
        row = c.execute("SELECT * FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL", (digest,)).fetchone()
        if not row:
            return None
        if row["expires_at"]:
            try:
                from datetime import datetime, timezone
                expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                return None
        c.execute("UPDATE api_tokens SET last_used_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        return {"id": row["id"], "name": row["name"], "scopes": set(filter(None, row["scopes"].split(",")))}

def api_auth(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        token = _api_token_from_request()
        if not token:
            return api_json_error("Missing, invalid, expired, or revoked bearer token.", 401)
        request.api_token = token
        return fn(*args, **kwargs)
    return wrap

def api_scope_required(scope):
    def decorator(fn):
        @wraps(fn)
        @api_auth
        def wrap(*args, **kwargs):
            if scope not in request.api_token["scopes"]:
                return api_json_error("Token lacks required scope: " + scope, 403)
            return fn(*args, **kwargs)
        return wrap
    return decorator

def api_bot_dict(bot):
    return {key: bot[key] for key in ("id", "user_id", "name", "filename", "status", "created_at", "last_error")}

@app.get("/api/v1")
def api_index():
    return Response(json.dumps({
        "name": "CYBER HOST API", "version": "v1",
        "authentication": "Authorization: Bearer <token>",
        "endpoints": {
            "GET /api/v1/me": "Token identity and granted scopes",
            "GET /api/v1/settings": "site:read",
            "GET /api/v1/users": "users:read",
            "GET /api/v1/bots": "bots:read",
            "GET /api/v1/bots/<id>": "bots:read",
            "POST /api/v1/bots/<id>/actions/approve|reject|stop|restart": "bots:control",
            "DELETE /api/v1/bots/<id>": "bots:delete",
            "GET /api/v1/payments": "payments:read"
        },
        "note": "Create and scope tokens in the Admin console. Never expose tokens in browser code."
    }, ensure_ascii=False), mimetype="application/json", headers={"Cache-Control": "no-store"})

@app.get("/api/v1/me")
@api_auth
def api_me():
    return Response(json.dumps({"token_id": request.api_token["id"], "name": request.api_token["name"],
                                "scopes": sorted(request.api_token["scopes"])}, ensure_ascii=False),
                    mimetype="application/json", headers={"Cache-Control": "no-store"})

@app.get("/api/v1/settings")
@api_scope_required("site:read")
def api_settings():
    with db() as c:
        values = {r["key"]: r["value"] for r in c.execute(
            "SELECT key,value FROM settings WHERE key IN ('site_name','support_text','maintenance')").fetchall()}
    return Response(json.dumps({"settings": values}, ensure_ascii=False), mimetype="application/json")

@app.get("/api/v1/users")
@api_scope_required("users:read")
def api_users():
    with db() as c:
        rows = c.execute("SELECT id,username,is_admin,credits,created_at FROM users ORDER BY id DESC LIMIT 500").fetchall()
    return Response(json.dumps({"users": [dict(r) for r in rows]}, ensure_ascii=False), mimetype="application/json")

@app.get("/api/v1/bots")
@api_scope_required("bots:read")
def api_bots():
    with db() as c:
        rows = c.execute("SELECT * FROM bots WHERE status!='deleted' ORDER BY id DESC LIMIT 500").fetchall()
    return Response(json.dumps({"bots": [api_bot_dict(r) for r in rows]}, ensure_ascii=False), mimetype="application/json")

@app.get("/api/v1/bots/<int:bot_id>")
@api_scope_required("bots:read")
def api_bot_detail(bot_id):
    with db() as c:
        row = c.execute("SELECT * FROM bots WHERE id=? AND status!='deleted'", (bot_id,)).fetchone()
    if not row:
        return api_json_error("Bot not found.", 404)
    return Response(json.dumps({"bot": api_bot_dict(row)}, ensure_ascii=False), mimetype="application/json")

@app.post("/api/v1/bots/<int:bot_id>/actions/<action>")
@api_scope_required("bots:control")
def api_bot_control(bot_id, action):
    if action not in ("approve", "reject", "stop", "restart"):
        return api_json_error("Action must be approve, reject, stop, or restart.", 400)
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=? AND status!='deleted'", (bot_id,)).fetchone()
    if not bot:
        return api_json_error("Bot not found.", 404)
    if action == "approve":
        with db() as c: c.execute("UPDATE bots SET status='approved',last_error='' WHERE id=?", (bot_id,))
        with db() as c: fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        threading.Thread(target=run_bot, args=(fresh,), daemon=True).start()
    elif action == "reject":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='rejected' WHERE id=?", (bot_id,))
    elif action == "stop":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='stopped' WHERE id=?", (bot_id,))
    else:
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='approved' WHERE id=?", (bot_id,))
        with db() as c: fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        threading.Thread(target=run_bot, args=(fresh,), daemon=True).start()
    with db() as c:
        fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
    return Response(json.dumps({"ok": True, "action": action, "bot": api_bot_dict(fresh)}, ensure_ascii=False),
                    mimetype="application/json")

@app.delete("/api/v1/bots/<int:bot_id>")
@api_scope_required("bots:delete")
def api_bot_delete(bot_id):
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=? AND status!='deleted'", (bot_id,)).fetchone()
    if not bot:
        return api_json_error("Bot not found.", 404)
    stop_process(bot_id)
    with db() as c: c.execute("UPDATE bots SET status='deleted' WHERE id=?", (bot_id,))
    shutil.rmtree(RUNTIMES / str(bot_id), ignore_errors=True)
    try: (UPLOADS / bot["filename"]).unlink(missing_ok=True)
    except OSError: pass
    if _storage_enabled():
        _storage_delete("uploads/" + bot["filename"])
    return Response(json.dumps({"ok": True, "deleted_bot_id": bot_id}), mimetype="application/json")

@app.get("/api/v1/payments")
@api_scope_required("payments:read")
def api_payments():
    with db() as c:
        rows = c.execute("""SELECT payments.id,payments.user_id,users.username,payments.plan_id,
            plans.name plan_name,payments.utr,payments.status,payments.created_at
            FROM payments JOIN users ON users.id=payments.user_id
            JOIN plans ON plans.id=payments.plan_id ORDER BY payments.id DESC LIMIT 500""").fetchall()
    return Response(json.dumps({"payments": [dict(r) for r in rows]}, ensure_ascii=False), mimetype="application/json")

def get_user():
    uid = session.get("uid")
    if not uid: return None
    with db() as c: return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrap(*a, **kw):
        if not get_user():
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrap

def admin_required(fn):
    @wraps(fn)
    def wrap(*a, **kw):
        u = get_user()
        if not u: return redirect(url_for("login"))
        if not u["is_admin"]: abort(403)
        return fn(*a, **kw)
    return wrap

def bot_count(uid):
    with db() as c:
        return c.execute("SELECT COUNT(*) n FROM bots WHERE user_id=? AND status!='deleted'", (uid,)).fetchone()["n"]

@app.get("/")
def index():
    with db() as c:
        plans = c.execute("SELECT * FROM plans WHERE active=1 ORDER BY price").fetchall()
        stats = {"bots": c.execute("SELECT COUNT(*) n FROM bots WHERE status='running'").fetchone()["n"],
                 "users": c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
                 "plans": len(plans)}
    return render_template("index.html", plans=plans, stats=stats)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if len(username) < 3 or len(password) < 8:
            flash("Username must be 3+ characters and password 8+ characters.", "danger")
        else:
            try:
                with db() as c:
                    c.execute("INSERT INTO users(username,password,credits) VALUES(?,?,1)",
                              (username, generate_password_hash(password)))
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "danger")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with db() as c: user = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear(); session["uid"] = user["id"]; session.permanent = True
            return redirect(url_for("admin") if user["is_admin"] else url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("auth.html", mode="login")

@app.get("/logout")
def logout():
    session.clear(); return redirect(url_for("index"))

@app.get("/dashboard")
@login_required
def dashboard():
    u = get_user()
    with db() as c:
        bots = c.execute("SELECT * FROM bots WHERE user_id=? AND status!='deleted' ORDER BY id DESC",(u["id"],)).fetchall()
        plans = c.execute("SELECT * FROM plans WHERE active=1 ORDER BY price",( )).fetchall()
        payments = c.execute("SELECT payments.*, plans.name plan_name, plans.price plan_price, plans.credits plan_credits FROM payments JOIN plans ON plans.id=payments.plan_id WHERE user_id=? ORDER BY payments.id DESC",(u["id"],)).fetchall()
        purchase_summary = c.execute("SELECT COUNT(*) count, COALESCE(SUM(plans.price),0) total FROM payments JOIN plans ON plans.id=payments.plan_id WHERE payments.user_id=? AND payments.status='approved'", (u["id"],)).fetchone()
    return render_template("dashboard.html", bots=bots, plans=plans, payments=payments, user=u,
                           purchase_summary=purchase_summary, bot_limit=10**6 if u["is_admin"] else 2)


@app.get("/bots")
@login_required
def my_bots():
    u=get_user()
    with db() as c: bots=c.execute("SELECT * FROM bots WHERE user_id=? AND status!='deleted' ORDER BY id DESC",(u["id"],)).fetchall()
    return render_template("workspace.html", page="bots", bots=bots, user=u)

@app.get("/create")
@login_required
def create_bot_page():
    return render_template("workspace.html", page="create", user=get_user())

@app.get("/store")
@login_required
def store_page():
    u=get_user()
    with db() as c:
        plans=c.execute("SELECT * FROM plans WHERE active=1 ORDER BY price").fetchall()
        payments=c.execute("SELECT payments.*,plans.name plan_name,plans.price plan_price FROM payments JOIN plans ON plans.id=payments.plan_id WHERE user_id=? ORDER BY payments.id DESC",(u["id"],)).fetchall()
    return render_template("workspace.html", page="store", user=u, plans=plans, payments=payments)

@app.get("/payments")
@login_required
def payments_page():
    u=get_user()
    with db() as c: payments=c.execute("SELECT payments.*,plans.name plan_name,plans.price plan_price FROM payments JOIN plans ON plans.id=payments.plan_id WHERE user_id=? ORDER BY payments.id DESC",(u["id"],)).fetchall()
    return render_template("workspace.html", page="payments", user=u, payments=payments)

@app.get("/profile")
@login_required
def profile_page():
    u=get_user()
    with db() as c: bot_total=c.execute("SELECT COUNT(*) n FROM bots WHERE user_id=? AND status!='deleted'",(u["id"],)).fetchone()["n"]
    return render_template("workspace.html", page="profile", user=u, bot_total=bot_total)

def _admin_page_data():
    with db() as c:
        users=c.execute("""SELECT users.id,users.username,users.is_admin,users.credits,users.created_at,
          COALESCE((SELECT SUM(plans.price) FROM payments JOIN plans ON plans.id=payments.plan_id WHERE payments.user_id=users.id AND payments.status='approved'),0) purchased_total,
          (SELECT COUNT(*) FROM payments WHERE payments.user_id=users.id AND payments.status='approved') purchase_count FROM users ORDER BY users.id DESC""").fetchall()
        bots=c.execute("SELECT bots.*,users.username FROM bots JOIN users ON users.id=bots.user_id WHERE status!='deleted' ORDER BY bots.id DESC").fetchall()
        payments=c.execute("SELECT payments.*,users.username,plans.name plan_name,plans.price plan_price,plans.credits plan_credits FROM payments JOIN users ON users.id=payments.user_id JOIN plans ON plans.id=payments.plan_id ORDER BY payments.id DESC").fetchall()
        plans=c.execute("SELECT * FROM plans ORDER BY price").fetchall()
        settings={r["key"]:r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
        api_tokens=c.execute("SELECT id,name,token_prefix,scopes,created_at,expires_at,last_used_at,revoked_at FROM api_tokens ORDER BY id DESC").fetchall()
    return users,bots,payments,plans,settings,api_tokens

@app.get("/admin/bots")
@admin_required
def admin_bots_page():
    return render_template("workspace.html",page="admin_bots",bots=_admin_page_data()[1])

@app.get("/admin/payments")
@admin_required
def admin_payments_page():
    return render_template("workspace.html",page="admin_payments",payments=_admin_page_data()[2])

@app.get("/admin/users")
@admin_required
def admin_users_page():
    return render_template("workspace.html",page="admin_users",users=_admin_page_data()[0])

@app.get("/admin/settings")
@admin_required
def admin_settings_page():
    data=_admin_page_data()
    return render_template("workspace.html",page="admin_settings",settings=data[4])

@app.get("/admin/plans")
@admin_required
def admin_plans_page():
    return render_template("workspace.html",page="admin_plans",plans=_admin_page_data()[3])

@app.get("/admin/api")
@admin_required
def admin_api_page():
    data=_admin_page_data()
    token=session.pop("new_api_token",None)
    return render_template("workspace.html",page="admin_api",api_tokens=data[5],api_scopes=API_SCOPES,new_api_token=token)

@app.post("/upload")
@login_required
def upload():
    u = get_user()
    f = request.files.get("file")
    name = request.form.get("name","").strip() or (f.filename if f else "My bot")
    if not f or not f.filename:
        flash("Choose a .py, .js or .zip file.", "danger"); return redirect(url_for("dashboard"))
    safe = secure_filename(f.filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED:
        flash("Only .py, .js and .zip files are accepted.", "danger"); return redirect(url_for("dashboard"))
    if bot_count(u["id"]) >= (10**6 if u["is_admin"] else 2):
        flash("Your current demo limit is 2 bots. Configure plan entitlements before production.", "warning")
        return redirect(url_for("dashboard"))
    token = secrets.token_hex(6)
    stored = f"{u['id']}_{token}_{safe}"
    local_upload = UPLOADS / stored
    f.save(local_upload)
    if _storage_enabled() and not _storage_upload_file(local_upload, "uploads/" + stored):
        local_upload.unlink(missing_ok=True)
        flash("Supabase Storage upload failed. Check SUPABASE_URL, SUPABASE_SERVICE_KEY and the private bot-files bucket.", "danger")
        return redirect(url_for("dashboard"))
    initial_status = "approved" if u["is_admin"] else "pending"
    try:
        with db() as c:
            c.execute("INSERT INTO bots(user_id,name,filename,status) VALUES(?,?,?,?)",
                      (u["id"], name[:80], stored, initial_status))
    except Exception:
        local_upload.unlink(missing_ok=True)
        if _storage_enabled():
            _storage_delete("uploads/" + stored)
        raise
    if u["is_admin"]:
        with db() as c:
            created_bot = c.execute("SELECT * FROM bots WHERE filename=?", (stored,)).fetchone()
        threading.Thread(target=run_bot, args=(created_bot,), name=f"admin-bot-{created_bot['id']}", daemon=True).start()
        flash("Admin upload approved automatically; launch requested.", "success")
    else:
        flash("Upload received. It is pending admin review before it can run.", "success")
    return redirect(url_for("dashboard"))

def _write_log(bot_id, message):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / f"{bot_id}.log").open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}] {message}\n")
        handle.flush()

def _recent_log_excerpt(bot_id, max_chars=5000):
    """Return enough recent output to include startup tracebacks and pip errors."""
    try:
        path = LOGS / f"{bot_id}.log"
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_chars * 4))
            data = handle.read().decode("utf-8", errors="replace")
        lines = [line for line in data.splitlines() if line.strip()]
        return "\n".join(lines[-50:])[-max_chars:]
    except OSError:
        return ""

def stop_process(bot_id):
    with process_lock:
        proc = processes.pop(bot_id, None)
    if proc and proc.poll() is None:
        _write_log(bot_id, "[control] Stop requested.")
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        _write_log(bot_id, f"[control] Process stopped (exit code {proc.returncode}).")

def _detect_python_packages(entry):
    """Infer a conservative set of common third-party packages for single-file uploads."""
    module_to_package = {
        "requests": "requests", "telegram": "python-telegram-bot",
        "telebot": "pyTelegramBotAPI", "aiogram": "aiogram",
        "discord": "discord.py", "aiohttp": "aiohttp",
        "bs4": "beautifulsoup4", "PIL": "Pillow",
        "dotenv": "python-dotenv", "pymongo": "pymongo",
        "motor": "motor", "yt_dlp": "yt-dlp",
        "cv2": "opencv-python-headless", "numpy": "numpy",
        "pandas": "pandas", "flask": "Flask",
        "httpx": "httpx", "openai": "openai",
        "google": "google-api-python-client", "yaml": "PyYAML",
        "schedule": "schedule", "apscheduler": "APScheduler",
        "bs4": "beautifulsoup4", "cryptography": "cryptography",
    }
    try:
        tree = ast.parse(entry.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, UnicodeError):
        return []
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    stdlib = getattr(sys, "stdlib_module_names", set())
    return sorted({module_to_package[m] for m in modules if m in module_to_package and m not in stdlib})

def _run_setup_command(command, cwd, env, log, label, timeout=360):
    """Run dependency setup with explicit diagnostics and one conservative pip retry."""
    base_command = list(command)
    is_pip_install = (
        len(base_command) >= 3
        and Path(base_command[0]).name.startswith("python")
        and base_command[1:3] == ["-m", "pip"]
        and "install" in base_command
    )
    attempts = 2 if is_pip_install else 1
    last_code = None
    for attempt in range(1, attempts + 1):
        run_command = list(base_command)
        if is_pip_install:
            # Avoid filling the small ephemeral container with pip's download cache
            # and bytecode compilation; prefer prebuilt wheels where available.
            additions = ["--no-cache-dir", "--prefer-binary", "--no-compile"]
            insert_at = run_command.index("install") + 1
            for option in additions:
                if option not in run_command:
                    run_command.insert(insert_at, option)
                    insert_at += 1
        log.write(f"[setup] {label} (attempt {attempt}/{attempts}): {' '.join(run_command)}\n")
        log.flush()
        run_env = os.environ.copy()
        run_env.update(env or {})
        if is_pip_install:
            run_env["PIP_NO_CACHE_DIR"] = "1"
            run_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        try:
            result = subprocess.run(
                run_command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                env=run_env, timeout=timeout, check=False
            )
            last_code = result.returncode
        except subprocess.TimeoutExpired:
            log.write(f"[setup] {label} timed out after {timeout} seconds on attempt {attempt}.\n")
            log.flush()
            last_code = "timeout"
        if last_code == 0:
            log.write(f"[setup] {label} completed successfully.\n")
            log.flush()
            return
        log.write(f"[setup] {label} failed on attempt {attempt} (exit={last_code}).\n")
        log.flush()
        if attempt < attempts:
            log.write("[setup] Retrying dependency installation once without pip cache/bytecode compilation.\n")
            log.flush()
    details = _recent_log_excerpt_from_handle(log) if False else ""
    raise RuntimeError(
        f"{label} failed after {attempts} attempt(s) (exit={last_code}). "
        "Open Live logs and check the final pip ERROR lines; common causes are an invalid "
        "package/version, incompatible Python version, or the host running out of memory."
    )

def run_bot(bot):
    bot_id = bot["id"]
    source = UPLOADS / bot["filename"]
    # Rehydrate the original upload from durable storage after a Render restart.
    if not source.is_file() and _storage_enabled():
        _storage_download_file("uploads/" + bot["filename"], source)
    runtime = RUNTIMES / str(bot_id)
    # Start from a clean project folder so a previous failed setup cannot leave
    # stale dependencies or entry files behind.
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{bot_id}.log"
    proc = None
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}] [system] Launch requested for {bot['name']}\n")
            log.flush()
            ext = source.suffix.lower()
            if not source.is_file():
                raise FileNotFoundError("Uploaded source file is missing. Re-upload the project.")
            if ext == ".zip":
                with zipfile.ZipFile(source) as archive:
                    total_uncompressed = sum(info.file_size for info in archive.infolist())
                    if total_uncompressed > 100 * 1024 * 1024:
                        raise ValueError("ZIP expands to over 100 MB; reduce the project size and upload again.")
                    for info in archive.infolist():
                        target = (runtime / info.filename).resolve()
                        if not str(target).startswith(str(runtime.resolve()) + os.sep):
                            raise ValueError("Unsafe path in ZIP archive.")
                        if (info.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("Symlinks are not allowed in ZIP uploads.")
                    archive.extractall(runtime)
                # If the archive contains one project folder, use its contents as
                # the project root for entry-file and manifest discovery.
                project_root = runtime
                top_dirs = [p for p in runtime.iterdir() if p.is_dir()]
                top_files = [p for p in runtime.iterdir() if p.is_file()]
                if len(top_dirs) == 1 and not top_files:
                    project_root = top_dirs[0]
                py_files = list(project_root.rglob("*.py"))
                js_files = list(project_root.rglob("*.js"))
                preferred = ("main.py", "bot.py", "app.py", "run.py", "index.js", "bot.js", "main.js")
                candidates = sorted(
                    py_files + js_files,
                    key=lambda p: (p.name.lower() not in preferred, len(p.relative_to(project_root).parts), str(p))
                )
                if not candidates:
                    raise ValueError("ZIP must contain a Python or JavaScript entry file (for example bot.py or index.js).")
                entry = candidates[0]
            else:
                project_root = runtime
                entry = runtime / source.name
                shutil.copy2(source, entry)

            env = os.environ.copy()
            env.update({
                "HOME": str(runtime),
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": os.pathsep.join(filter(None, [str(project_root), str(runtime / "vendor"), env.get("PYTHONPATH", "")])),
                "npm_config_audit": "false",
                "npm_config_fund": "false",
            })

            # Python: install requirements.txt automatically. For a lone .py file,
            # infer a small allowlist of common packages; custom packages should be
            # declared in requirements.txt inside a ZIP project.
            if entry.suffix.lower() == ".py":
                vendor = runtime / "vendor"
                vendor.mkdir(parents=True, exist_ok=True)
                req_files = sorted(project_root.rglob("requirements.txt"))
                if req_files:
                    req = req_files[0]
                    _run_setup_command(
                        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                         "--no-warn-script-location", "--target", str(vendor), "-r", str(req)],
                        project_root, env, log, f"Install Python requirements ({req.relative_to(project_root)})"
                    )
                else:
                    inferred = _detect_python_packages(entry)
                    if inferred:
                        log.write("[setup] Detected common imports: " + ", ".join(inferred) + "\n")
                        _run_setup_command(
                            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                             "--no-warn-script-location", "--target", str(vendor), *inferred],
                            project_root, env, log, "Install detected Python packages"
                        )
                    else:
                        log.write("[setup] No known third-party imports detected; skipping pip install.\n")
                cmd = [sys.executable, "-u", str(entry)]

            # JavaScript: install package.json dependencies when present. The Docker
            # runtime includes Node.js/npm; on other runtimes, show a useful error.
            elif entry.suffix.lower() == ".js":
                node = shutil.which("node")
                npm = shutil.which("npm")
                if not node:
                    raise RuntimeError("Node.js is unavailable. Deploy this repo with its Dockerfile/runtime to enable .js bots.")
                package_files = sorted(project_root.rglob("package.json"))
                package_file = package_files[0] if package_files else None
                if package_file:
                    _run_setup_command([npm, "install", "--omit=dev", "--no-audit", "--no-fund"],
                                       package_file.parent, env, log, "Install npm dependencies")
                    try:
                        import json
                        package_data = json.loads(package_file.read_text(encoding="utf-8"))
                    except Exception as exc:
                        raise RuntimeError(f"Could not read package.json: {exc}")
                    start_script = package_data.get("scripts", {}).get("start")
                    if start_script:
                        cmd = [npm, "start"]
                        project_root = package_file.parent
                    else:
                        main_name = package_data.get("main", "index.js")
                        candidate = package_file.parent / main_name
                        cmd = [node, str(candidate if candidate.is_file() else entry)]
                        project_root = package_file.parent
                else:
                    cmd = [node, str(entry)]
            else:
                raise ValueError("Unsupported entry file. Upload a .py, .js, or ZIP project.")

            log.write(f"[system] Starting command: {' '.join(cmd)}\n")
            log.flush()
            proc = subprocess.Popen(
                cmd, cwd=str(project_root), stdout=log, stderr=subprocess.STDOUT,
                env=env, start_new_session=True
            )
            time.sleep(1.0)
            if proc.poll() is not None:
                log.flush()
                details = _recent_log_excerpt(bot_id)
                raise RuntimeError(
                    f"Process exited during startup (exit code {proc.returncode}). "
                    f"Recent bot output: {details or 'No application output was captured.'}"
                )
            with process_lock:
                processes[bot_id] = proc
            with db() as c:
                c.execute("UPDATE bots SET status='running',last_error='' WHERE id=?", (bot_id,))
            log.write("[system] Process is running; stdout/stderr and exceptions are captured below.\n")
            log.flush()

        def monitor():
            exit_code = proc.wait()
            with process_lock:
                if processes.get(bot_id) is proc:
                    processes.pop(bot_id, None)
            with db() as c:
                row = c.execute("SELECT status FROM bots WHERE id=?", (bot_id,)).fetchone()
                if row and row["status"] == "running":
                    details = _recent_log_excerpt(bot_id) if exit_code != 0 else ""
                    error = "" if exit_code == 0 else (
                        f"Process exited with code {exit_code}. "
                        f"Recent output: {details or 'No traceback captured; open Live logs.'}"
                    )
                    c.execute("UPDATE bots SET status=?,last_error=? WHERE id=?",
                              ("stopped" if exit_code == 0 else "error", error[:500], bot_id))
            _write_log(bot_id, f"[system] Process exited with code {exit_code}.")
            if exit_code != 0:
                _write_log(bot_id, "[diagnostic] Last bot output: " + (_recent_log_excerpt(bot_id) or "No output captured."))
        threading.Thread(target=monitor, daemon=True).start()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        _write_log(bot_id, f"[error] {message}")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        with db() as c:
            c.execute("UPDATE bots SET status='error',last_error=? WHERE id=?", (message[:500], bot_id))

def _terminal_project_root(bot_id):
    runtime = (RUNTIMES / str(bot_id)).resolve()
    if not runtime.exists() or not runtime.is_dir():
        return None
    try:
        dirs = [p for p in runtime.iterdir() if p.is_dir()]
        files = [p for p in runtime.iterdir() if p.is_file()]
        if len(dirs) == 1 and not files:
            return dirs[0].resolve()
    except OSError:
        return runtime
    return runtime

def _prepare_terminal_workspace(bot):
    """Prepare a bot's project files for terminal use even before the bot is started."""
    bot_id = bot["id"]
    runtime = RUNTIMES / str(bot_id)
    if runtime.exists() and any(runtime.iterdir()):
        return _terminal_project_root(bot_id)
    source = UPLOADS / bot["filename"]
    if not source.is_file() and _storage_enabled():
        _storage_download_file("uploads/" + bot["filename"], source)
    if not source.is_file():
        return None
    runtime.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if sum(info.file_size for info in members) > 100 * 1024 * 1024:
                raise ValueError("ZIP expands to over 100 MB; reduce the project size and upload again.")
            root_resolved = runtime.resolve()
            for info in members:
                target = (runtime / info.filename).resolve()
                if target != root_resolved and root_resolved not in target.parents:
                    raise ValueError("Unsafe path in ZIP archive.")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Symlinks are not allowed in ZIP uploads.")
            archive.extractall(runtime)
    elif source.suffix.lower() in (".py", ".js"):
        shutil.copy2(source, runtime / source.name)
    else:
        return None
    return _terminal_project_root(bot_id)

def _terminal_safe_path(root, raw_name):
    candidate = (root / raw_name).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path must stay inside this bot's project directory.")
    return candidate

def _terminal_safe_file(root, raw_name):
    candidate = _terminal_safe_path(root, raw_name)
    if not candidate.is_file():
        raise ValueError("File not found. Use ls to see project files.")
    if candidate.stat().st_size > 256 * 1024:
        raise ValueError("File is larger than the 256 KB terminal-view limit.")
    return candidate

def _terminal_execute(root, command, bot_id):
    import shlex
    parts = shlex.split(command)
    if not parts:
        return "Enter a command. Type help to see supported commands."
    if any(x in command for x in (";", "&&", "||", "|", ">", "<", chr(96), "$(", "\n", "\r")):
        raise ValueError("Shell operators are disabled. Run one command at a time.")
    if parts in (["help"], ["help()"]):
        return (
            "CYBER HOST TERMINAL — supported commands\n"
            "  help                              Show commands\n"
            "  pwd                               Show project directory\n"
            "  ls [relative-path]                List project files\n"
            "  cat <file>                        View a small text file\n"
            "  python --version                  Python version\n"
            "  python <file.py> [args...]        Run a project Python script (20s limit)\n"
            "  python -m py_compile <file.py>    Check Python syntax\n"
            "  pip list                          List project-local Python packages\n"
            "  pip install <package>             Install into this bot's vendor folder\n"
            "  pip install -r requirements.txt   Install project requirements locally\n"
            "  node --version                    Node.js version\n"
            "  node <file.js> [args...]          Run a project JS script (20s limit)\n"
            "  node --check <file.js>             Check JavaScript syntax\n"
            "  npm --version                     npm version\n"
            "  npm list                          List project packages\n\n"
            "Commands run one at a time inside this bot project. Shell operators,\n"
            "system administration commands, network tools and paths outside the project are blocked."
        )
    if parts == ["pwd"]:
        return str(root)
    if parts[0] == "ls" and len(parts) <= 2:
        target = _terminal_safe_path(root, parts[1] if len(parts) == 2 else ".")
        if not target.exists() or not target.is_dir():
            raise ValueError("Directory not found.")
        rows = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
            rows.append(("DIR  " if item.is_dir() else "FILE ") + item.name + ("/" if item.is_dir() else ""))
        return "\n".join(rows) if rows else "(empty directory)"
    if parts[0] == "cat" and len(parts) == 2:
        return _terminal_safe_file(root, parts[1]).read_text(encoding="utf-8", errors="replace")[:20000]
    if parts == ["python", "--version"]:
        result = subprocess.run([sys.executable, "--version"], cwd=str(root), capture_output=True, text=True, timeout=5)
        return (result.stdout + result.stderr).strip()
    vendor = (RUNTIMES / str(bot_id) / "vendor").resolve()
    vendor.mkdir(parents=True, exist_ok=True)
    if parts == ["pip", "list"]:
        result = subprocess.run([sys.executable, "-m", "pip", "list", "--path", str(vendor), "--format=columns"],
                                cwd=str(root), capture_output=True, text=True, timeout=8)
        return (result.stdout + result.stderr).strip()[-20000:] or "No project-local Python packages installed."
    if len(parts) >= 3 and parts[:2] == ["pip", "install"]:
        if parts[2] == "-r":
            if len(parts) != 4:
                raise ValueError("Use: pip install -r requirements.txt")
            req_file = _terminal_safe_file(root, parts[3])
            if req_file.name != "requirements.txt":
                raise ValueError("For safety, pip install -r only accepts a project requirements.txt file.")
            packages = ["-r", str(req_file)]
        else:
            packages = parts[2:]
            if any(p.startswith("-") for p in packages):
                raise ValueError("pip options are restricted. Use: pip install package-name")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                                 "--no-warn-script-location", "--target", str(vendor), *packages],
                                cwd=str(root), capture_output=True, text=True, timeout=90)
        return ((result.stdout or "") + (result.stderr or "")).strip()[-20000:] or f"pip exited with code {result.returncode}."
    if parts in (["npm", "--version"], ["node", "--version"]):
        binary = shutil.which(parts[0])
        if not binary:
            return f"{parts[0]} is not installed in this runtime."
        result = subprocess.run([binary, "--version"], cwd=str(root), capture_output=True, text=True, timeout=5)
        return (result.stdout + result.stderr).strip()
    if parts == ["npm", "list"]:
        npm = shutil.which("npm")
        if not npm:
            return "npm is not installed in this runtime."
        result = subprocess.run([npm, "list", "--depth=0"], cwd=str(root), capture_output=True, text=True, timeout=8)
        return (result.stdout + result.stderr).strip()[-20000:]
    if len(parts) == 4 and parts[:3] == ["python", "-m", "py_compile"]:
        target = _terminal_safe_file(root, parts[3])
        if target.suffix.lower() != ".py":
            raise ValueError("py_compile only accepts a .py file.")
        result = subprocess.run([sys.executable, "-m", "py_compile", str(target)], cwd=str(root),
                                capture_output=True, text=True, timeout=8)
        return (result.stdout + result.stderr).strip() or ("Python syntax OK." if result.returncode == 0 else f"Exited with code {result.returncode}.")
    if len(parts) == 3 and parts[:2] == ["node", "--check"]:
        target = _terminal_safe_file(root, parts[2])
        if target.suffix.lower() not in (".js", ".mjs", ".cjs"):
            raise ValueError("node --check only accepts a JavaScript file.")
        node = shutil.which("node")
        if not node:
            return "Node.js is not installed in this runtime."
        result = subprocess.run([node, "--check", str(target)], cwd=str(root), capture_output=True, text=True, timeout=8)
        return (result.stdout + result.stderr).strip() or ("JavaScript syntax OK." if result.returncode == 0 else f"Exited with code {result.returncode}.")
    if len(parts) >= 2 and parts[0] == "python":
        target = _terminal_safe_file(root, parts[1])
        if target.suffix.lower() != ".py":
            raise ValueError("python can only run a project .py file.")
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        vendor = (RUNTIMES / str(bot_id) / "vendor").resolve()
        env["PYTHONPATH"] = str(vendor) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        result = subprocess.run([sys.executable, str(target), *parts[2:]], cwd=str(root), env=env,
                                capture_output=True, text=True, timeout=20)
        return ((result.stdout or "") + (result.stderr or "")).strip() or f"Process exited with code {result.returncode} (no output)."
    if len(parts) >= 2 and parts[0] == "node":
        target = _terminal_safe_file(root, parts[1])
        if target.suffix.lower() not in (".js", ".mjs", ".cjs"):
            raise ValueError("node can only run a project JavaScript file.")
        node = shutil.which("node")
        if not node:
            return "Node.js is not installed in this runtime."
        result = subprocess.run([node, str(target), *parts[2:]], cwd=str(root),
                                capture_output=True, text=True, timeout=20)
        return ((result.stdout or "") + (result.stderr or "")).strip() or f"Process exited with code {result.returncode} (no output)."
    raise ValueError("Command not supported. Type help. Arbitrary Linux shell commands and package installation are disabled on this shared host.")

def _terminal_authorized_bot(bot_id):
    u = get_user()
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=? AND status!='deleted'", (bot_id,)).fetchone()
    if not u or not bot or (bot["user_id"] != u["id"] and not u["is_admin"]):
        abort(404)
    return u, bot

@app.route("/bot/<int:bot_id>/terminal", methods=["GET", "POST"])
@login_required
def bot_terminal(bot_id):
    u, bot = _terminal_authorized_bot(bot_id)
    root = _terminal_project_root(bot_id)
    if not root:
        try:
            root = _prepare_terminal_workspace(bot)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            _write_log(bot_id, "[terminal] Workspace preparation failed: " + str(exc))
    if request.method == "POST":
        payload = request.get_json(silent=True) if request.is_json else None
        form = payload if payload is not None else request.form
        command = str(form.get("command", "")).strip()[:500]
        output = ""
        if not command:
            output = "Enter a command. Type help to see supported commands."
        elif not root:
            output = "Project workspace is unavailable. Check that the uploaded file still exists in storage, then retry."
        else:
            try:
                output = _terminal_execute(root, command, bot_id)
            except subprocess.TimeoutExpired:
                output = "Command timed out. Script commands have a 20-second limit; dependency installs have a 90-second limit."
            except (ValueError, OSError) as exc:
                output = str(exc)
        output = (output or "(command completed with no output)")[-20000:]
        _write_log(bot_id, "[terminal] $ " + command)
        for line in output.splitlines()[-100:]:
            _write_log(bot_id, "[terminal] " + line)
        if request.is_json:
            return Response(json.dumps({"command": command, "output": output, "ok": True}, ensure_ascii=False),
                            mimetype="application/json", headers={"Cache-Control": "no-store"})
        return render_template("terminal.html", bot=bot, command=command, output=output,
                               runtime_ready=bool(root), project_root=str(root) if root else "")
    return render_template("terminal.html", bot=bot, command="", output="",
                           runtime_ready=bool(root), project_root=str(root) if root else "")

@app.get("/bot/<int:bot_id>/terminal/live")
@login_required
def bot_terminal_live(bot_id):
    _u, bot = _terminal_authorized_bot(bot_id)
    path = LOGS / f"{bot_id}.log"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 48 * 1024))
            content = handle.read().decode("utf-8", errors="replace")
    except OSError:
        content = "No logs yet. Start or approve this bot to create logs."
    with process_lock:
        proc = processes.get(bot_id)
        alive = bool(proc and proc.poll() is None)
    return Response(json.dumps({"logs": content[-48000:], "alive": alive}, ensure_ascii=False),
                    mimetype="application/json", headers={"Cache-Control": "no-store"})

@app.get("/bot/<int:bot_id>/logs")
@login_required
def bot_logs(bot_id):
    u = get_user()
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not bot or (bot["user_id"] != u["id"] and not u["is_admin"]):
        abort(404)
    if request.args.get("raw") == "1":
        path = LOGS / f"{bot_id}.log"
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 64 * 1024))
                content = handle.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            content = "No logs yet. Approve or restart this bot to launch it."
        with process_lock:
            proc = processes.get(bot_id)
            alive = bool(proc and proc.poll() is None)
        if not alive:
            with db() as c:
                current = c.execute("SELECT status,last_error FROM bots WHERE id=?", (bot_id,)).fetchone()
            if current and current["status"] == "running":
                with db() as c:
                    c.execute("UPDATE bots SET status='error',last_error=? WHERE id=?",
                              ("Process is no longer running; check logs.", bot_id))
        return Response(content, mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store"})
    return render_template("logs.html", bot=bot)

@app.post("/bot/<int:bot_id>/<action>")
@login_required
def bot_action(bot_id, action):
    u = get_user()
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not bot or (bot["user_id"] != u["id"] and not u["is_admin"]): abort(404)
    if action == "delete":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='deleted' WHERE id=?", (bot_id,))
        shutil.rmtree(RUNTIMES / str(bot_id), ignore_errors=True)
        try: (UPLOADS / bot["filename"]).unlink(missing_ok=True)
        except Exception: pass
        if _storage_enabled():
            _storage_delete("uploads/" + bot["filename"])
        flash("Bot and its stored files were deleted.", "success")
    elif action == "stop":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='stopped' WHERE id=?", (bot_id,))
        flash("Bot stopped.", "success")
    elif action == "restart":
        stop_process(bot_id)
        if bot["status"] not in ("approved", "stopped", "error", "running") and not u["is_admin"]:
            flash("This bot has not been approved by an admin yet.", "warning")
        else:
            with db() as c: c.execute("UPDATE bots SET status='approved' WHERE id=?", (bot_id,))
            with db() as c: fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
            threading.Thread(target=run_bot, args=(fresh,), daemon=True).start()
            flash("Restart requested.", "success")
    else: abort(400)
    return redirect(url_for("admin") if u["is_admin"] else url_for("my_bots"))

@app.get("/admin")
@admin_required
def admin():
    with db() as c:
        users = c.execute("""SELECT users.id,users.username,users.is_admin,users.credits,users.created_at,
            COALESCE((SELECT SUM(plans.price) FROM payments JOIN plans ON plans.id=payments.plan_id
                      WHERE payments.user_id=users.id AND payments.status='approved'),0) purchased_total,
            (SELECT COUNT(*) FROM payments WHERE payments.user_id=users.id AND payments.status='approved') purchase_count
            FROM users ORDER BY users.id DESC""").fetchall()
        bots = c.execute("SELECT bots.*,users.username FROM bots JOIN users ON users.id=bots.user_id WHERE status!='deleted' ORDER BY bots.id DESC").fetchall()
        payments = c.execute("SELECT payments.*,users.username,plans.name plan_name,plans.price plan_price,plans.credits plan_credits FROM payments JOIN users ON users.id=payments.user_id JOIN plans ON plans.id=payments.plan_id ORDER BY payments.id DESC").fetchall()
        plans = c.execute("SELECT * FROM plans ORDER BY price").fetchall()
        overview = {
            "users": c.execute("SELECT COUNT(*) n FROM users WHERE is_admin=0").fetchone()["n"],
            "bots": c.execute("SELECT COUNT(*) n FROM bots WHERE status!='deleted'").fetchone()["n"],
            "running": c.execute("SELECT COUNT(*) n FROM bots WHERE status='running'").fetchone()["n"],
            "pending_bots": c.execute("SELECT COUNT(*) n FROM bots WHERE status='pending'").fetchone()["n"],
            "pending_payments": c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"],
            "revenue": c.execute("SELECT COALESCE(SUM(plans.price),0) total FROM payments JOIN plans ON plans.id=payments.plan_id WHERE payments.status='approved'").fetchone()["total"]
        }
        settings = {r["key"]:r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
        api_tokens = c.execute("SELECT id,name,token_prefix,scopes,created_at,expires_at,last_used_at,revoked_at FROM api_tokens ORDER BY id DESC").fetchall()
    new_api_token = session.pop("new_api_token", None)
    return render_template("admin.html", users=users, bots=bots, payments=payments, plans=plans, settings=settings,
                           overview=overview, api_tokens=api_tokens, api_scopes=API_SCOPES, new_api_token=new_api_token)

@app.post("/admin/api-tokens")
@admin_required
def create_api_token():
    name = request.form.get("name", "").strip()[:80]
    chosen = sorted(set(request.form.getlist("scopes")) & set(API_SCOPES))
    try:
        days = int(request.form.get("days", "90"))
    except ValueError:
        days = 90
    days = max(1, min(365, days))
    if not name or not chosen:
        flash("Give the token a name and choose at least one permission.", "danger")
        return redirect(url_for("admin_api_page"))
    raw = "ch_live_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    from datetime import datetime, timezone, timedelta as dt_timedelta
    expiry = (datetime.now(timezone.utc) + dt_timedelta(days=days)).isoformat(timespec="seconds")
    with db() as c:
        cur = c.execute("INSERT INTO api_tokens(name,token_hash,token_prefix,scopes,expires_at) VALUES(?,?,?,?,?)",
                        (name, digest, raw[:15] + "...", ",".join(chosen), expiry))
        token_id = cur.lastrowid
    session["new_api_token"] = {"id": token_id, "name": name, "token": raw, "scopes": chosen, "expires_at": expiry}
    flash("API token created. Copy it now; the full token will not be shown again.", "success")
    return redirect(url_for("admin_api_page"))

@app.post("/admin/api-tokens/<int:token_id>/revoke")
@admin_required
def revoke_api_token(token_id):
    with db() as c:
        c.execute("UPDATE api_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=? AND revoked_at IS NULL", (token_id,))
    flash("API token revoked. Requests using it will stop working.", "success")
    return redirect(url_for("admin_api_page"))

@app.get("/admin/bot/<int:bot_id>/file")
@admin_required
def admin_bot_file(bot_id):
    with db() as c:
        bot = c.execute("SELECT * FROM bots WHERE id=? AND status!='deleted'", (bot_id,)).fetchone()
    if not bot:
        abort(404)
    source = UPLOADS / bot["filename"]
    if not source.is_file() and _storage_enabled():
        _storage_download_file("uploads/" + bot["filename"], source)
    if not source.is_file():
        return Response("Uploaded file is unavailable. Check Supabase Storage and Render logs.", status=404, mimetype="text/plain")
    is_zip = source.suffix.lower() == ".zip"
    disposition = "attachment" if is_zip else "inline"
    mime = "application/zip" if is_zip else "text/plain; charset=utf-8"
    return Response(source.read_bytes(), mimetype=mime,
                    headers={"Content-Disposition": f'{disposition}; filename="{secure_filename(bot["filename"])}"',
                             "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})

@app.post("/admin/bot/<int:bot_id>/<action>")
@admin_required
def admin_bot(bot_id, action):
    with db() as c: bot = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not bot: abort(404)
    if action == "approve":
        with db() as c: c.execute("UPDATE bots SET status='approved' WHERE id=?", (bot_id,))
        with db() as c: fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        threading.Thread(target=run_bot, args=(fresh,), daemon=True).start()
        flash("Approved; launch requested.", "success")
    elif action == "reject":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='rejected' WHERE id=?", (bot_id,))
        flash("Upload rejected.", "success")
    elif action in ("stop","restart","delete"):
        return bot_action.__wrapped__(bot_id, action)
    else: abort(400)
    return redirect(url_for("admin_bots_page"))

@app.post("/admin/payment/<int:payment_id>/<action>")
@admin_required
def admin_payment(payment_id, action):
    with db() as c:
        payment = c.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not payment: abort(404)
        if action == "approve" and payment["status"] == "pending":
            plan = c.execute("SELECT * FROM plans WHERE id=?", (payment["plan_id"],)).fetchone()
            c.execute("UPDATE payments SET status='approved' WHERE id=?", (payment_id,))
            c.execute("UPDATE users SET credits=credits+? WHERE id=?", (plan["credits"], payment["user_id"]))
        elif action == "reject":
            c.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
        else: abort(400)
    flash("Payment updated.", "success"); return redirect(url_for("admin_payments_page"))

@app.post("/admin/user/<int:user_id>/credits")
@admin_required
def admin_credits(user_id):
    try: amount = int(request.form.get("amount","0"))
    except ValueError: amount = 0
    with db() as c: c.execute("UPDATE users SET credits=MAX(0,credits+?) WHERE id=?", (amount,user_id))
    flash("User credits updated.", "success"); return redirect(url_for("admin_users_page"))

@app.post("/buy")
@login_required
def buy():
    u = get_user()
    try: plan_id = int(request.form.get("plan_id","0"))
    except ValueError: plan_id = 0
    utr = request.form.get("utr","").strip()
    with db() as c: plan = c.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone()
    if not plan or len(utr) < 6:
        flash("Select a plan and enter a valid UTR/reference number.", "danger")
    else:
        with db() as c: c.execute("INSERT INTO payments(user_id,plan_id,utr) VALUES(?,?,?)",(u["id"],plan_id,utr[:100]))
        flash("Payment submitted for admin verification.", "success")
    return redirect(url_for("store_page"))

@app.get("/payment-qr")
def payment_qr():
    """Serve an uploaded QR from private Supabase Storage or local fallback."""
    object_path = setting("payment_qr_storage_path")
    content_type = setting("payment_qr_content_type") or "image/png"
    if object_path and _storage_enabled():
        data = _storage_request("GET", object_path)
        if data is not None:
            return Response(data, mimetype=content_type, headers={"Cache-Control":"private, max-age=300"})
        return Response("Payment QR image is temporarily unavailable.", status=503, mimetype="text/plain")
    local_name = setting("payment_qr_filename")
    if local_name:
        local_path = DATA / secure_filename(local_name)
        if local_path.is_file():
            return Response(local_path.read_bytes(), mimetype=content_type, headers={"Cache-Control":"private, max-age=300"})
    abort(404)

@app.post("/admin/settings")
@admin_required
def save_settings():
    allowed = ["site_name","support_text","upi_id","maintenance"]
    qr_file = request.files.get("payment_qr_file")
    remove_qr = request.form.get("remove_payment_qr") == "1"
    with db() as c:
        for k in allowed:
            val = request.form.get(k, "").strip()
            if k == "maintenance": val = "1" if val == "1" else "0"
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,val[:2000]))

    # An ordinary save or page refresh never clears the saved QR.
    if qr_file and qr_file.filename:
        original = secure_filename(qr_file.filename)
        ext = Path(original).suffix.lower()
        mime_by_ext = {".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".webp":"image/webp"}
        if ext not in mime_by_ext:
            flash("QR image must be PNG, JPG, JPEG, or WEBP.", "danger")
            return redirect(url_for("admin_settings_page"))
        data = qr_file.read()
        if not data or len(data) > 5 * 1024 * 1024:
            flash("Choose a valid QR image up to 5 MB.", "danger")
            return redirect(url_for("admin_settings_page"))
        object_path = "settings/payment-qr" + ext
        content_type = mime_by_ext[ext]
        local_name = "payment-qr" + ext
        (DATA / local_name).write_bytes(data)
        if _storage_enabled() and not _storage_upload_bytes(object_path, data, content_type):
            flash("QR upload failed. Check Supabase Storage configuration and Render logs.", "danger")
            return redirect(url_for("admin_settings_page"))
        with db() as c:
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_storage_path',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (object_path if _storage_enabled() else "",))
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_content_type',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (content_type,))
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_filename',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (local_name,))
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_url','/payment-qr') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    elif remove_qr:
        old_path = setting("payment_qr_storage_path")
        if old_path and _storage_enabled():
            _storage_delete(old_path)
        old_local = setting("payment_qr_filename")
        if old_local:
            try: (DATA / secure_filename(old_local)).unlink(missing_ok=True)
            except OSError: pass
        with db() as c:
            for key in ("payment_qr_url","payment_qr_storage_path","payment_qr_filename"):
                c.execute("INSERT INTO settings(key,value) VALUES(?, '') ON CONFLICT(key) DO UPDATE SET value=''", (key,))
    elif request.form.get("payment_qr_url", "").strip():
        external_url = request.form.get("payment_qr_url", "").strip()[:1000]
        if not external_url.startswith(("https://", "http://")):
            flash("QR URL must start with https:// or http://.", "danger")
            return redirect(url_for("admin_settings_page"))
        with db() as c:
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_url',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (external_url,))
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_storage_path','') ON CONFLICT(key) DO UPDATE SET value=''")
            c.execute("INSERT INTO settings(key,value) VALUES('payment_qr_filename','') ON CONFLICT(key) DO UPDATE SET value=''")
    flash("Settings saved.", "success"); return redirect(url_for("admin_settings_page"))

@app.post("/admin/plan")
@admin_required
def save_plan():
    try:
        plan_id = int(request.form.get("id","0"))
        name = request.form.get("name","Plan").strip()[:60]
        price = max(0, float(request.form.get("price","0")))
        credits = max(0, int(request.form.get("credits","0")))
        bot_limit = max(1, int(request.form.get("bot_limit","1")))
        days = max(1, int(request.form.get("days","30")))
        active = 1 if request.form.get("active") == "1" else 0
        with db() as c:
            if plan_id:
                c.execute("UPDATE plans SET name=?,price=?,credits=?,bot_limit=?,days=?,active=? WHERE id=?",
                          (name,price,credits,bot_limit,days,active,plan_id))
            else:
                c.execute("INSERT INTO plans(name,price,credits,bot_limit,days,active) VALUES(?,?,?,?,?,?)",
                          (name,price,credits,bot_limit,days,active))
        flash("Plan saved.", "success")
    except Exception:
        flash("Could not save plan. Check the values.", "danger")
    return redirect(url_for("admin_plans_page"))

@app.post("/admin/plan/<int:plan_id>/delete")
@admin_required
def delete_plan(plan_id):
    with db() as c: c.execute("UPDATE plans SET active=0 WHERE id=?", (plan_id,))
    flash("Plan disabled.", "success"); return redirect(url_for("admin_plans_page"))

@app.errorhandler(403)
def forbidden(e): return render_template("error.html", code=403, message="Admin access required."), 403
@app.errorhandler(404)
def not_found(e): return render_template("error.html", code=404, message="Page not found."), 404
@app.errorhandler(413)
def too_large(e): return render_template("error.html", code=413, message="Upload too large. Maximum upload size is 25 MB."), 413

def _restore_approved_bots():
    """Re-download files and relaunch bots whose persisted state says approved/running."""
    try:
        with db() as c:
            rows = c.execute("SELECT * FROM bots WHERE status IN ('approved','running') ORDER BY id").fetchall()
            # The old OS processes died with the Render instance. Mark them as
            # approved before launching fresh processes in this instance.
            c.execute("UPDATE bots SET status='approved' WHERE status='running'")
        for row in rows:
            threading.Thread(target=run_bot, args=(row,), name=f"restore-bot-{row['id']}", daemon=True).start()
    except Exception as exc:
        sys.stderr.write(f"[restore] could not restore bots: {type(exc).__name__}: {exc}\\n")

# Start the optional ping loop and persisted bot recovery.
_start_keep_alive()
if _storage_enabled():
    threading.Thread(target=_restore_approved_bots, name="restore-approved-bots", daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# ================= GITHUB OAUTH DEPLOYMENT MODULE =================
from urllib.parse import urlencode
import base64

def _github_fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256((app.secret_key + "|cyberhost-github-v1").encode()).digest())
    return Fernet(key)

def _github_configured():
    return bool(os.getenv("GITHUB_CLIENT_ID", "").strip() and os.getenv("GITHUB_CLIENT_SECRET", "").strip())

def _github_api(path, token):
    if not path.startswith("/") or ".." in path:
        raise ValueError("Invalid GitHub API path.")
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CyberHost-Repository-Deploy"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()

def _github_connection(uid):
    with db() as c:
        return c.execute("SELECT * FROM github_connections WHERE user_id=?", (uid,)).fetchone()

def _github_access_token(uid):
    row = _github_connection(uid)
    if not row: return None
    try: return _github_fernet().decrypt(row["access_token"].encode()).decode()
    except Exception: return None

def _github_callback_url():
    configured = os.getenv("GITHUB_CALLBACK_URL", "").strip()
    return configured or ((os.getenv("RENDER_EXTERNAL_URL") or request.url_root).rstrip("/") + "/github/callback")

@app.get("/github")
@login_required
def github_page():
    user=get_user(); connected=_github_connection(user["id"]); repositories=[]
    if connected:
        token=_github_access_token(user["id"])
        if token:
            try:
                for page in range(1,4):
                    rows=json.loads(_github_api(f"/user/repos?per_page=100&sort=updated&direction=desc&page={page}&affiliation=owner,collaborator,organization_member",token))
                    repositories.extend(rows)
                    if len(rows)<100: break
            except Exception as exc: flash("GitHub repository list error: "+str(exc)[:180],"danger")
    return render_template("github.html",connected=connected,repositories=repositories,github_configured=_github_configured())

@app.get("/github/connect")
@login_required
def github_connect():
    if not _github_configured():
        flash("Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in Render first.","warning")
        return redirect(url_for("github_page"))
    state=secrets.token_urlsafe(32); session["github_oauth_state"]=state
    params=urlencode({"client_id":os.getenv("GITHUB_CLIENT_ID","").strip(),
        "redirect_uri":_github_callback_url(),"scope":"read:user repo","state":state})
    return redirect("https://github.com/login/oauth/authorize?"+params)

@app.get("/github/callback")
@login_required
def github_callback():
    expected=session.pop("github_oauth_state",None); supplied=request.args.get("state","")
    if not expected or not secrets.compare_digest(expected,supplied):
        flash("GitHub OAuth state check failed. Try connecting again.","danger"); return redirect(url_for("github_page"))
    if request.args.get("error"):
        flash("GitHub authorization was cancelled or denied.","warning"); return redirect(url_for("github_page"))
    code=request.args.get("code","")
    if not code or not _github_configured():
        flash("GitHub did not return a valid authorization code.","danger"); return redirect(url_for("github_page"))
    payload=json.dumps({"client_id":os.getenv("GITHUB_CLIENT_ID","").strip(),
        "client_secret":os.getenv("GITHUB_CLIENT_SECRET","").strip(),"code":code,
        "redirect_uri":_github_callback_url()}).encode()
    req=urllib.request.Request("https://github.com/login/oauth/access_token",data=payload,
        headers={"Accept":"application/json","Content-Type":"application/json","User-Agent":"CyberHost"})
    try:
        with urllib.request.urlopen(req,timeout=30) as response: oauth=json.loads(response.read().decode())
        token=oauth.get("access_token")
        if not token: raise ValueError(oauth.get("error_description") or oauth.get("error") or "No access token returned.")
        profile=json.loads(_github_api("/user",token))
        encrypted=_github_fernet().encrypt(token.encode()).decode()
        with db() as c:
            c.execute("""INSERT INTO github_connections(user_id,github_login,github_id,access_token,connected_at)
                VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET
                github_login=excluded.github_login,github_id=excluded.github_id,
                access_token=excluded.access_token,connected_at=CURRENT_TIMESTAMP""",
                (get_user()["id"],profile.get("login","")[:100],str(profile.get("id","")),encrypted))
        flash("GitHub connected. Select a repository to import.","success")
    except Exception as exc: flash("GitHub connection failed: "+str(exc)[:220],"danger")
    return redirect(url_for("github_page"))

@app.post("/github/disconnect")
@login_required
def github_disconnect():
    with db() as c: c.execute("DELETE FROM github_connections WHERE user_id=?",(get_user()["id"],))
    flash("GitHub disconnected; saved OAuth token deleted.","success")
    return redirect(url_for("github_page"))

@app.post("/github/deploy")
@login_required
def github_deploy():
    user=get_user(); token=_github_access_token(user["id"])
    if not token: flash("Connect GitHub first.","warning"); return redirect(url_for("github_page"))
    full_name=request.form.get("repository","").strip(); branch=request.form.get("branch","").strip()
    project_name=request.form.get("name","").strip()
    if full_name.count("/")!=1 or len(full_name)>200:
        flash("Choose a valid repository.","danger"); return redirect(url_for("github_page"))
    owner,repo_name=full_name.split("/",1)
    if not all(part and all(ch.isalnum() or ch in "-_." for ch in part) for part in (owner,repo_name)):
        flash("Invalid repository name.","danger"); return redirect(url_for("github_page"))
    if bot_count(user["id"]) >= (10**6 if user["is_admin"] else 2):
        flash("Your current bot limit has been reached.","warning"); return redirect(url_for("github_page"))
    try:
        repository=json.loads(_github_api(f"/repos/{owner}/{repo_name}",token))
        branch=branch or repository.get("default_branch","main")
        if len(branch)>250 or branch.startswith("-") or ".." in branch or any(x in branch for x in ("\\","\x00")):
            raise ValueError("Invalid branch name.")
        archive_req=urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{quote(branch,safe='')}",
            headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28","User-Agent":"CyberHost"})
        with urllib.request.urlopen(archive_req,timeout=60) as response:
            archive_bytes=response.read(50*1024*1024+1)
        if len(archive_bytes)>50*1024*1024: raise ValueError("Repository archive exceeds 50 MB.")
        import io
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members=archive.infolist()
            if not members or sum(x.file_size for x in members)>100*1024*1024:
                raise ValueError("Archive is empty or expands beyond 100 MB.")
            for item in members:
                name=item.filename.replace("\\","/")
                if name.startswith("/") or any(p==".." for p in name.split("/")):
                    raise ValueError("Unsafe path found in repository archive.")
                if (item.external_attr>>16)&0o170000==0o120000:
                    raise ValueError("Symbolic links are not allowed.")
        safe=secure_filename(project_name or repository.get("name") or repo_name)[:60] or "github-project"
        stored=f"{user['id']}_{secrets.token_hex(6)}_{safe}.zip"; local=UPLOADS/stored
        local.write_bytes(archive_bytes)
        if _storage_enabled() and not _storage_upload_file(local,"uploads/"+stored):
            local.unlink(missing_ok=True); raise RuntimeError("Supabase Storage upload failed; check private bot-files bucket.")
        status="approved" if user["is_admin"] else "pending"
        with db() as c:
            c.execute("INSERT INTO bots(user_id,name,filename,status) VALUES(?,?,?,?)",
                (user["id"],(project_name or repository.get("name") or repo_name)[:80],stored,status))
            bot=c.execute("SELECT * FROM bots WHERE filename=?",(stored,)).fetchone()
        if user["is_admin"]:
            threading.Thread(target=run_bot,args=(bot,),name=f"github-bot-{bot['id']}",daemon=True).start()
            flash(f"Imported {full_name} ({branch}); launch requested.","success")
        else: flash(f"Imported {full_name} ({branch}); waiting for admin approval.","success")
    except Exception as exc: flash("GitHub import failed: "+str(exc)[:250],"danger")
    return redirect(url_for("my_bots"))

with db() as _github_db:
    _github_db.execute("""CREATE TABLE IF NOT EXISTS github_connections(
        user_id INTEGER PRIMARY KEY, github_login TEXT NOT NULL, github_id TEXT NOT NULL,
        access_token TEXT NOT NULL, connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id))""")
# ================= END GITHUB OAUTH DEPLOYMENT MODULE =================
