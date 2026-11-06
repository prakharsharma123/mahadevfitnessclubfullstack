# Owner Alerts on Telegram (free, about 5 minutes)

Every check-in and new signup sends the owner a message like:

```
🏋️ Rahul Sharma marked attendance
🕒 06:42 AM  |  📞 9876543210
🔥 Streak: 5 days  |  👥 Today: 12 present
```

## Step 1. Create the bot
1. Install Telegram on your phone and open it.
2. Search **@BotFather** (blue tick), open it, tap **Start**.
3. Send `/newbot`. Give it a name (`Mahadev Gym Alerts`) and a username ending in `bot` (`mahadev_gym_alerts_bot`).
4. BotFather replies with a token like `123456789:AAF...`. That is `TELEGRAM_BOT_TOKEN`. Keep it private.

## Step 2. Get your Chat ID
1. Open your new bot, tap **Start**, and send it any message, for example `hi`.
2. In a browser open `https://api.telegram.org/botYOUR_TOKEN/getUpdates` (replace YOUR_TOKEN, keep the word `bot` before it).
3. Find `"chat":{"id":123456789` . That number is `TELEGRAM_CHAT_ID`.
   If the page shows `"result":[]`, send the bot another message and refresh.

## Step 3. Add to the app
```
TELEGRAM_BOT_TOKEN=123456789:AAF...
TELEGRAM_CHAT_ID=123456789
```
Local `.env` and the Render Environment page. Restart/redeploy.

## Step 4. Test
Log in as admin, open **Attendance**, click **Send test alert**. A message should arrive in seconds.

## Alert to staff too
Make a Telegram group, add the bot and your staff, send a message in the group, then run `getUpdates` again.
The group's chat id starts with a minus sign (for example `-1001234567890`). Use that as `TELEGRAM_CHAT_ID`.
