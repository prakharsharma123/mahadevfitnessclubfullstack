# 🏋️ Mahadev Fitness Club — Gym Management System

A clean, modern, mobile-friendly gym management dashboard for a single admin
(or a small staff team sharing one login) to manage members, fees, and
payment reminders — built entirely on free infrastructure.

## Stack, and why

| Layer | Choice | Why |
|---|---|---|
| Backend | **Flask** (Python) | Small, free, well-documented; matches the app you already had, so nothing to relearn. Handles auth, routes, and the WhatsApp/Excel logic in plain, readable code. |
| Database | **PostgreSQL via Neon.tech (free tier)** | Render's local disk (and its own free Postgres) get wiped/expire — Neon's free tier is a real always-on database with no expiry, so member data is never silently lost. SQLite is kept only as a local-dev fallback. |
| Member photos | **A public GitHub repo, served via the free jsDelivr CDN** | You asked for images stored on GitHub. This app uploads each photo through the GitHub API and reads it back through jsDelivr's GitHub CDN, so photos are free, permanent, and load fast worldwide — with zero storage service to pay for. |
| Hosting | **Render (free web service)** | Free tier, deploys straight from GitHub, works well with a Flask + gunicorn app. |
| Frontend | Server-rendered HTML (Jinja2) + one CSS file, no JS framework | Keeps the whole app in one deployable unit (simpler for a free tier, faster cold starts, nothing to build/bundle). Light/dark mode is pure CSS variables toggled with a few lines of JS. |
| Excel export | `openpyxl` | Free, no external service, generates a real `.xlsx` on demand. |
| Payment reminders | `wa.me` deep links | No SMS/WhatsApp API cost — clicking "WhatsApp" opens a pre-filled message ready to send from the admin's own phone/WhatsApp Web. |

## New: member login, QR attendance, owner alerts
Members sign up with Google at `/client/login` or `/signup`, and mark attendance by scanning the gym QR
(`/checkin?k=KEY`). The owner gets a Telegram message for every check-in. Admin is now at `/admin/login`.
See **CLAUDE.md** for the full plan and `docs/` for the Google and Telegram setup guides.

## Features

- 🔐 Admin login (env-var based; change the password before going live)
- 📊 Dashboard — total members, active/expired counts, revenue today & total
- 👥 Member list — photo thumbnail, plan, fees, expiry, status badge, search & filter
- 📸 Photo upload on add/edit, stored permanently on GitHub
- ✅ One-click "Mark Paid", ✏️ edit, 🗑️ delete (delete is the **only** thing that removes a member — nothing is ever auto-deleted)
- 💬 Per-member WhatsApp reminder link + a "Pending" page to copy phone/message for manual bulk sending
- 📥 Export all members to Excel
- 🌗 Light / dark mode toggle (saved per-browser)
- 📱 Fully responsive — usable on a phone at the front desk

## Local development

```bash
cp .env.example .env      # fill in values, or leave DATABASE_URL blank to use local SQLite
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Deploying for free

See **DEPLOYMENT_GUIDE.md** for the full step-by-step (GitHub repo → Neon
database → GitHub photo repo → Render).

## Project structure

```
├── app.py                # routes, models, business logic
├── github_storage.py      # uploads/deletes member photos in the GitHub photo repo
├── requirements.txt
├── Procfile               # gunicorn start command for Render
├── runtime.txt             # Python version for Render
├── templates/
│   ├── base.html           # shared layout, nav, theme toggle
│   ├── login.html
│   ├── dashboard.html
│   ├── members.html
│   ├── add_member.html
│   ├── edit_member.html
│   └── pending_sms.html
└── static/
    ├── style.css            # design tokens (light/dark), all layout
    └── app.js                # theme toggle + mobile nav
```

## Extending later (kept simple for now on purpose)

- **Multiple staff logins**: currently one shared admin login via env vars,
  matching the "simple, easy to understand" brief. Swapping in a `User` table
  with per-person logins and roles is a natural next step if needed.
- **Private photo storage**: swap `github_storage.py` for Supabase Storage
  (also free) if photos need to be access-controlled rather than public.
