# CYBER HOST — Premium Bot Hosting Dashboard

A premium-styled Flask starter for managing user-uploaded Python, JavaScript and ZIP bot projects. Includes user accounts, admin review, bot controls, plan management, manual UPI/UTR payment review, credits, and settings.

## Deploy on Render
1. Upload this project to a new GitHub repository, or use **New > Web Service** to connect the repository.
2. Render detects `render.yaml`; this configuration does not require a paid persistent disk.
3. Set `ADMIN_PASSWORD` to a strong password in Render environment variables before launch. `ADMIN_USERNAME` defaults to `admin`.
4. Deploy. Open `/login` and sign in with the admin credentials.
5. Change the UPI ID, QR URL, support text and site name in Admin.

## Important production notes
- This diskless setup stores the SQLite database, uploads, runtime files, and current log files under `/tmp/cyberhost-data`. It avoids the `/var/data` permission error, but `/tmp` is temporary storage: accounts, uploads, logs, and settings may be lost when the service restarts, redeploys, or the instance is replaced. Running bot processes also stop when the service instance is replaced. Reliable persistence requires an external database and durable file storage; reliable long-running bot hosting should use a separate worker service.
- Approved bot files now launch as real child processes, stdout/stderr are captured in the dashboard's Live logs page, and process exits update the bot status. ZIP projects can include a `requirements.txt`; the app installs those Python dependencies into that bot's runtime before launch. Upload a ZIP containing a clear entry file such as `bot.py` and `requirements.txt` when your bot needs third-party packages. JavaScript bots require Node.js to be installed in the service runtime; a native Render Python runtime may not include it.
- This is still a starter, not a hardened multi-tenant execution service. Uploaded programs are arbitrary code and can access the app container's files and network. **Do not allow unknown users' uploads on a public production service without isolated containers/sandboxing, strict CPU/RAM/time/network limits, per-user quotas, malware review, and security testing.**
- Bot processes started by this app are local child processes. They are not supervised across every deploy/instance change; for reliable 24/7 operation, use a dedicated worker/container service and a process supervisor.
- Google OAuth, Telegram admin notifications, and a live payment gateway are not wired up. This starter uses username/password accounts and manual UTR approval. Never collect or store users' Google passwords.
- Payment approval adds the plan's credits. Plan bot limits/duration are displayed/configurable but must be enforced with a proper entitlement system before real paid use.
- Set a strong `SECRET_KEY` and `ADMIN_PASSWORD`. Do not use the sample admin password in production.

## Local run
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:10000`. Initial admin defaults to `admin` / `ChangeMe123!` only when no admin exists. Override using environment variables.
