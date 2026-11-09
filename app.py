from dotenv import load_dotenv
load_dotenv()  # reads .env when running locally

from flask import Flask, render_template, request, redirect, session, jsonify, send_file, send_from_directory, url_for, flash, abort, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from urllib.parse import quote
import os
import io
import calendar
from werkzeug.middleware.proxy_fix import ProxyFix

import github_storage

# ---------------- PATH SETUP ----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.environ.get('INSTANCE_PATH', os.path.join(BASE_DIR, 'instance'))
os.makedirs(INSTANCE_DIR, exist_ok=True)

# ---------------- APP SETUP ----------------
app = Flask(__name__)
# Render sits behind a proxy; this makes url_for(_external=True) produce https links
# (needed so the Google OAuth redirect URI matches exactly)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key')

# IMPORTANT: In production always set DATABASE_URL to a real Postgres DB
# (e.g. a free Neon.tech database). SQLite is only a local-dev fallback -
# Render's free-tier disk is wiped on every redeploy, so member data would
# be lost if left on SQLite there. See DEPLOYMENT_GUIDE.md.
import os

db_url = os.environ.get("DATABASE_URL") or "sqlite:///gym.db"
# Always use the psycopg (v3) driver for Postgres; it installs cleanly on new Python versions.
for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
    if db_url.startswith(prefix):
        db_url = "postgresql+psycopg://" + db_url[len(prefix):]
        break

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 24 * 3600  # members stay signed in for 60 days
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024  # 6MB upload cap

db = SQLAlchemy(app)

# ---------------- PLAN CONFIG ----------------
PLAN_MONTHS = {"1_month": 1, "3_month": 3, "6_month": 6, "1_year": 12}
PLAN_FEES = {"1_month": 700, "3_month": 2500, "6_month": 4000, "1_year": 8000}


def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# ---------------- DATABASE MODEL ----------------
class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    fees = db.Column(db.Integer, default=0)
    joining_date = db.Column(db.String(20))
    last_fee_date = db.Column(db.String(20))
    plan = db.Column(db.String(20))
    payment_done = db.Column(db.Boolean, default=False)
    photo_url = db.Column(db.String(300))     # public jsDelivr/GitHub URL
    photo_path = db.Column(db.String(300))    # path inside the GitHub repo (for deletes)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # --- Client (public) accounts: filled when a member signs up with Google ---
    email = db.Column(db.String(150), index=True)
    google_id = db.Column(db.String(60), index=True)
    picture_url = db.Column(db.String(500))
    source = db.Column(db.String(10), default='admin')  # 'admin' = added by owner, 'self' = signed up online
    # Row is only ever removed by an explicit admin action on /delete/<id>.
    # There is no automatic expiry/cleanup anywhere in this app.


class Attendance(db.Model):
    """One row per member per day. The unique constraint blocks double check-ins."""
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id', ondelete='CASCADE'), nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)   # YYYY-MM-DD, India time
    checkin_time = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship('Member', backref=db.backref('attendance', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('member_id', 'day', name='uq_member_day'),)


class Announcement(db.Model):
    """Public message written by the admin; shown on every member's page."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    """One UPI payment attempt (QR session) for a member's fees."""
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = db.Column(db.String(30), unique=True)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(12), default="pending", index=True)  # pending, submitted, paid, expired, rejected
    utr = db.Column(db.String(20), index=True)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    submitted_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)


def upgrade_schema():
    """create_all() never adds columns to an existing table, so add the new
    Member columns by hand. Safe to run on every start (skips if present)."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    have = {c['name'] for c in insp.get_columns('member')}
    wanted = {'email': 'VARCHAR(150)', 'google_id': 'VARCHAR(60)',
              'picture_url': 'VARCHAR(500)', 'source': "VARCHAR(10) DEFAULT 'admin'"}
    with db.engine.begin() as conn:
        for col, ddl in wanted.items():
            if col not in have:
                conn.execute(text(f'ALTER TABLE member ADD COLUMN {col} {ddl}'))


with app.app_context():
    db.create_all()
    upgrade_schema()


# ---------------- WHATSAPP MESSAGE ----------------
def generate_wa_message(name, fees, plan, expiry_date, member_id=None):
    import payments
    payment_page = payments.pay_url(member_id) if member_id else request.url_root.rstrip("/")
    return (
        f"MAHADEV FITNESS CLUB\n"
        f"Hello {name},\n\n"
        f"Your gym fees of Rs.{fees} are due.\n"
        f"Plan: {plan}\n"
        f"Expiry: {expiry_date}\n\n"
        f"Pay online (QR + UPI): {payment_page}\n\n"
        f"- Team Mahadev"
    )


# ---------------- STATS ----------------
def calculate_revenue_stats():
    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    all_members = Member.query.all()
    stats = {
        'total_members': len(all_members), 'paid_count': 0, 'unpaid_count': 0,
        'paid_revenue': 0, 'unpaid_revenue': 0, 'total_revenue': 0,
        'active_members': 0, 'expired_members': 0,
        'paid_today_count': 0, 'paid_today_revenue': 0
    }
    for m in all_members:
        try:
            last_fee = datetime.strptime(m.last_fee_date, "%Y-%m-%d").date()
            expiry = add_months(last_fee, PLAN_MONTHS.get(m.plan, 1))
            days_left = (expiry - today).days
            if m.payment_done and m.last_fee_date == today_str:
                stats['paid_count'] += 1
                stats['paid_revenue'] += m.fees
                stats['paid_today_count'] += 1
                stats['paid_today_revenue'] += m.fees
            elif days_left <= 0:
                stats['unpaid_count'] += 1
                stats['unpaid_revenue'] += m.fees
                stats['expired_members'] += 1
            else:
                stats['active_members'] += 1
            stats['total_revenue'] += m.fees
        except Exception:
            continue
    return stats


def require_login():
    return "user" not in session


# ---------------- LOGIN / LOGOUT ----------------
SITE_DIR = os.path.join(BASE_DIR, "site")


def photo_src(m):
    """Best picture address for a member: GitHub photo (via this app), else Google picture."""
    if m.photo_path:
        return url_for("member_photo", id=m.id, v=m.photo_path[-14:])
    return m.photo_url or m.picture_url or ""


app.jinja_env.globals["photo_src"] = photo_src


@app.route("/member-photo/<int:id>")
def member_photo(id):
    """Serves a member's GitHub-stored photo. Works even if the GitHub repo is private."""
    if "user" not in session and "client_id" not in session:
        abort(403)
    m = Member.query.get_or_404(id)
    data, ctype = github_storage.fetch_photo(m.photo_path)
    if not data:
        abort(404)
    resp = make_response(data)
    resp.headers["Content-Type"] = ctype
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.route("/")
def home():
    """The public website (site/index.html) is the first page everyone sees."""
    return send_from_directory(SITE_DIR, "index.html")


@app.route("/photos/<path:filename>")
def site_photos(filename):
    return send_from_directory(os.path.join(SITE_DIR, "photos"), filename)


@app.route("/api/announcements")
def api_announcements():
    notes = Announcement.query.filter_by(active=True).order_by(Announcement.id.desc()).limit(3).all()
    return jsonify([{"title": a.title, "body": a.body} for a in notes])


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        password = os.environ.get('ADMIN_PASSWORD', 'admin123')
        if request.form.get("username") == username and request.form.get("password") == password:
            session["user"] = username
            return redirect("/admin")
        return render_template("login.html", error="Invalid credentials!")
    if "user" in session:
        return redirect("/admin")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/admin/login")


# ---------------- DASHBOARD ----------------
@app.route("/admin")
@app.route("/dashboard")
def dashboard():
    if require_login():
        return redirect("/admin/login")
    return render_template("dashboard.html", stats=calculate_revenue_stats())


@app.route("/api/revenue")
def api_revenue():
    if require_login():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(calculate_revenue_stats())


# ---------------- ADD MEMBER ----------------
@app.route("/add", methods=["GET", "POST"])
def add_member():
    if require_login():
        return redirect("/admin/login")
    if request.method == "POST":
        member = Member(
            name=request.form["name"].strip(),
            phone=request.form["phone"].strip(),
            fees=int(request.form["fees"] or 0),
            joining_date=request.form["joining_date"],
            last_fee_date=request.form["last_fee_date"],
            plan=request.form["plan"],
        )
        db.session.add(member)
        db.session.commit()  # commit first to get member.id for the photo filename

        photo = request.files.get("photo")
        if photo and photo.filename:
            if github_storage.is_configured():
                url_, path_ = github_storage.upload_photo(photo, member.id)
                if url_:
                    member.photo_url, member.photo_path = url_, path_
                    db.session.commit()
                else:
                    flash("Member saved, but photo upload failed. Check GitHub settings.", "warning")
            else:
                flash("Member saved without photo — GitHub photo storage isn't configured yet.", "warning")

        return redirect("/members")
    return render_template("add_member.html", plan_fees=PLAN_FEES)


# ---------------- EDIT MEMBER ----------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_member(id):
    if require_login():
        return redirect("/admin/login")
    m = Member.query.get_or_404(id)
    if request.method == "POST":
        m.name = request.form["name"].strip()
        m.phone = request.form["phone"].strip()
        m.fees = int(request.form["fees"] or 0)
        m.plan = request.form["plan"]
        m.joining_date = request.form["joining_date"]
        m.last_fee_date = request.form["last_fee_date"]

        photo = request.files.get("photo")
        if photo and photo.filename and github_storage.is_configured():
            if m.photo_path:
                github_storage.delete_photo(m.photo_path)
            url_, path_ = github_storage.upload_photo(photo, m.id)
            if url_:
                m.photo_url, m.photo_path = url_, path_

        db.session.commit()
        return redirect("/members")
    return render_template("edit_member.html", m=m, plan_fees=PLAN_FEES)


# ---------------- MARK PAID ----------------
@app.route("/mark_paid/<int:id>")
def mark_paid(id):
    if require_login():
        return redirect("/admin/login")
    member = Member.query.get_or_404(id)
    member.payment_done = True
    member.last_fee_date = datetime.now().strftime("%Y-%m-%d")
    db.session.commit()
    return redirect("/members")


# ---------------- DELETE MEMBER (only explicit admin action that removes data) ----------------
@app.route("/delete/<int:id>")
def delete(id):
    if require_login():
        return redirect("/admin/login")
    member = Member.query.get(id)
    if member:
        if member.photo_path:
            github_storage.delete_photo(member.photo_path)
        db.session.delete(member)
        db.session.commit()
    return redirect("/members")


# ---------------- VIEW MEMBERS ----------------
@app.route("/members")
def members():
    if require_login():
        return redirect("/admin/login")
    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'all')

    query = Member.query
    if search_query:
        query = query.filter(
            (Member.name.ilike(f'%{search_query}%')) | (Member.phone.ilike(f'%{search_query}%'))
        )
    all_members = query.order_by(Member.id.desc()).all()

    filtered = []
    for m in all_members:
        if m.payment_done and m.last_fee_date != today_str:
            m.payment_done = False
            db.session.commit()
        try:
            last_fee = datetime.strptime(m.last_fee_date, "%Y-%m-%d").date()
            expiry = add_months(last_fee, PLAN_MONTHS.get(m.plan, 1))
            m.days_left = max((expiry - today).days, 0)
            m.expiry_date = expiry.strftime("%d %b %Y")
            m.wa_message = generate_wa_message(m.name, m.fees, m.plan, m.expiry_date, m.id)
        except Exception:
            m.days_left = 0
            m.expiry_date = "N/A"
            m.wa_message = ""

        include = True
        if status_filter == 'paid':
            include = (m.payment_done and m.last_fee_date == today_str)
        elif status_filter in ('pending', 'expired'):
            include = (m.days_left == 0 and not m.payment_done)
        elif status_filter == 'active':
            include = (m.days_left > 0 and not m.payment_done)
        if include:
            filtered.append(m)

    return render_template("members.html", members=filtered, today=today_str,
                            search_query=search_query, status_filter=status_filter)


# ---------------- PENDING (FOR MANUAL WHATSAPP/SMS) ----------------
@app.route("/pending_sms")
def pending_sms():
    if require_login():
        return redirect("/admin/login")
    today = datetime.now().date()
    all_members = Member.query.filter_by(payment_done=False).all()
    pending = []
    for m in all_members:
        try:
            last_fee = datetime.strptime(m.last_fee_date, "%Y-%m-%d").date()
            expiry = add_months(last_fee, PLAN_MONTHS.get(m.plan, 1))
            days_left = (expiry - today).days
            if days_left <= 0:
                m.expiry_date = expiry.strftime("%d %b %Y")
                m.days_overdue = abs(days_left)
                m.wa_message = generate_wa_message(m.name, m.fees, m.plan, m.expiry_date, m.id)
                pending.append(m)
        except Exception:
            continue
    return render_template("pending_sms.html", pending_members=pending, total_pending=len(pending))


@app.route("/send_sms/<int:id>")
def send_sms(id):
    if require_login():
        return redirect("/admin/login")
    member = Member.query.get_or_404(id)
    today = datetime.now().date()
    try:
        last_fee = datetime.strptime(member.last_fee_date, "%Y-%m-%d").date()
        expiry = add_months(last_fee, PLAN_MONTHS.get(member.plan, 1))
        expiry_date = expiry.strftime("%d %b %Y")
    except Exception:
        expiry_date = "N/A"
    message = generate_wa_message(member.name, member.fees, member.plan, expiry_date, member.id)
    wa_link = f"https://wa.me/91{member.phone}?text={quote(message)}"
    return redirect(wa_link)


# ---------------- EXPORT TO EXCEL ----------------
@app.route("/export_members")
def export_members():
    if require_login():
        return redirect("/admin/login")
    import openpyxl
    today = datetime.now().date()
    all_members = Member.query.all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Members"
    ws.append(["#", "Name", "Phone", "Plan", "Fees (Rs)", "Joining Date",
               "Last Fee Submit Date", "Expiry Date", "Days Left", "Status", "Payment Done"])
    for idx, m in enumerate(all_members, start=1):
        try:
            last_fee = datetime.strptime(m.last_fee_date, "%Y-%m-%d").date()
            expiry = add_months(last_fee, PLAN_MONTHS.get(m.plan, 1))
            days_left = (expiry - today).days
            expiry_str = expiry.strftime("%d %b %Y")
        except Exception:
            days_left, expiry_str = 0, "N/A"
        today_str = today.strftime("%Y-%m-%d")
        status = "Paid Today" if (m.payment_done and m.last_fee_date == today_str) else ("Active" if days_left > 0 else "Expired")
        ws.append([idx, m.name, m.phone, (m.plan or "").replace("_", " ").title(), m.fees,
                   m.joining_date, m.last_fee_date, expiry_str, max(days_left, 0), status,
                   "Yes" if m.payment_done else "No"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      as_attachment=True, download_name="members_export.xlsx")


# ---------------- ANNOUNCEMENTS (admin) ----------------
@app.route("/admin/announcements", methods=["GET", "POST"])
def admin_announcements():
    if require_login():
        return redirect("/admin/login")
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        body = request.form.get("body", "").strip()[:2000]
        if title and body:
            db.session.add(Announcement(title=title, body=body))
            db.session.commit()
            flash("Announcement published. Members will see it on their page.", "success")
        else:
            flash("Please fill in both the title and the message.", "danger")
        return redirect(url_for("admin_announcements"))
    items = Announcement.query.order_by(Announcement.id.desc()).all()
    return render_template("admin_announcements.html", items=items)


@app.route("/admin/announcements/<int:id>/toggle")
def announcement_toggle(id):
    if require_login():
        return redirect("/admin/login")
    a = Announcement.query.get_or_404(id)
    a.active = not a.active
    db.session.commit()
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:id>/delete")
def announcement_delete(id):
    if require_login():
        return redirect("/admin/login")
    a = Announcement.query.get_or_404(id)
    db.session.delete(a)
    db.session.commit()
    return redirect(url_for("admin_announcements"))


# ---------------- ATTENDANCE QR (admin) ----------------
@app.route("/admin/qr")
def admin_qr():
    if require_login():
        return redirect("/admin/login")
    key = os.environ.get("GYM_QR_KEY", "")
    link = f"{request.url_root.rstrip('/')}/checkin?k={key}"
    return render_template("admin_qr.html", link=link, key_set=bool(key))


@app.route("/admin/qr.png")
def admin_qr_png():
    if require_login():
        return redirect("/admin/login")
    import qrcode
    link = f"{request.url_root.rstrip('/')}/checkin?k={os.environ.get('GYM_QR_KEY', '')}"
    buf = io.BytesIO()
    qrcode.make(link, box_size=14, border=3).save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name="gym-qr.png")


# ---------------- SETUP CHECK (admin) ----------------
@app.route("/admin/setup-check")
def admin_setup_check():
    if require_login():
        return redirect("/admin/login")
    import notify
    root = request.url_root.rstrip("/")
    env = os.environ.get
    checks = [
        ("Database", "sqlite" not in db_url,
         "Postgres in use." if "sqlite" not in db_url else
         "Using local SQLite. Fine for testing, but on Render the data is wiped on every redeploy. Set DATABASE_URL to a Neon Postgres string."),
        ("SECRET_KEY", env("SECRET_KEY", "change-this-secret-key") != "change-this-secret-key",
         "Set." if env("SECRET_KEY", "change-this-secret-key") != "change-this-secret-key" else "Still the default. Set a long random value."),
        ("Admin password", env("ADMIN_PASSWORD", "admin123") != "admin123",
         "Changed from default." if env("ADMIN_PASSWORD", "admin123") != "admin123" else "Still admin123. Set ADMIN_PASSWORD."),
        ("Google login", bool(env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET")),
         "Client ID and secret are set." if (env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET")) else "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing."),
        ("Photo storage (GitHub)", github_storage.is_configured(),
         "GITHUB_TOKEN and GITHUB_REPO set." if github_storage.is_configured() else "GITHUB_TOKEN / GITHUB_REPO missing. Photos will not upload."),
        ("Telegram alerts", notify.is_configured(),
         "Token and chat id set. Use the test button below." if notify.is_configured() else "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing."),
        ("Attendance QR key", bool(env("GYM_QR_KEY")),
         "Set." if env("GYM_QR_KEY") else "GYM_QR_KEY is empty. Anyone could mark attendance."),
        ("HTTPS", root.startswith("https://") or "localhost" in root,
         "Site is on HTTPS (needed for the camera scanner)." if root.startswith("https://") else
         ("Local testing: camera works on localhost." if "localhost" in root else "Site is on plain http. Camera scanning and Google login need https.")),
    ]
    return render_template("admin_setup_check.html", checks=checks,
                           redirect_uri=f"{root}/auth/google/callback", origin=root)


# ---------------- HEALTH CHECK ----------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


import client_routes
import payments
payments.register(app, db, Member, Payment, require_login, PLAN_MONTHS, add_months)
client_routes.register(app, db, Member, Attendance, Announcement, require_login, PLAN_MONTHS, PLAN_FEES, add_months)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
