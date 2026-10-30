<div align="center">

# ☠️ CYBER HOST // BOT DEPLOYMENT SYSTEM

### `FREE PYTHON • JAVASCRIPT • ZIP TELEGRAM BOT HOSTING`

`[ SYSTEM ONLINE ]` · `[ ANDROID READY ]` · `[ OPEN SOURCE PANEL ]`

**Upload. Configure. Launch. Monitor.**

A dark, cyberpunk-inspired Telegram bot hosting dashboard built with Flask. Manage Python, JavaScript and ZIP bot projects from a clean mobile-first control panel — including from Android.

[Features](#-core-features) · [Deploy](#-quick-deploy) · [Android UI](#-mobile--android-control-panel) · [Storage](#-persistent-storage) · [API](#-scoped-api-access) · [Security](#-security--hosting-limits)

</div>

---

## `01 // SYSTEM OVERVIEW`

CYBER HOST is a self-hostable bot management panel designed to make bot deployment simple.

- 🐍 **Python bot hosting** — upload `.py` files or ZIP projects.
- 🟨 **JavaScript bot hosting** — upload `.js` files or ZIP projects with `package.json`.
- 📦 **ZIP project hosting** — deploy project folders containing entry files and dependency manifests.
- 📱 **Android-friendly dashboard** — separate pages, responsive cards and fixed bottom navigation.
- 🖥️ **Browser terminal** — Termux-inspired, restricted per-project command interface.
- 📡 **Live logs** — inspect bot output and startup errors.
- 🛡️ **Admin approval** — review user uploads before launch.
- 💳 **Credits and manual UPI payments** — configurable plans and admin verification.
- 🔑 **Scoped API tokens** — issue and revoke tokens with selected permissions.

> **Hosting note:** The panel code is free to self-host. Actual runtime capacity, uptime, storage and free-tier limits depend on the hosting provider. This project does not promise unlimited or guaranteed 24/7 hosting.

---

## `02 // CORE FEATURES`

| Module | Capabilities |
|---|---|
| Python runtime | Run `.py` projects; install dependencies from `requirements.txt` |
| JavaScript runtime | Run `.js` projects; install dependencies from `package.json` |
| ZIP deployment | Extract supported projects and detect entry files |
| Bot controls | Start, stop, restart, approve and delete |
| Live logs | View process output and recent startup diagnostics |
| Web terminal | Restricted commands for project files and dependencies |
| User accounts | Registration, login and persistent session cookie |
| Admin console | Manage bots, users, payments, plans, settings and API tokens |
| Credit store | Display packages and submit UPI/UTR payment references |
| Storage | Optional Supabase Storage for uploaded files and database snapshots |

### Supported upload formats

- `.py` — single Python bot file.
- `.js` — single JavaScript bot file.
- `.zip` — project archive. Python projects can include `requirements.txt`; JavaScript projects can include `package.json`.

Manual file uploads (`.py`, `.js`, `.zip`) also include an **Environment Variables** editor. Add keys such as `BOT_TOKEN`, `API_ID`, `API_HASH`, or `MONGO_URI` before uploading. Up to 50 variables are accepted, each value up to 4,000 characters. Values are encrypted at rest and loaded into the bot process on every start. Keep the same stable `SECRET_KEY` so saved values remain decryptable.

For best results, keep one clear entry file in the project. For ZIP projects, include the correct dependency manifest and entry script.

---

## `03 // MOBILE & ANDROID CONTROL PANEL`

The interface is designed to work on phone screens without needing desktop mode.

### User navigation

- **Dashboard** — account overview and quick links.
- **My Bots** — view and manage uploaded projects.
- **Create Bot** — upload a new Python, JS or ZIP project.
- **Credit Store** — view plans and submit payment references.
- **My Profile** — account information and sign-out.

### Admin navigation

- **Admin Dashboard** — platform overview.
- **Bot Management** — review and control hosted projects.
- **Payment Management** — approve or reject payment requests.
- **User Management** — inspect users and adjust credits.
- **Website Settings** — configure site name, UPI, QR and support text.
- **Plans & Pricing** — edit available credit packages.
- **API Access** — create, inspect and revoke API tokens.

The bottom navigation is fixed on mobile, with responsive layouts for cards, forms and action buttons.

---

## `04 // QUICK DEPLOY`

### Deploy on Render

1. Fork or push this repository to your GitHub account.
2. Open Render and create a **New Web Service** connected to this repository.
3. Use the included **Dockerfile** / Docker runtime. The image installs Python and Node.js.
4. Add the environment variables below.
5. Deploy and open your service URL.
6. Visit `/login` and sign in with your configured admin credentials.

### Required environment variables

| Variable | Value |
|---|---|
| `SECRET_KEY` | Strong random secret; keep it private and stable |
| `ADMIN_USERNAME` | Admin login name; defaults to `admin` |
| `ADMIN_PASSWORD` | Set a strong admin password before deployment |

### Optional environment variables

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Local app data directory; Render config uses `/tmp/cyberhost-data` |
| `KEEP_ALIVE_ENABLED` | Enables best-effort health ping when set to `true` |
| `KEEP_ALIVE_INTERVAL_MINUTES` | Ping interval; supported range is 5–14 minutes |
| `KEEP_ALIVE_URL` | Optional public base URL for the health ping |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Private server-side Supabase service key |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket name; use `bot-files` |\n| `GITHUB_CLIENT_ID` | GitHub OAuth App Client ID |\n| `GITHUB_CLIENT_SECRET` | GitHub OAuth App secret |\n| `GITHUB_CALLBACK_URL` | `https://YOUR-SERVICE.onrender.com/github/callback` |

**Important:** If an existing Render service was created with a different runtime and cannot switch to Docker, create a new Web Service using this repository's Docker configuration.

---

## `05 // GITHUB CONNECT & DIRECT IMPORT`

Connect a GitHub OAuth App, browse repositories accessible to the signed-in GitHub account, and import a selected repository directly into CYBER HOST.

### Configure GitHub OAuth

1. Open GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Set Homepage URL to your deployed CYBER HOST URL.
3. Set Authorization callback URL to `https://YOUR-SERVICE.onrender.com/github/callback`.
4. Copy the OAuth App **Client ID** and generate a **Client Secret**.
5. In Render → Environment, add:
   - `GITHUB_CLIENT_ID` — OAuth App Client ID.
   - `GITHUB_CLIENT_SECRET` — private OAuth App secret.
   - `GITHUB_CALLBACK_URL` — exact callback URL configured in GitHub.
6. Save and redeploy. Sign in to CYBER HOST, open **GitHub**, and select **Connect GitHub**.
7. Approve the GitHub authorization, select a repository, then press **Import & Deploy**.

The app requests `read:user` and `repo` scopes so it can list private and public repositories the account can access. The current importer only calls read/download endpoints; it does not push commits or modify repository contents. GitHub's OAuth `repo` scope is broad, so authorize only an account you control.

### Import behavior and limits

- The selected default branch is downloaded as a ZIP snapshot (50 MB download / 100 MB expanded limit).
- Archive paths and symbolic links are checked before the project is saved.
- Imported projects use the existing bot launch flow. Normal users' imports remain pending until admin approval; admin imports launch automatically.
- This is a one-time import, not automatic redeployment after future Git pushes. Re-import the repository to update the hosted copy.
- The access token is encrypted at rest using a key derived from the app's stable `SECRET_KEY`. Keep `SECRET_KEY` unchanged between deploys; otherwise saved GitHub connections cannot be decrypted. Disconnecting removes the saved token.

### Per-bot environment variables

When importing a GitHub repository, expand **Add environment variables** and enter the exact names your code reads, for example `BOT_TOKEN`, `TELEGRAM_BOT_TOKEN`, `API_ID`, `API_HASH`, or `MONGO_URI`. Add as many as needed (maximum 50; each value up to 4,000 characters). The importer encrypts these values at rest in the database and injects them only into that bot's process. They are not printed in logs or displayed again after submission. Restart/redeploy the bot after changing environment values.

GitHub connection remains saved to the CYBER HOST account until the user explicitly disconnects it. It survives browser logout and server restarts only when the database snapshot persistence is configured and the same stable `SECRET_KEY` is retained. GitHub repository listing is paginated (up to 10,000 repositories per account view).


Only import source code you trust: deployed Python/JavaScript projects execute inside the hosting container.

---

## `06 // BOT DEPLOYMENT WORKFLOW`

1. Create an account and sign in.
2. Open **Create Bot**.
3. Enter a project name and upload a `.py`, `.js` or `.zip` file.
4. Admin uploads are marked approved automatically. Normal user uploads remain pending until an admin reviews them.
5. Once approved, use the bot controls to start the project.
6. Open **Terminal** for supported project commands or **Live Logs** to inspect process output.

### Dependency setup

- Python ZIP projects: dependencies are installed from `requirements.txt`.
- Single Python files: the app attempts limited detection of common libraries.
- JavaScript ZIP projects: `npm install` is run when `package.json` exists; the app uses its start script or a detected JS entry file.

Dependency installation can take time and can fail if a package is incompatible, unavailable, or exceeds the host's resources. Check the final lines in Live Logs for the actual error.

---

## `07 // WEB TERMINAL & LIVE LOGS`

The browser terminal has a dark, Termux-inspired interface and is intended for basic project tasks.

Supported commands include:

```text
help
pwd
ls
cat <file>
python --version
python <file.py>
python -m py_compile <file.py>
pip list
pip install <package>
pip install -r requirements.txt
node --version
node <file.js>
node --check <file.js>
npm --version
npm list
```

- Python packages installed from the terminal go into the selected bot's local `vendor` folder.
- Script execution and dependency installation have time limits.
- Terminal history is stored in the browser's local storage (up to 40 entries per bot).
- Live Logs refreshes the selected bot's process output.

**Terminal limitation:** This is not a full Linux shell or unrestricted Termux. Arbitrary shell commands, shell operators, system administration commands and paths outside the project are not supported. The terminal does not attach to the running bot's stdin. Use the website's bot controls to start or restart the bot, and Live Logs to inspect its output.

---

## `08 // PERSISTENT STORAGE`

Render's local filesystem is ephemeral. For persistence across instance replacement, configure Supabase Storage.

### Supabase setup

1. Open your Supabase project.
2. Create a **private Storage bucket** named `bot-files`.
3. In Render → Environment, add:
   - `SUPABASE_URL` — Supabase project URL.
   - `SUPABASE_SERVICE_KEY` — server-side service-role/secret key.
   - `SUPABASE_STORAGE_BUCKET` — `bot-files`.
4. Save and redeploy.
5. Check Render logs for `[supabase-storage]` errors.

The app stores uploaded files under `uploads/` and a SQLite database snapshot at `_system/hosting.db`. On restart, it attempts to restore the snapshot, rehydrate uploads and relaunch bots with saved approved/running status.

### Storage architecture limits

- The database is stored as a SQLite snapshot object in Supabase Storage; this is **not** a Supabase Postgres database migration.
- Use one app instance only. Do not scale this snapshot-based design across multiple web instances.
- Runtime folders, dependency caches and logs are local and may be rebuilt or lost after restart.
- Without Supabase, local uploads and database files may disappear when the host replaces its ephemeral filesystem.
- Snapshot upload/download failures must be investigated in Render logs; persistence is not guaranteed until verified.

---

## `09 // SCOPED API ACCESS`

Admins can create named bearer tokens and select permissions. Tokens can be set to expire and revoked. The full token is displayed only once; the database stores its SHA-256 hash.

### Authentication

Send the token from a trusted backend:

```http
Authorization: Bearer ch_live_YOUR_TOKEN
```

### API permissions

| Scope | Endpoint access |
|---|---|
| No scope | `GET /api/v1` — API discovery |
| Any valid token | `GET /api/v1/me` |
| `site:read` | `GET /api/v1/settings` |
| `users:read` | `GET /api/v1/users` |
| `bots:read` | `GET /api/v1/bots`, `GET /api/v1/bots/<id>` |
| `bots:control` | Approve, reject, stop or restart bot actions |
| `bots:delete` | `DELETE /api/v1/bots/<id>` |
| `payments:read` | `GET /api/v1/payments` |

Example:

```bash
curl -H "Authorization: Bearer ch_live_YOUR_TOKEN" \
  https://YOUR-HOST/api/v1/bots
```

Grant only the scopes an integration needs. Never place API tokens or the Supabase service key in frontend JavaScript, public repositories or screenshots.

---

## `10 // PAYMENTS & CREDITS`

The Store page displays active plans. Users submit a UPI transaction reference/UTR; the request remains pending until an admin checks the payment and approves or rejects it.

Admins can configure:
- UPI ID.
- Payment QR image URL or uploaded QR image.
- Support text and site name.
- Credit plans and package values.
- User credit adjustments.

**Payment verification is manual.** This project does not automatically verify bank transfers or provide a built-in live payment gateway. Do not mark a payment approved until it has been checked independently.

---

## `11 // SECURITY & HOSTING LIMITS`

> **Read before allowing public uploads.**

This is a starter hosting panel, not a hardened multi-tenant code execution platform. Uploaded Python and JavaScript code runs as child processes inside the app's host environment. Uploaded code may access files and network resources available to that container.

For a public service, add isolated worker containers, strict CPU/RAM/process/time/network limits, per-user quotas, malware review, audit logs and security testing before accepting untrusted uploads.

Other important limitations:

- Free hosting providers can restart or suspend services.
- Self-pinging is best-effort and cannot guarantee 24/7 uptime.
- A bot that crashes because of invalid credentials, code errors or incompatible dependencies will not be automatically repaired by restarting it.
- Manual UPI review is not automated payment verification.
- This starter does not include Google OAuth, Telegram admin notifications or a live payment gateway.
- Keep `SECRET_KEY`, `ADMIN_PASSWORD` and `SUPABASE_SERVICE_KEY` private.

---

## `12 // RUN LOCALLY`

Requirements: Python 3.12+ and Node.js/npm if you want to run JavaScript bot projects.

```bash
git clone https://github.com/Anandsinghsarkar/hoster.git
cd hoster

python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:10000`.

Set a strong `ADMIN_PASSWORD` and `SECRET_KEY` in your environment before using the panel. Never use a sample/default password on a public deployment.

---

## `13 // PROJECT STATUS`

| Component | Status |
|---|---|
| Flask web dashboard | Included |
| Python / JavaScript / ZIP uploads | Included |
| Admin review and bot controls | Included |
| Mobile bottom navigation | Included |
| Web terminal and Live Logs | Included |
| Credit plans and manual UPI review | Included |
| Supabase Storage persistence | Optional configuration |
| Scoped API tokens | Included |\n| GitHub OAuth repository import | Requires OAuth App configuration |
| Guaranteed 24/7 free runtime | Not guaranteed |
| Secure isolation for untrusted public code | Requires additional infrastructure |

---

<div align="center">

### `[ END OF TRANSMISSION ]`

**CYBER HOST // BUILD • DEPLOY • MONITOR**

`FREE PANEL CODE` · `PYTHON` · `JAVASCRIPT` · `ZIP` · `ANDROID READY`

</div>
