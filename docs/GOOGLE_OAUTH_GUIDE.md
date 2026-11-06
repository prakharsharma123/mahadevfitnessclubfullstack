# Google Sign-in Setup (free, about 10 minutes)

You will get a **Client ID** and **Client Secret** and paste them into `.env` / Render.

The error you saw (`Error 401: invalid_client - The OAuth client was not found`) means the Client ID the app
sent does not exist at Google. It happens when the ID is empty, is still a placeholder like
`your_client_id`, has a typo, or belongs to a deleted client. The steps below fix it.

## Step 1. Create a project
1. Go to https://console.cloud.google.com and sign in with the gym's Google account.
2. Top bar, project picker, **New project**. Name it `Mahadev Fitness Club`. Click **Create**, then select it.

## Step 2. Set up the consent screen
1. Open the menu, **APIs & Services**, **OAuth consent screen** (it may be called **Google Auth Platform**).
2. Click **Get started**.
3. App name: `Mahadev Fitness Club`. User support email: your email. Click Next.
4. Audience: choose **External**. Click Next.
5. Contact email: your email. Agree to the policy, **Create**.

## Step 3. Create the OAuth client
1. Go to **Clients** (or **Credentials**, **Create credentials**, **OAuth client ID**).
2. Application type: **Web application**. Name: `Gym web`.
3. **Authorized JavaScript origins** (add each, no trailing slash):
   - `http://localhost:5000`
   - `https://YOUR-APP.onrender.com` (add once deployed)
4. **Authorized redirect URIs** (must match exactly):
   - `http://localhost:5000/auth/google/callback`
   - `https://YOUR-APP.onrender.com/auth/google/callback` (add once deployed)
5. Click **Create**. Copy the **Client ID** and **Client secret**.

## Step 4. Let every member sign in (important)
New apps start in **Testing** mode, where only people you list as test users can log in. Everyone else sees
"Access blocked". Fix it:
1. Go to **Audience** (or OAuth consent screen).
2. Click **Publish app**, confirm. Status becomes **In production**.
3. The app only asks for name, email and photo, so Google does not require a review. Members may see an
   "unverified app" notice only if you add sensitive scopes, which this app does not.

## Step 5. Put the keys in the app
Local `.env`:
```
GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
```
Render: your service, **Environment**, add the same two variables, then redeploy.
Restart the app after changing them.

## Troubleshooting
| Message | Cause and fix |
|---|---|
| `invalid_client` / client not found | ID empty, placeholder, typo, or wrong project. Re-copy it. No spaces or quotes. |
| `redirect_uri_mismatch` | The redirect URI in Google differs from the app's. Check http vs https, no trailing slash, and use `localhost` not `127.0.0.1`. The exact URI is shown in the error details. |
| `Access blocked: app has not completed verification` / `access_denied` | App is in Testing. Do Step 4, or add the person under **Audience, Test users**. |
| Login works locally but not on Render | You did not add the Render URL in Step 3, or `GOOGLE_*` is missing in Render. |
| Page says "Google login is not set up yet" | `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` is empty in the running app. |
