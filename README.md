<div align="center">

# CYBER HOST

### TELEGRAM BOT HOSTING & MANAGEMENT PLATFORM

**Deploy • Manage • Monitor • Control**

A modern, mobile-friendly hosting dashboard for managing Python, JavaScript and ZIP-based Telegram bot projects. Upload your bot, configure its environment, monitor its activity and manage its stored files from one place — including on Android.

**PYTHON** · **JAVASCRIPT** · **ZIP PROJECTS** · **LIVE LOGS** · **ADMIN CONTROL** · **PERSISTENT STORAGE**

</div>

---

## Welcome to CYBER HOST

CYBER HOST makes bot hosting easier through a single website. Users can create an account, deploy supported bot projects, check bot status and view logs. Administrators can review deployments, manage users and credits, handle payments, configure the website and inspect bot files.

The website uses a responsive interface, so its main features can be used from a mobile browser without desktop mode.

## 1. Getting Started

### Create an account
1. Open the CYBER HOST website.
2. Select **Register**.
3. Enter your username and password.
4. Sign in to open your dashboard.

### User dashboard

| Section | What you can do |
|---|---|
| **My Bots** | View deployed bots, statuses and available actions. |
| **Create Bot** | Deploy by pasting code or uploading a project. |
| **Credit Store** | View plans and submit a payment reference. |
| **Payment History** | Check submitted payment requests. |
| **My Profile** | View account details and sign out. |

## 2. Deploy a Bot

CYBER HOST supports:

- **Python (.py)** — Python Telegram bots.
- **JavaScript (.js)** — Node.js Telegram bots.
- **ZIP (.zip)** — projects containing multiple files, source code and dependency information.

### Option A — Paste code
1. Open **Create Bot**.
2. Find **Deploy with pasted code**.
3. Enter a bot name.
4. Select Python or JavaScript.
5. Paste the source code.
6. Press **Deploy Code**.

### Option B — Upload a project
1. Open **Create Bot**.
2. Enter a project name.
3. Select a supported .py, .js or .zip file.
4. Add any required environment variables.
5. Press **Upload Project**.

### Environment Variables
Environment variables let your bot read configuration values without placing them directly in its source code. Examples include BOT_TOKEN, API_ID, API_HASH and MONGO_URI.

- Enter the exact variable names expected by your bot.
- Values are encrypted before being saved by the website.
- Values are supplied to the bot when it starts.
- Keep credentials private. Never share screenshots or source files containing live secrets.

### After deployment
- An administrator's own upload is approved automatically.
- A normal user's upload is marked **Pending**.
- An administrator reviews the submission and approves or rejects it.
- After approval, the bot can be started from the bot controls.

## 3. Manage Your Bots

Open **My Bots** to see your projects. Depending on the bot's status, available controls may include:

| Button / Feature | Purpose |
|---|---|
| **Start / Restart** | Launch the bot process or restart it. |
| **Stop** | Stop a running bot. |
| **Terminal** | Open the browser-based project command interface. |
| **Live Logs** | Inspect recent output and error messages. |
| **Edit Code** | Edit supported single-file Python or JavaScript bots. |
| **Delete** | Remove the bot and its associated stored files. |

### Edit Bot Code
For supported .py and .js bots, use **Edit Code** to update the source and bot name. Saving updates the stored source. If the bot was already approved, the website attempts to restart it with the updated code.

ZIP projects are managed through their project files and terminal workflow rather than the single-file code editor.

## 4. Terminal & Live Logs

### Terminal
The browser terminal provides a mobile-friendly interface for selected project tasks, such as viewing files, checking runtime versions and installing supported dependencies.

It is a restricted project tool, not a complete Linux shell or unrestricted Termux replacement. Only commands supported by the website are available.

### Live Logs
Open **Live Logs** to inspect recent bot output. Logs can help identify:
- Invalid bot configuration.
- Missing environment variables.
- Python or Node.js dependency errors.
- Startup exceptions.
- Runtime errors printed by the bot.

If a bot does not start, review its latest logs, correct the reported issue and restart it.

## 5. Automatic Bot Data & Persistent Storage

CYBER HOST provides a separate data location for each bot so supported files created by a bot can be retained between restarts.

### How it works
1. The website creates a bot-specific data directory automatically.
2. The bot receives directory locations through the BOT_DATA_DIR, DATA_DIR and PERSISTENT_DIR environment variables.
3. The website periodically creates a backup of the bot's runtime files and data.
4. When the bot starts again, the website attempts to restore the latest available backup.
5. Each bot's data is stored separately at the application level.

This can help preserve locally stored application data and supported session files. The bot or library must actually write its data to disk; information held only in memory cannot be preserved by a file backup.

**Important:** Persistent backups require the website's Supabase Storage integration to be configured correctly. Backups are periodic and best-effort, not instant real-time synchronization. A sudden crash can cause changes made after the last successful backup to be lost. File-size and file-count limits apply. Test restore behavior before relying on it for important data.

## 6. Credit Store & Payments

The **Credit Store** displays plans made available by the administrator.

### Submit a payment request
1. Open **Credit Store**.
2. Review the available plan and price.
3. Follow the payment details displayed on the website.
4. Complete the payment using your payment application.
5. Enter the transaction UTR/reference in the payment form.
6. Submit the request.

Your request appears in **Payment History**. Credits are added after an administrator checks and approves the payment. Submitting a UTR does not mean the payment has already been approved.

## 7. Admin Panel

Only accounts with administrator permission can open the admin pages.

| Admin section | What it does |
|---|---|
| **Bot Management** | View hosted bots and owners, review pending submissions, approve or reject bots. |
| **Bot File Manager** | Browse available runtime and persistent-data files for individual bots. |
| **Payment Management** | Review payment references and approve or reject requests. |
| **User Management** | View registered accounts and adjust user credits. |
| **Website Settings** | Update site name, UPI details, payment QR and support text. |
| **Plans & Pricing** | Add plans, update prices and credits, activate or deactivate plans. |
| **API Access** | Create scoped API tokens, review permissions and revoke tokens. |

### Admin Bot File Manager
1. Open **Admin Panel → Bot Management**.
2. Press **Bot File Manager**.
3. Select the bot you want to inspect.
4. Browse its available runtime and data files.
5. Open a supported text file to preview or edit it.
6. Save changes when required. Restart the bot if a runtime file needs to be reloaded.

The file manager can include local files available on the current instance and files indexed from the saved Supabase backup. Credential-like files — including files associated with passwords, tokens, private keys or sessions — are protected from browser preview and editing to reduce accidental exposure.

The file manager is not a live remote desktop or a full storage console. What appears depends on the bot's available files and the latest successful backup.

## 8. API Access

Administrators can create API tokens for approved integrations. Each token can have selected permissions, an expiry period and can be revoked from the Admin API page.

Available permission groups:

- **site:read** — read selected website settings.
- **users:read** — list registered users.
- **bots:read** — read bot details and statuses.
- **bots:control** — approve, reject, stop or restart bots.
- **bots:delete** — delete bots.
- **payments:read** — read payment requests.

API requests use a bearer token in the Authorization header. Keep tokens private and grant only the permissions an integration needs. The complete token is shown only when it is created.

## 9. GitHub Import

If GitHub connection has been configured for the website, users can connect their GitHub account and import a repository they are authorized to access.

1. Open **Create Bot** and choose **Connect GitHub**.
2. Authorize the GitHub connection.
3. Select a repository and branch.
4. Add environment variables required by the project.
5. Start the import.

Imported projects follow the website's normal approval process. A repository import is a copy of the selected branch at that time; it does not automatically sync every later GitHub commit. Re-import the repository to bring in newer code.

## 10. How the Website Works

The usual workflow is:

**Register → Deploy → Admin Review → Start Bot → Monitor Logs → Save Data → Manage**

- Users create an account and submit a supported bot project.
- The website stores the uploaded project and its deployment details.
- Normal user uploads wait for administrator approval.
- Once approved, the hosting service launches the bot process.
- Users monitor status and output through the website.
- The persistence feature periodically backs up supported runtime and data files when Supabase Storage is configured.
- Administrators manage users, bots, payments, plans, website settings and API permissions from the admin panel.

## 11. Important Usage & Hosting Notes

- Available runtime resources depend on the hosting provider and its plan.
- Free hosting services may sleep, restart or stop applications. CYBER HOST cannot guarantee uninterrupted 24/7 bot uptime.
- Automatic backups depend on a working private Supabase Storage configuration.
- Backups are periodic, so keep independent copies of important bot data.
- A bot must save its own session or application data to disk or an external database for that information to persist.
- Dependency installation may fail if a package is unavailable, incompatible or exceeds host resource limits.
- Uploaded bot code executes on the hosting server. Only deploy code you trust.
- Per-bot folders organize data but do not provide hardened operating-system isolation between untrusted programs.
- Never share administrator credentials, API tokens, bot tokens or Supabase service credentials.

---

<div align="center">

## CYBER HOST

**A single dashboard to deploy, manage and monitor your Telegram bots.**

Built for a smooth mobile experience.

### Owner — Anand Singh

</div>
