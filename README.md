# CYBER HOST — Premium Bot Hosting Dashboard

A premium-styled Flask starter for managing user-uploaded Python, JavaScript and ZIP bot projects. Includes user accounts, admin review, bot controls, plan management, manual UPI/UTR payment review, credits, and settings.

## Deploy on Render
1. Upload this project to a new GitHub repository, or use **New > Web Service** to connect the repository.
2. Render uses the included `Dockerfile`, which provides Python and Node.js/npm. This configuration does not require a paid persistent disk. If you already have an existing Render service configured with the Python runtime and Render does not allow changing its runtime, create a new Web Service from this repo and select the Docker runtime.
3. Set `ADMIN_PASSWORD` to a strong password in Render environment variables before launch. `ADMIN_USERNAME` defaults to `admin`.
4. Deploy. The app uses a 365-day persistent login cookie and configures a best-effort health ping every 10 minutes using Render's RENDER_EXTERNAL_URL. Open `/login` and sign in with the admin credentials.
5. Change the UPI ID, QR URL, support text and site name in Admin.

## Android/mobile navigation and payment QR
- On phones, the signed-in site has a fixed bottom navigation bar: **Dashboard**, **My Bots**, **Create Bot**, and **Store**. Admins get **Dashboard**, **Bots**, **Payments**, and **Settings** buttons.
- In Admin → Platform settings, enter a public HTTPS QR image URL **or** upload a PNG/JPG/JPEG/WEBP image up to 5 MB. The QR and UPI ID are displayed in the user's Store section. Saving other settings or refreshing the page does not clear the saved QR; use the explicit remove checkbox only when you want to delete it.
- For restart-safe uploaded QR storage, configure the private Supabase Storage bucket `bot-files` and the three Supabase environment variables described below. The QR image is saved in that bucket at `settings/payment-qr.<extension>`; its setting is stored in the app database snapshot. Without Supabase, an uploaded QR is saved locally and may disappear when Render replaces its ephemeral instance.
- Admin-uploaded bot files are marked approved and launch is requested automatically. Normal users' uploads remain **pending** until an admin uses **Inspect file** in the review queue to view/download the submitted source, then approves or rejects it.
- Admin dashboard shows bot counts, pending reviews, approved purchase totals, and per-user approved purchase amounts. The user's dashboard shows their own bots, payment requests, and approved purchase total.
- This is a manual UPI/UTR flow: submitting a UTR creates a pending request. An admin must verify the payment and approve it; this starter does not automatically verify bank transfers.

## Per-bot web terminal
- A **Terminal** button is available in the user's bot table and the admin review table. It only opens a bot the signed-in user owns, unless the viewer is an admin.
- The mobile-friendly terminal runs in the selected bot's runtime/project folder and supports `help`, `pwd`, `ls`, `cat <relative-file>`, `python --version`, `node --version`, `pip list`, `python -m py_compile <file.py>`, and `node --check <file.js>`.
- For safety, it does not provide an unrestricted Linux shell, arbitrary system commands, shell operators, package installation, or paths outside the selected bot project. Commands have short timeouts and output limits. The bot must have been started at least once so its runtime folder exists.
- This is a restricted convenience terminal, not a security sandbox. This starter runs uploaded bot code in the same host environment; do not expose it to untrusted public users without moving bot execution into isolated containers with CPU/memory/process limits.

## Login persistence and health ping
- Successful login creates a permanent Flask session cookie that lasts up to 365 days and refreshes as the user visits the site. It ends when the user signs out, clears browser cookies, or the cookie expires. Keep Render's generated SECRET_KEY stable between deploys; changing it invalidates existing sessions.
- The /health and /ping endpoints return a lightweight ok response for health checks. When KEEP_ALIVE_ENABLED=true and RENDER_EXTERNAL_URL is available, the app makes a best-effort request to its own health endpoint every 10 minutes. You can change the interval with KEEP_ALIVE_INTERVAL_MINUTES (supported range 5–14) or set KEEP_ALIVE_URL to the public base URL.
- This cannot guarantee 24/7 uptime. Render can restart services or suspend free instances independently of app code, and self-pings may not prevent sleep in every configuration. Render's official free-instance documentation describes the 15-minute idle spin-down and ephemeral filesystem limitations: https://render.com/docs/free. Do not rely on this as a production uptime guarantee.

## Important production notes
- When `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `SUPABASE_STORAGE_BUCKET=bot-files` are configured, the app stores uploaded project files in the private Supabase Storage bucket and uploads a snapshot of its SQLite database to `_system/hosting.db` after database writes. On a new Render instance it downloads that snapshot, rehydrates missing uploads, and starts bots whose saved status was `approved` or `running`. Logs and runtime dependency folders are still local and may reset; dependencies are rebuilt when bots relaunch. If Supabase is not configured, the app falls back to temporary local storage.
- **Important architecture limit:** this diskless implementation keeps the app's database as one SQLite snapshot object in Supabase Storage, not as normalized tables in Supabase Postgres. It is intended for one Render web instance only; do not scale to multiple instances or use as a high-concurrency production database. Snapshot upload errors are logged to Render. Long-running bot hosting should ideally run in isolated worker containers with a real managed database and process supervisor.
- Approved bot files launch as real child processes, stdout/stderr are captured in the Live logs page, and process exits update the bot status. For ZIP Python projects, the app automatically installs dependencies from `requirements.txt`; for a single `.py` upload it tries to detect and install a limited set of common libraries. For uncommon/custom Python packages, upload a ZIP containing `bot.py` and `requirements.txt`. For JavaScript ZIP projects, it runs `npm install` when `package.json` exists, then uses the `start` script or the detected JS entry file. The logs page has Copy logs and Copy error buttons. Setup commands can take a few minutes and their output is included in logs.
- This is still a starter, not a hardened multi-tenant execution service. Uploaded programs are arbitrary code and can access the app container's files and network. **Do not allow unknown users' uploads on a public production service without isolated containers/sandboxing, strict CPU/RAM/time/network limits, per-user quotas, malware review, and security testing.**
- Bot processes are local child processes. With Supabase Storage configured, the app attempts to relaunch bots saved as approved/running after a restart, but startup restoration is best-effort and does not guarantee 24/7 operation. For dependable hosting, use a dedicated worker/container service and a process supervisor.
- Google OAuth, Telegram admin notifications, and a live payment gateway are not wired up. This starter uses username/password accounts and manual UTR approval. Never collect or store users' Google passwords.
- Payment approval adds the plan's credits. Plan bot limits/duration are displayed/configurable but must be enforced with a proper entitlement system before real paid use.
- Set a strong `SECRET_KEY` and `ADMIN_PASSWORD`. Do not use the sample admin password in production.


## Scoped API tokens (GitHub-style permissions)
The Admin console now includes **API tokens & permissions**. Admins can generate a named bearer token, choose individual scopes, select a 30/90/180/365-day expiry, review last-used time, and revoke a token. The full token is shown only once; only its SHA-256 hash is stored in the database.

### Authentication
Send the token from a trusted server/backend, never from public browser JavaScript:
```http
Authorization: Bearer ch_live_YOUR_TOKEN
```
The API root `GET /api/v1` lists supported endpoints. Successful responses are JSON. Invalid/expired/revoked tokens return HTTP 401; missing permissions return HTTP 403. User and bot list endpoints are limited to the latest 500 records.

### Permissions and endpoints
| Scope | Endpoints | Access |
| --- | --- | --- |
| No scope | `GET /api/v1` | Public API discovery |
| Any valid token | `GET /api/v1/me` | Token name, ID and granted scopes |
| `site:read` | `GET /api/v1/settings` | Public site name, support text and maintenance flag |
| `users:read` | `GET /api/v1/users` | User IDs, usernames, admin flags, credits and creation dates |
| `bots:read` | `GET /api/v1/bots`, `GET /api/v1/bots/<id>` | Bot metadata, status and last error |
| `bots:control` | `POST /api/v1/bots/<id>/actions/approve`, `reject`, `stop`, or `restart` | Approve/reject or control bot process |
| `bots:delete` | `DELETE /api/v1/bots/<id>` | Delete bot record, upload and runtime folder |
| `payments:read` | `GET /api/v1/payments` | Payment status, package, username and UTR/reference |

Example request:
```bash
curl -H "Authorization: Bearer ch_live_YOUR_TOKEN" \
  https://YOUR-HOST/api/v1/bots
```

**Security:** issue only the minimum scopes required. Treat tokens like passwords, keep them in server-side environment variables, do not commit them to GitHub, and revoke immediately if exposed. The `bots:control` scope can launch uploaded code; only grant it to trusted integrations. This starter does not yet provide API token rate limiting, audit event history, pagination, or write access to users/payments/settings. Protect the admin account and use HTTPS.

## Local run
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:10000`. Initial admin defaults to `admin` / `ChangeMe123!` only when no admin exists. Override using environment variables.

## Supabase persistence setup
1. In Supabase, create a **private Storage bucket** named `bot-files` (do not make it public).
2. In Render → your service → Environment, add:
   - `SUPABASE_URL`: Project URL from Supabase → Project Settings → API.
   - `SUPABASE_SERVICE_KEY`: server-side service-role/secret key from the same API settings. Never expose it in HTML, JavaScript, screenshots, or GitHub.
   - `SUPABASE_STORAGE_BUCKET`: `bot-files`.
3. Save the variables and redeploy. The app uses the bucket for `uploads/<stored-filename>` and `_system/hosting.db`. A successful file upload is rejected if the configured Storage upload fails.
4. Confirm the private bucket contains both the uploaded bot objects and `_system/hosting.db`; inspect Render logs for any `[supabase-storage]` errors.

The service key has broad project privileges. Use it only as a Render secret. This approach persists the existing SQLite database as a Storage object so no SQL schema setup is required; it is not a Supabase Postgres migration and is not suitable for multiple app instances. If you already have data only in Render's ephemeral `/tmp`, that old data cannot be recovered after it has been lost.