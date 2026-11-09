"""
push.py - Chrome / browser push notifications for the owner (free, Web Push + VAPID).

How it works:
  1. The admin opens Attendance, taps "Enable notifications" and allows Chrome's permission prompt.
  2. The browser gives us a private subscription address, saved in the push_subscription table.
  3. Every time notify.notify_owner() runs (check-in, new signup, payment...) we also send a push to
     every saved device. It arrives even if the tab is closed or the phone is locked (Android),
     or while Chrome is running (laptop).

Needs env vars VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_EMAIL.
Make them with:  python scripts/make_vapid_keys.py
"""
import os
import json
import threading
from datetime import datetime

from flask import request, jsonify, send_from_directory


def vapid_ready():
    return bool(os.environ.get("VAPID_PUBLIC_KEY") and os.environ.get("VAPID_PRIVATE_KEY"))


def _claims():
    sub = os.environ.get("VAPID_EMAIL", "admin@example.com").strip()
    if not sub.startswith(("mailto:", "https://")):
        sub = "mailto:" + sub
    return {"sub": sub}


def register(app, db, require_login, notify):

    class PushSubscription(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        endpoint = db.Column(db.String(800), unique=True, nullable=False)
        p256dh = db.Column(db.String(200), nullable=False)
        auth = db.Column(db.String(100), nullable=False)
        label = db.Column(db.String(150))
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

    with app.app_context():
        db.create_all()  # creates the new table on first start; existing data is untouched

    # ------------------------------------------------------------ sending
    def deliver(title, body, url="/admin/attendance"):
        """Send to every saved device. Returns (sent, removed, failed). Never raises."""
        if not vapid_ready():
            return 0, 0, 0
        from pywebpush import webpush, WebPushException
        payload = json.dumps({"title": title, "body": body, "url": url})
        sent = removed = failed = 0
        with app.app_context():
            for s in PushSubscription.query.all():
                try:
                    webpush(
                        subscription_info={"endpoint": s.endpoint,
                                           "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                        data=payload,
                        vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                        vapid_claims=_claims(),   # new dict each time (the library edits it)
                        ttl=3600,                  # drop it if the phone stays offline for 1 hour
                        headers={"Urgency": "high"},
                        timeout=10,
                    )
                    sent += 1
                except WebPushException as e:
                    code = getattr(e.response, "status_code", None)
                    if code in (404, 410):   # device unsubscribed or app data cleared
                        db.session.delete(s)
                        removed += 1
                    else:
                        failed += 1
                        print("Push failed:", code, str(e)[:200])
                except Exception as e:
                    failed += 1
                    print("Push error:", str(e)[:200])
            db.session.commit()
        return sent, removed, failed

    def push_text(text):
        """Hook used by notify.notify_owner: first line becomes the title, the rest the body."""
        if not vapid_ready():
            return
        lines = [l for l in text.split("\n") if l.strip()]
        if not lines:
            return
        title = lines[0]
        body = "\n".join(lines[1:]) or lines[0]
        threading.Thread(target=deliver, args=(title, body), daemon=True).start()

    notify.set_push_hook(push_text)

    # ------------------------------------------------------------ routes
    @app.route("/sw.js")
    def service_worker():
        # Must be served from the site root so it can control the whole site
        resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    @app.route("/admin/push/config")
    def push_config():
        if require_login():
            return jsonify({"error": "unauthorized"}), 401
        return jsonify({"enabled": vapid_ready(),
                        "key": os.environ.get("VAPID_PUBLIC_KEY", ""),
                        "devices": PushSubscription.query.count()})

    @app.route("/admin/push/subscribe", methods=["POST"])
    def push_subscribe():
        if require_login():
            return jsonify({"error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        sub = data.get("subscription") or {}
        keys = sub.get("keys") or {}
        if not (sub.get("endpoint") and keys.get("p256dh") and keys.get("auth")):
            return jsonify({"error": "bad subscription"}), 400
        row = PushSubscription.query.filter_by(endpoint=sub["endpoint"]).first()
        if not row:
            row = PushSubscription(endpoint=sub["endpoint"])
            db.session.add(row)
        row.p256dh, row.auth = keys["p256dh"], keys["auth"]
        row.label = (data.get("label") or "")[:150]
        db.session.commit()
        return jsonify({"ok": True, "devices": PushSubscription.query.count()})

    @app.route("/admin/push/unsubscribe", methods=["POST"])
    def push_unsubscribe():
        if require_login():
            return jsonify({"error": "unauthorized"}), 401
        endpoint = (request.get_json(silent=True) or {}).get("endpoint")
        if endpoint:
            PushSubscription.query.filter_by(endpoint=endpoint).delete()
            db.session.commit()
        return jsonify({"ok": True})

    @app.route("/admin/push/test", methods=["POST"])
    def push_test():
        if require_login():
            return jsonify({"error": "unauthorized"}), 401
        if not vapid_ready():
            return jsonify({"ok": False, "message": "VAPID keys are not set on the server."})
        sent, removed, failed = deliver("🏋️ Test: Ajay marked attendance",
                                        "🕒 6:42 AM | Your phone alerts are working.")
        return jsonify({"ok": sent > 0, "sent": sent, "removed": removed, "failed": failed})

    return PushSubscription
