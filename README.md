# CYBER HOST — Premium Bot Hosting Dashboard

A premium-styled Flask starter for managing user-uploaded Python, JavaScript and ZIP bot projects. Includes user accounts, admin review, bot controls, plan management, manual UPI/UTR payment review, credits, and settings.

## Deploy on Render
1. Upload this project to a new GitHub repository, or use **New > Web Service** to connect the repository.
2. Render detects `render.yaml`. Confirm the disk is mounted at `/var/data`.
3. Set `ADMIN_PASSWORD` to a strong password in Render environment variables before launch. `ADMIN_USERNAME` defaults to `admin`.
4. Deploy. Open `/login` and sign in with the admin credentials.
5. Change the UPI ID, QR URL, support text and site name in Admin.

## Important production notes
- Render's persistent disk is required for the SQLite database and uploaded files to survive deploys/restarts. A persistent disk may require a paid Render plan; check current Render pricing and plan limits.
- This is a starter, not a hardened multi-tenant execution service. Uploaded programs are arbitrary code and can access the app's runtime environment. **Do not expose public uploads or run untrusted uploads in production without isolated containers/sandboxing, strict CPU/RAM/time/network limits, per-user quotas, malware review, and security testing.**
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
