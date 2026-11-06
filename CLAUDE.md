# CLAUDE.md - Mahadev Fitness Club Gym System

Read this first. It is the single source of truth for what this project is, what is done,
and what to build next. Update the checkboxes as work is completed.

## 1. What we are building
A gym web app for **Mahadev Fitness Club** (owner: Ashish Singh) with three parts:

| Part | URL | Who | What it does |
|---|---|---|---|
| Public landing | `/` | everyone | Two buttons: Member Login, Admin Login |
| Member (client) side | `/client/login`, `/signup`, `/client/register`, `/client/home` | gym members | Sign up / log in with **Google**, add mobile number, see streak, visits, membership expiry |
| QR attendance | `/checkin?k=<GYM_QR_KEY>` | gym members | The page the printed QR opens. Logged in: marks present at once. New person: Google login, then phone number, then marked present |
| Admin | `/admin/login`, `/admin`, `/admin/attendance`, `/members`, `/add`, `/pending_sms`, `/export_members` | owner / staff | Full access: dashboard, members, fees, WhatsApp reminders, Excel export, daily attendance, new signups |

**Owner alert:** every time someone marks attendance (and every new signup) the owner gets an
instant Telegram message: name, time, phone, streak, how many are present today.

## 2. Stack and the database decision
- Backend: **Flask** (Python), server-rendered Jinja templates, one CSS file. No build step.
- Auth for members: **Google OAuth 2.0** via Authlib (free). Admin: username/password from env vars.
- Database: **PostgreSQL on Neon (free)**. Keep it. SQLite only for local testing.
  - Why: the data is relational (member -> many attendance rows, one per day enforced by a unique constraint),
    it is already wired in, the free tier does not expire, and a gym's data is tiny
    (300 members x 365 days is about 110k small rows a year).
  - MongoDB Atlas would work but gives no benefit here and would mean rewriting every query.
  - Do not use SQLite in production: Render's disk is wiped on every deploy.
- Photos: public GitHub repo via jsDelivr (already built).
- Hosting: Render free web service. It sleeps after about 15 minutes idle, so the first QR scan of the
  morning can take 30-60 seconds. Fix: free UptimeRobot monitor pinging `/health` every 5 minutes.
- Alerts: Telegram bot (free, instant, no approval needed). WhatsApp Business API is not free.

## 3. Files
```
app.py              models (Member, Attendance), admin routes, schema upgrade on start
client_routes.py    Google login, signup, register, member home, /checkin, /admin/attendance
notify.py           Telegram alerts (background thread, never blocks a check-in)
github_storage.py   photo upload
templates/          landing, client_login, client_register, client_home, checkin_result,
                    admin_attendance + existing admin pages
scripts/make_qr.py  creates gym-qr.png
docs/               GOOGLE_OAUTH_GUIDE.md, TELEGRAM_GUIDE.md
```
Schema changes: `upgrade_schema()` in app.py adds new Member columns automatically on start, so the
existing Neon database keeps all current members. The `attendance` table is created automatically.

## 4. Environment variables (.env locally, Render dashboard in production)
`SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, DATABASE_URL, GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH,
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GYM_QR_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID`

## 5. Step-by-step plan
Work top to bottom. Each step is small. Tick it when done.

### Phase A - Code (done by Claude)
- [x] Public landing page `/`
- [x] Member login and signup with Google (`/client/login`, `/signup`)
- [x] Registration step: new member adds phone number
- [x] Member home: streak, best streak, visits, 28-day calendar, membership expiry
- [x] QR check-in `/checkin?k=...` with duplicate protection (one per day) and wrong-QR protection
- [x] Telegram alert to owner on every check-in and every new signup
- [x] Admin: `/admin`, `/admin/attendance` (by date), new-signup list with "Set plan" button, test alert button
- [x] Removed the admin password that was printed on the login page
- [x] Auto database upgrade, QR generator script, guides

### Phase B - Accounts you create (about 20 minutes, all free)
- [ ] B1. Google OAuth client: follow `docs/GOOGLE_OAUTH_GUIDE.md`, get Client ID and Secret
- [ ] B2. Telegram bot: follow `docs/TELEGRAM_GUIDE.md`, get Bot Token and Chat ID
- [ ] B3. Pick a secret `GYM_QR_KEY` (random word, e.g. `mahadev-7x2k9q`)

### Phase C - Run locally
- [ ] C1. `cp .env.example .env` and fill in the values from Phase B
- [ ] C2. `pip install -r requirements.txt`
- [ ] C3. `python app.py`, open `http://localhost:5000` (use localhost, not 127.0.0.1)
- [ ] C4. Open `http://localhost:5000/checkin?k=YOUR_KEY`, sign in with Google, add phone, check you are marked present
- [ ] C5. Check the Telegram message arrived and `/admin/attendance` shows you
- [ ] C6. In Google Cloud add `http://localhost:5000` and `http://localhost:5000/auth/google/callback` (guide step 5)

### Phase D - Deploy
- [ ] D1. Push code to GitHub, redeploy on Render (see `DEPLOYMENT_GUIDE.md`)
- [ ] D2. Add all env vars in Render, including the new Google, QR key and Telegram ones
- [ ] D3. In Google Cloud add your live site URL and `https://YOUR-SITE/auth/google/callback`
- [ ] D4. Publish the Google app to Production (guide step 4) so every member can sign in
- [ ] D5. Add UptimeRobot monitor for `https://YOUR-SITE/health`

### Phase E - QR code
- [ ] E1. `python scripts/make_qr.py https://YOUR-SITE` creates `gym-qr.png`
- [ ] E2. Print it large and stick it at the entrance (A4, laminated)
- [ ] E3. Scan it with a phone that has never logged in: login, phone, marked present, Telegram alert arrives

### Phase F - Ideas for later (ask Claude to build any of these)
- [ ] Owner can mark attendance manually for a member who forgot their phone
- [ ] Hide the check-in for members whose plan expired, and tell them to pay
- [ ] Notice board and "gym closed" announcements shown on member home
- [ ] Attendance export to Excel, weekly "who has not come for 7 days" list with WhatsApp reminder
- [ ] Rotate the QR key monthly, or make the QR location-aware
- [ ] Link new self-signups to an existing admin-added member (merge by phone)

## 6. Rules for Claude when editing this project
1. Never delete members or attendance automatically. Only explicit admin actions delete data.
2. Keep it free-tier friendly: no paid APIs, no heavy dependencies.
3. Day boundaries use India time (Asia/Kolkata). Store `Attendance.day` as `YYYY-MM-DD`.
4. A failed Telegram message must never break a check-in.
5. Never print secrets or default passwords in templates or logs.
6. After any change run a quick Flask test-client check of: `/`, `/client/login`, `/checkin`, `/admin/login`, `/admin/attendance`.
