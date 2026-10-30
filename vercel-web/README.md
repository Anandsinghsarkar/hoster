# CYBER HOST — Vercel web entry

This folder is the Vercel deployment root for the compatibility deployment.

## Vercel project settings

- Repository: Anandsinghsarkar/hoster
- Root Directory: vercel-web
- Framework Preset: Next.js
- Build Command: npm run build
- Output Directory: leave the Next.js default
- Install Command: npm install

Add this Environment Variable for Production (and Preview if used):

| Name | Value |
|---|---|
| RENDER_BACKEND_URL | https://hoster-1-1qzm.onrender.com |

Deploy, then test the Vercel domain at /, /login, /dashboard, and /health.

## Current architecture — read carefully

The Vercel Next.js route handler forwards website requests to the existing Flask service on Render. This keeps existing login, sessions, dashboard, admin tools, Telegram admin bot, bot controls, and current data model working without deleting or duplicating them.

**This is a compatibility bridge, not the completed frontend/backend split.** Flask still renders the HTML pages and handles application routes on Render. Bot processes also still run in the existing Render service. Vercel is the public entry point only; it does not yet move page rendering or application logic off Render.

Do not disable or delete the current Render service. Keep its environment variables and Supabase configuration unchanged. The Render URL above must remain reachable from Vercel.

## Upload and runtime limits

- Vercel Function request/response limits still apply. Large ZIP uploads may fail through this proxy. A production migration should upload files directly from the browser to private Supabase Storage using short-lived signed upload URLs.
- The current Render app executes uploaded projects as child processes in the same container. It is not a hardened multi-tenant sandbox. Only approve and run source code you trust.
- Render free instances can sleep/restart and do not guarantee 24/7 bot uptime.
- No build, live deployment, login, upload, bot-run, or payment test is performed by this repository commit. Verify these on the deployed Vercel and Render services before using with real users.

## Required existing Render configuration

Keep the existing required values configured on Render:

- SECRET_KEY — stable private secret; changing it can invalidate encrypted saved values and sessions.
- ADMIN_USERNAME and ADMIN_PASSWORD — set a strong admin password.
- SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_STORAGE_BUCKET=bot-files — if using persistent snapshots/uploads.
- GitHub OAuth variables if GitHub import is enabled.
- Telegram admin bot token/owner are configured from the existing admin page.

Never put Render secrets or the Supabase service-role key in browser-side code or commit them to GitHub.

## Next migration stage

A genuine split requires migrating each Flask page and its business routes into Next.js, moving shared account/session state to a server-side auth/API layer, creating a dedicated Render bot-worker service, and implementing direct signed uploads to Supabase. Migrate and test feature-by-feature to preserve existing users, credits, payments, files, and bot records.
