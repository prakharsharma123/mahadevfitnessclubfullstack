# Deployment Guide — Mahadev Fitness Club

Everything below uses only free tiers. Total setup time: ~20 minutes.

## 1. Create a GitHub repo for the app code
```bash
git init
git add .
git commit -m "Mahadev Fitness Club - gym management system"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mahadev-fitness-club.git
git push -u origin main
```

## 2. Create a second, small GitHub repo for member photos
This app stores photos in their own **public** GitHub repo (free, permanent,
survives redeploys) and serves them through the free jsDelivr CDN.

1. Create a new repo, e.g. `gym-photos` (Public — jsDelivr only mirrors public repos).
2. Add one commit with an empty `members/.gitkeep` file so the folder exists.
3. Create a GitHub Personal Access Token:
   - GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained token**
   - Repository access: only the `gym-photos` repo
   - Permissions: **Contents: Read and write**
   - Copy the token — you'll paste it into Render as `GITHUB_TOKEN`.

> Member photos are personal data. Because the photo repo is public, anyone
> with the exact image URL could view a photo (URLs aren't listable/guessable
> in practice, but they aren't access-controlled either). If that's a concern,
> switch to Supabase Storage (also free) instead — ask and this can be swapped in.

## 3. Create a free Postgres database (Neon)
Render's own free Postgres tier expires after ~30 days, which would silently
wipe your member data — so this app uses **Neon** instead, whose free tier
has no such expiry.

1. Go to https://neon.tech → sign up free → New Project.
2. Copy the **connection string** it gives you (starts with `postgresql://`).
3. You'll paste this into Render as `DATABASE_URL`.

## 4. Deploy the web app on Render
1. Go to https://render.com → New → Web Service → connect your `mahadev-fitness-club` repo.
2. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: leave blank (uses the Procfile)
   - **Instance Type**: Free
3. Environment → add these variables:

| Key | Value |
|---|---|
| `SECRET_KEY` | any long random string |
| `ADMIN_USERNAME` | your chosen admin username |
| `ADMIN_PASSWORD` | your chosen admin password |
| `DATABASE_URL` | the Neon connection string from step 3 |
| `GITHUB_TOKEN` | the token from step 2 |
| `GITHUB_REPO` | `YOUR_USERNAME/gym-photos` |
| `GITHUB_BRANCH` | `main` |

4. Click **Create Web Service**. First deploy takes 3–5 minutes.
5. Visit `/health` on your Render URL to confirm it's live.

## 5. Keep the free instance awake (optional)
Render's free tier sleeps after 15 minutes of no traffic (first request after
that takes ~30–50s to wake up). To avoid that:
- https://uptimerobot.com — free monitor, ping `https://YOUR-APP.onrender.com/health` every 5 minutes.

## Data safety summary
- **Member records** live in Neon Postgres — a real database, not a file on
  Render's disk, so redeploys/restarts never touch them.
- **Photos** live in the `gym-photos` GitHub repo — also unaffected by
  redeploys.
- Both are only ever removed when an admin clicks **Delete** on a member —
  there is no automatic cleanup or expiry anywhere in the code.
- Back up any time by cloning the `gym-photos` repo and using Neon's built-in
  point-in-time restore / SQL export (free tier included).
