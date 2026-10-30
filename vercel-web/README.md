# CYBER HOST — Vercel compatibility frontend

This is the first migration stage. It provides a Vercel-hosted HTTP entry point while preserving every existing Flask route, form, session cookie, upload, admin action, and Telegram workflow through the existing Render service.

## Deploy

1. In Vercel, import this repository.
2. Set **Root Directory** to `vercel-web`.
3. Framework preset: Next.js.
4. Add environment variable `RENDER_BACKEND_URL=https://hoster-1-1qzm.onrender.com`.
5. Deploy.

## Important architecture note

This stage is a compatibility bridge, not the completed frontend/backend separation. Existing pages are still rendered by Flask on Render and proxied through Vercel. Bot processes also remain on Render. This keeps current functionality intact while the frontend is migrated page-by-page to native Next.js and the bot runner is separated into a dedicated Render worker.

Do not remove or disable the existing Render service during this stage. Keep its existing environment variables and Supabase configuration unchanged.
