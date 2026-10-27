import os, sqlite3, secrets, subprocess, sys, time, threading, zipfile, shutil
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, render_template, send_from_directory, abort
from werkzeug.utils import secure_filename
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
for p in (UPLOADS, RUNTIMES):
    p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
DB = DATA / "hosting.db"
ALLOWED = {".py", ".js", ".zip"}
processes = {}
process_lock = threading.Lock()

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

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
                    "upi_id":"your-upi@bank", "payment_qr_url":"", "maintenance":"0"}
        for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
init_db()

def setting(key):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""

@app.context_processor
def inject_globals():
    return {"site_name": setting("site_name"), "support_text": setting("support_text"),
            "current_user": get_user(), "maintenance": setting("maintenance") == "1"}

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
            session.clear(); session["uid"] = user["id"]
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
        payments = c.execute("SELECT payments.*, plans.name plan_name FROM payments JOIN plans ON plans.id=payments.plan_id WHERE user_id=? ORDER BY payments.id DESC",(u["id"],)).fetchall()
    return render_template("dashboard.html", bots=bots, plans=plans, payments=payments, user=u, bot_limit=10**6 if u["is_admin"] else 2)

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
    f.save(UPLOADS / stored)
    with db() as c:
        c.execute("INSERT INTO bots(user_id,name,filename,status) VALUES(?,?,?,'pending')",
                  (u["id"], name[:80], stored))
    flash("Upload received. It is pending admin review before it can run.", "success")
    return redirect(url_for("dashboard"))

def stop_process(bot_id):
    with process_lock:
        proc = processes.pop(bot_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=4)
        except subprocess.TimeoutExpired: proc.kill()

def run_bot(bot):
    source = UPLOADS / bot["filename"]
    runtime = RUNTIMES / str(bot["id"])
    runtime.mkdir(parents=True, exist_ok=True)
    ext = source.suffix.lower()
    try:
        if ext == ".zip":
            # Reject path traversal and symlink entries before extracting.
            with zipfile.ZipFile(source) as z:
                for info in z.infolist():
                    target = (runtime / info.filename).resolve()
                    if not str(target).startswith(str(runtime.resolve()) + os.sep):
                        raise ValueError("Unsafe path in ZIP archive.")
                    if info.external_attr >> 16 & 0o170000 == 0o120000:
                        raise ValueError("Symlinks are not allowed in ZIP uploads.")
                z.extractall(runtime)
            candidates = list(runtime.rglob("*.py")) + list(runtime.rglob("*.js"))
            if not candidates: raise ValueError("ZIP must contain a Python or JavaScript entry file.")
            entry = candidates[0]
        else:
            entry = runtime / source.name
            shutil.copy2(source, entry)
        if ext == ".js" or entry.suffix.lower() == ".js":
            cmd = ["node", str(entry)]
        else:
            cmd = [sys.executable, str(entry)]
        # No shell=True. Production deployments should isolate uploaded code in containers.
        proc = subprocess.Popen(cmd, cwd=str(runtime), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env={"PATH": os.getenv("PATH",""), "HOME": str(runtime), "PYTHONUNBUFFERED":"1"})
        time.sleep(0.6)
        if proc.poll() is not None:
            raise RuntimeError("Process exited immediately. Check runtime dependencies and entry file.")
        with process_lock: processes[bot["id"]] = proc
        with db() as c: c.execute("UPDATE bots SET status='running',last_error='' WHERE id=?", (bot["id"],))
    except Exception as e:
        with db() as c: c.execute("UPDATE bots SET status='error',last_error=? WHERE id=?", (str(e)[:500],bot["id"]))

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
        flash("Bot and its stored files were deleted.", "success")
    elif action == "stop":
        stop_process(bot_id)
        with db() as c: c.execute("UPDATE bots SET status='stopped' WHERE id=?", (bot_id,))
        flash("Bot stopped.", "success")
    elif action == "restart":
        stop_process(bot_id)
        if bot["status"] != "approved" and not u["is_admin"]:
            flash("This bot has not been approved by an admin yet.", "warning")
        else:
            with db() as c: c.execute("UPDATE bots SET status='approved' WHERE id=?", (bot_id,))
            with db() as c: fresh = c.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
            threading.Thread(target=run_bot, args=(fresh,), daemon=True).start()
            flash("Restart requested.", "success")
    else: abort(400)
    return redirect(url_for("admin") if u["is_admin"] else url_for("dashboard"))

@app.get("/admin")
@admin_required
def admin():
    with db() as c:
        users = c.execute("SELECT id,username,is_admin,credits,created_at FROM users ORDER BY id DESC").fetchall()
        bots = c.execute("SELECT bots.*,users.username FROM bots JOIN users ON users.id=bots.user_id WHERE status!='deleted' ORDER BY bots.id DESC").fetchall()
        payments = c.execute("SELECT payments.*,users.username,plans.name plan_name FROM payments JOIN users ON users.id=payments.user_id JOIN plans ON plans.id=payments.plan_id ORDER BY payments.id DESC").fetchall()
        plans = c.execute("SELECT * FROM plans ORDER BY price").fetchall()
        settings = {r["key"]:r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
    return render_template("admin.html", users=users, bots=bots, payments=payments, plans=plans, settings=settings)

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
    return redirect(url_for("admin"))

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
    flash("Payment updated.", "success"); return redirect(url_for("admin"))

@app.post("/admin/user/<int:user_id>/credits")
@admin_required
def admin_credits(user_id):
    try: amount = int(request.form.get("amount","0"))
    except ValueError: amount = 0
    with db() as c: c.execute("UPDATE users SET credits=MAX(0,credits+?) WHERE id=?", (amount,user_id))
    flash("User credits updated.", "success"); return redirect(url_for("admin"))

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
    return redirect(url_for("dashboard"))

@app.post("/admin/settings")
@admin_required
def save_settings():
    allowed = ["site_name","support_text","upi_id","payment_qr_url","maintenance"]
    with db() as c:
        for k in allowed:
            val = request.form.get(k, "").strip()
            if k == "maintenance": val = "1" if val == "1" else "0"
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,val[:2000]))
    flash("Settings saved.", "success"); return redirect(url_for("admin"))

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
    return redirect(url_for("admin"))

@app.post("/admin/plan/<int:plan_id>/delete")
@admin_required
def delete_plan(plan_id):
    with db() as c: c.execute("UPDATE plans SET active=0 WHERE id=?", (plan_id,))
    flash("Plan disabled.", "success"); return redirect(url_for("admin"))

@app.errorhandler(403)
def forbidden(e): return render_template("error.html", code=403, message="Admin access required."), 403
@app.errorhandler(404)
def not_found(e): return render_template("error.html", code=404, message="Page not found."), 404
@app.errorhandler(413)
def too_large(e): return render_template("error.html", code=413, message="Upload too large. Maximum upload size is 25 MB."), 413

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
