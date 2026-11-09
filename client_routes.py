"""
client_routes.py - public side of the app:
  /client/login, /signup   -> sign in / create account with Google
  /client/register         -> new members add their mobile number
  /client/home             -> member's own page (streak, history, membership)
  /checkin?k=KEY           -> the page the gym QR code opens (marks attendance)
and the admin attendance pages:
  /admin/attendance        -> who came on a given day + new online signups
  /admin/test-alert        -> sends a test Telegram message to the owner
"""
import os
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from authlib.integrations.flask_client import OAuth
from flask import (render_template, request, redirect, session, url_for,
                   flash, jsonify)
from sqlalchemy.exc import IntegrityError

import notify
import github_storage

IST = ZoneInfo("Asia/Kolkata")


def today_ist():
    return datetime.now(IST).date()


def register(app, db, Member, Attendance, Announcement, require_login, PLAN_MONTHS, PLAN_FEES, add_months):
    oauth = OAuth(app)
    google_ready = bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    if google_ready:
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    # ------------------------------------------------------------ helpers
    def current_client():
        cid = session.get("client_id")
        return db.session.get(Member, cid) if cid else None

    def streak_info(member):
        """Current streak (counts if last visit was today or yesterday) and best streak."""
        days = sorted({a.day for a in Attendance.query.filter_by(member_id=member.id).all()})
        if not days:
            return 0, 0, days
        dset = {date.fromisoformat(d) for d in days}
        best = run = 0
        prev = None
        for d in sorted(dset):
            run = run + 1 if prev and (d - prev).days == 1 else 1
            best = max(best, run)
            prev = d
        t = today_ist()
        cursor = t if t in dset else (t - timedelta(days=1) if (t - timedelta(days=1)) in dset else None)
        current = 0
        while cursor and cursor in dset:
            current += 1
            cursor -= timedelta(days=1)
        return current, best, days

    def safe_next(default):
        nxt = session.pop("next", None)
        # only allow local paths, never an external URL
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return nxt
        return default

    # ------------------------------------------------------------ login / signup
    @app.route("/client/login")
    def client_login():
        if current_client():
            return redirect(url_for("client_home"))
        return render_template("client_login.html", google_ready=google_ready, signup=False)

    @app.route("/signup")
    @app.route("/client/signup")
    def client_signup():
        if current_client():
            return redirect(url_for("client_home"))
        return render_template("client_login.html", google_ready=google_ready, signup=True)

    @app.route("/auth/google")
    def auth_google():
        if not google_ready:
            flash("Google login is not set up yet. The owner needs to add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", "danger")
            return redirect(url_for("client_login"))
        redirect_uri = url_for("auth_google_callback", _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def auth_google_callback():
        try:
            token = oauth.google.authorize_access_token()
            info = token.get("userinfo") or {}
        except Exception as e:
            print("Google OAuth error:", e)
            flash("Google sign-in failed or was cancelled. Please try again.", "danger")
            return redirect(url_for("client_login"))

        if not info.get("email") or not info.get("email_verified", True):
            flash("Your Google email is not verified.", "danger")
            return redirect(url_for("client_login"))

        member = Member.query.filter_by(google_id=info["sub"]).first()
        is_new = False
        if not member:
            is_new = True
            member = Member(
                name=info.get("name") or info["email"].split("@")[0],
                phone="", email=info["email"], google_id=info["sub"],
                picture_url=info.get("picture"), source="self",
                fees=0, joining_date=today_ist().isoformat(), plan=None,
            )
            db.session.add(member)
            db.session.commit()
            notify.notify_owner(f"🆕 New signup\n{member.name}\n{member.email}\nThey still need to add a phone number and a plan.")
        else:
            member.picture_url = info.get("picture") or member.picture_url
            db.session.commit()

        session["client_id"] = member.id
        session.permanent = True
        if not member.phone:
            return redirect(url_for("client_register"))
        return redirect(safe_next(url_for("client_home")))

    def parse_date(txt):
        try:
            return date.fromisoformat(txt).isoformat()
        except ValueError:
            return None

    def save_profile(m, editing):
        """Validates the profile form and saves it. Returns an error text or None."""
        phone = re.sub(r"\D", "", request.form.get("phone", ""))[-10:]
        name = request.form.get("name", "").strip() or m.name
        plan = request.form.get("plan", "")
        joining = parse_date(request.form.get("joining_date", ""))
        last_fee = parse_date(request.form.get("last_fee_date", ""))
        if len(phone) != 10:
            return "Please enter a valid 10-digit mobile number."
        if plan not in PLAN_FEES:
            return "Please choose a plan."
        if not joining or not last_fee:
            return "Please enter both the joining date and the last fee date."
        m.phone, m.name = phone, name[:100]
        m.plan, m.fees = plan, PLAN_FEES[plan]
        m.joining_date, m.last_fee_date = joining, last_fee

        photo = request.files.get("photo")
        if photo and photo.filename:
            if github_storage.is_configured():
                old = m.photo_path
                url_, path_ = github_storage.upload_photo(photo, m.id)
                if url_:
                    if old:
                        github_storage.delete_photo(old)
                    m.photo_url, m.photo_path = url_, path_
                else:
                    flash("Profile saved, but the photo upload failed. Please try again later.", "warning")
            else:
                flash("Profile saved, but photo storage is not set up yet (owner must add GITHUB_TOKEN and GITHUB_REPO).", "warning")
        db.session.commit()
        return None

    @app.route("/client/register", methods=["GET", "POST"])
    def client_register():
        m = current_client()
        if not m:
            return redirect(url_for("client_login"))
        if request.method == "POST":
            first_time = not m.phone
            err = save_profile(m, editing=False)
            if err:
                flash(err, "danger")
                return render_template("client_register.html", m=m, plan_fees=PLAN_FEES, editing=False)
            if first_time:
                notify.notify_owner(f"✅ Registration complete\n{m.name}\n📞 {m.phone}\n"
                                    f"Plan: {m.plan} | Last fee: {m.last_fee_date}\nPlease verify in the admin panel.")
            return redirect(safe_next(url_for("client_home")))
        return render_template("client_register.html", m=m, plan_fees=PLAN_FEES, editing=False)

    @app.route("/client/profile", methods=["GET", "POST"])
    def client_profile():
        m = current_client()
        if not m:
            return redirect(url_for("client_login"))
        if request.method == "POST":
            err = save_profile(m, editing=True)
            if err:
                flash(err, "danger")
            else:
                flash("Profile updated.", "success")
                return redirect(url_for("client_home"))
        return render_template("client_register.html", m=m, plan_fees=PLAN_FEES, editing=True)

    @app.route("/client/scan")
    def client_scan():
        m = current_client()
        if not m:
            session["next"] = "/client/scan"
            return redirect(url_for("client_login"))
        if not m.phone:
            return redirect(url_for("client_register"))
        return render_template("client_scan.html", m=m)

    @app.route("/client/logout")
    def client_logout():
        session.pop("client_id", None)
        return redirect(url_for("home"))

    # ------------------------------------------------------------ member home
    @app.route("/client/home")
    def client_home():
        m = current_client()
        if not m:
            return redirect(url_for("client_login"))
        if not m.phone:
            return redirect(url_for("client_register"))
        current, best, days = streak_info(m)
        t = today_ist()
        month_prefix = t.strftime("%Y-%m")
        marked_today = t.isoformat() in days
        # last 28 days strip for the little calendar
        strip = [(t - timedelta(days=i)) for i in range(27, -1, -1)]
        dset = set(days)
        cells = [{"d": d.day, "on": d.isoformat() in dset, "today": d == t} for d in strip]

        expiry = days_left = None
        if m.plan and m.last_fee_date:
            try:
                last = datetime.strptime(m.last_fee_date, "%Y-%m-%d").date()
                exp = add_months(last, PLAN_MONTHS.get(m.plan, 1))
                expiry, days_left = exp.strftime("%d %b %Y"), (exp - t).days
            except Exception:
                pass

        import payments
        pay_link = url_for("payment_page", ref=payments.make_ref(m.id)) if (m.fees or 0) > 0 else None
        notes = Announcement.query.filter_by(active=True).order_by(Announcement.id.desc()).limit(10).all()
        return render_template("client_home.html", m=m, pay_link=pay_link, current=current, best=best, announcements=notes,
                               month_count=sum(1 for d in days if d.startswith(month_prefix)),
                               total=len(days), marked_today=marked_today, cells=cells,
                               expiry=expiry, days_left=days_left)

    # ------------------------------------------------------------ QR check-in
    @app.route("/checkin")
    def checkin():
        key = request.args.get("k", "")
        expected = os.environ.get("GYM_QR_KEY", "")

        # Wrong QR / tampered link
        if expected and key != expected:
            return render_template("checkin_result.html", status="badkey")

        m = current_client()
        if not m:
            # New or signed-out person: send to login, then bring them back here
            session["next"] = request.full_path.rstrip("?")
            return redirect(url_for("client_login"))
        if not m.phone:
            session["next"] = request.full_path.rstrip("?")
            return redirect(url_for("client_register"))

        now = datetime.now(IST)
        att = Attendance(member_id=m.id, day=now.date().isoformat())
        try:
            db.session.add(att)
            db.session.commit()
            status = "ok"
        except IntegrityError:
            db.session.rollback()
            status = "duplicate"

        current, best, _ = streak_info(m)
        if status == "ok":
            count_today = Attendance.query.filter_by(day=now.date().isoformat()).count()
            notify.notify_owner(
                f"🏋️ {m.name} marked attendance\n"
                f"🕒 {now.strftime('%I:%M %p')}  |  📞 {m.phone}\n"
                f"🔥 Streak: {current} days  |  👥 Today: {count_today} present"
            )
        return render_template("checkin_result.html", status=status, m=m, current=current,
                               time=now.strftime("%I:%M %p"))

    # ------------------------------------------------------------ admin: attendance
    @app.route("/admin/attendance")
    def admin_attendance():
        if require_login():
            return redirect("/admin/login")
        try:
            day = date.fromisoformat(request.args.get("date", ""))
        except ValueError:
            day = today_ist()
        rows = (db.session.query(Attendance, Member).join(Member, Member.id == Attendance.member_id)
                .filter(Attendance.day == day.isoformat()).order_by(Attendance.checkin_time).all())
        entries = []
        for a, m in rows:
            t = a.checkin_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
            entries.append({"name": m.name, "phone": m.phone, "time": t.strftime("%I:%M %p"), "id": m.id})
        new_signups = Member.query.filter(Member.source == "self").order_by(Member.id.desc()).limit(20).all()
        return render_template("admin_attendance.html", day=day.isoformat(), entries=entries,
                               prev_day=(day - timedelta(days=1)).isoformat(),
                               next_day=(day + timedelta(days=1)).isoformat(),
                               is_today=(day == today_ist()),
                               new_signups=new_signups, telegram_ready=notify.is_configured())

    @app.route("/admin/test-alert")
    def admin_test_alert():
        if require_login():
            return redirect("/admin/login")
        ok = notify.notify_owner_now("✅ Test alert from Mahadev Fitness Club. Your attendance alerts are working.")
        flash("Test alert sent to Telegram." if ok else
              "Could not send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see docs/TELEGRAM_GUIDE.md).",
              "warning" if not ok else "success")
        return redirect("/admin/attendance")
