# Render Web App

This folder is a separate Flask web version of your desktop `tkinter` app, prepared for deployment on Render.

## What it does now

- Keeps your current desktop bot untouched
- Uses the same `SupabaseUserManager` backend as the desktop app for login, registration, and password reset
- Uses the same `DerivBot` trading engine as the desktop app for bot start/stop, mode changes, positions, history, logs, and manual trades
- Reuses the same logo and icon assets in the browser tab and dashboard

## Run locally

```bash
pip install -r ../requirements.txt
python app.py
```

## Render deployment notes

- Deploy the whole repository, not only the `webapp` folder, because the web app imports code from the root `modules/` and `config.py`
- Create a new Render Web Service, not a Background Worker, because this project serves HTTP pages and a health endpoint
- Render can use the root [render.yaml](c:/Users/Steph/Desktop/UwezoFx%20D_Bot/render.yaml:1) blueprint or equivalent dashboard settings
- Install dependencies from the root [requirements.txt](c:/Users/Steph/Desktop/UwezoFx%20D_Bot/requirements.txt:1)
- Add the same environment variables your desktop app uses for Supabase and optional email/SMS integrations
- Set `FLASK_SECRET_KEY` in Render so sessions are secure
- Render health checks can use `/healthz`
- Your public app will start through Gunicorn with `gunicorn --chdir webapp app:app`

## Free plan note

Render's current free option applies to Web Services, not Background Workers. Free Web Services spin down after 15 minutes without inbound traffic, so this setup is good for testing and hobby use but not ideal for uninterrupted production trading.

## Important

Your original app is still a desktop `tkinter` application, so it cannot be hosted directly on Render as-is. This web copy reuses the same backend classes and is the correct deployment target for Render.
