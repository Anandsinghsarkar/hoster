# CYBER HOST — Premium Bot Hosting Dashboard

A premium-styled Flask starter for managing user-uploaded Python, JavaScript and ZIP bot projects. Includes user accounts, admin review, bot controls, plan management, manual UPI/UTR payment review, credits, and settings.

## Deploy on Render
1. Upload this project to a new GitHub repository, or use **New > Web Service** to connect the repository.
2. Render uses the included `Dockerfile`, which provides Python and Node.js/npm. This configuration does not require a paid persistent disk. If you already have an existing Render service configured with the Python runtime and Render does not allow changing its runtime, create a new Web Service from this repo and select the Docker runtime.
3. Set `ADMIN_PASSWORD` to a strong password in Render environment variables before launch. `ADMIN_USERNAME` defaults to `admin`.
4. Deploy. The app uses a 365-day persistent login cookie and configures a best-effort health ping every 10 minutes using Render's RENDER_EXTERNAL_URL. Open `/login` and sign in with the admin credentials.
5. Change the UPI ID, QR URL, support text and site name in Admin.

## Login persistence and health ping
- Successful login creates a permanent Flask session cookie that lasts up to 365 days and refreshes as the user visits the site. It ends when the user signs out, clears browser cookies, or the cookie expires. Keep Render's generated SECRET_KEY stable between deploys; changing it invalidates existing sessions.
- The /health and /ping endpoints return a lightweight ok response for health checks. When KEEP_ALIVE_ENABLED=true and RENDER_EXTERNAL_URL is available, the app makes a best-effort request to its own health endpoint every 10 minutes. You can change the interval with KEEP_ALIVE_INTERVAL_MINUTES (supported range 5–14) or set KEEP_ALIVE_URL to the public base URL.
- This cannot guarantee 24/7 uptime. Render can restart services or suspend free instances independently of app code, and self-pings may not prevent sleep in every configuration. Render's official free-instance documentation describes the 15-minute idle spin-down and ephemeral filesystem limitations: https://render.com/docs/free. Do not rely on this as a production uptime guarantee.

## Important production notes
- This diskless setup stores the SQLite database, uploads, runtime files, and current log files under `/tmp/cyberhost-data`. It avoids the `/var/data` permission error, but `/tmp` is temporary storage: accounts, uploads, logs, and settings may be lost when the service restarts, redeploys, or the instance is replaced. Running bot processes also stop when the service instance is replaced. Reliable persistence requires an external database and durable file storage; reliable long-running bot hosting should use a separate worker service.
- Approved bot files launch as real child processes, stdout/stderr are captured in the Live logs page, and process exits update the bot status. For ZIP Python projects, the app automatically installs dependencies from `requirements.txt`; for a single `.py` upload it tries to detect and install a limited set of common libraries. For uncommon/custom Python packages, upload a ZIP containing `bot.py` and `requirements.txt`. For JavaScript ZIP projects, it runs `npm install` when `package.json` exists, then uses the `start` script or the detected JS entry file. The logs page has Copy logs and Copy error buttons. Setup commands can take a few minutes and their output is included in logs.
- This is still a starter, not a hardened multi-tenant execution service. Uploaded programs are arbitrary code and can access the app container's files and network. **Do not allow unknown users' uploads on a public production service without isolated containers/sandboxing, strict CPU/RAM/time/network limits, per-user quotas, malware review, and security testing.**
- Bot processes started by this app are local child processes. They are not supervised across every deploy/instance change; for reliable 24/7 operation, use a dedicated worker/container service and a process supervisor.
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
