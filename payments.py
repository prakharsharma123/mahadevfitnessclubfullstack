"""UPI fee payments: tokenised link -> QR page -> UTR -> admin confirms -> member marked paid."""
import hmac, hashlib, os, io, re, secrets
from datetime import datetime, timedelta
from urllib.parse import quote
from flask import render_template, request, redirect, url_for, abort, jsonify, send_file, current_app, flash
import notify


def make_ref(member_id):
    """Link id like 12-a8f3k29dq1x4. Contains the member id plus a signature nobody can guess."""
    sig = hmac.new(current_app.secret_key.encode(), f"pay:{member_id}".encode(), hashlib.sha256).hexdigest()[:12]
    return f"{member_id}-{sig}"


def pay_url(member_id):
    return request.url_root.rstrip("/") + url_for("payment_page", ref=make_ref(member_id))


def register(app, db, Member, Payment, require_login, PLAN_MONTHS, add_months):
    UPI_ID = os.environ.get("UPI_ID", "ashishrajsngh@ybl")
    UPI_NAME = os.environ.get("UPI_NAME", "Mahadev Fitness Club")
    WINDOW = int(os.environ.get("PAY_WINDOW_MIN", "5"))
    AUTO_APPROVE = os.environ.get("AUTO_APPROVE_UTR", "0") == "1"

    def member_from_ref(ref):
        try:
            mid = int(ref.split("-", 1)[0])
        except ValueError:
            abort(404)
        if not hmac.compare_digest(make_ref(mid), ref):
            abort(404)
        return Member.query.get_or_404(mid)

    def ist_today():
        return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

    def upi_link(p):
        return (f"upi://pay?pa={UPI_ID}&pn={quote(UPI_NAME)}&am={p.amount:.2f}&cu=INR"
                f"&tn={quote('Gym fees ' + p.order_id)}&tr={p.order_id}")

    def new_payment(m):
        if not m.fees or m.fees <= 0:
            abort(400)
        now = datetime.utcnow()
        p = Payment(member_id=m.id, amount=m.fees, status="pending", attempts=0, created_at=now,
                    expires_at=now + timedelta(minutes=WINDOW),
                    order_id="MFC" + (now + timedelta(hours=5, minutes=30)).strftime("%y%m%d") + secrets.token_hex(3).upper())
        db.session.add(p)
        db.session.commit()
        return p

    def current_payment(m):
        now = datetime.utcnow()
        for old in Payment.query.filter_by(member_id=m.id, status="pending").all():
            if old.expires_at <= now:
                old.status = "expired"
        db.session.commit()
        p = Payment.query.filter_by(member_id=m.id).order_by(Payment.id.desc()).first()
        if p and (p.status in ("pending", "submitted", "expired", "rejected")
                  or (p.status == "paid" and p.paid_at and (now - p.paid_at).total_seconds() < 900)):
            return p
        return new_payment(m)

    def secs_left(p):
        return max(int((p.expires_at - datetime.utcnow()).total_seconds()), 0) if p.status == "pending" else 0

    def finish(m, p, how):
        m.payment_done = True
        m.last_fee_date = ist_today()
        p.status, p.paid_at = "paid", datetime.utcnow()
        db.session.commit()
        notify.notify_owner(f"✅ Fee marked PAID ({how})\n{m.name} | 📞 {m.phone}\n₹{p.amount} | UTR {p.utr}\nOrder {p.order_id}")

    # ------------------------------------------------------------ member side
    @app.route("/<ref>/payment")
    def payment_page(ref):
        m = member_from_ref(ref)
        p = current_payment(m)
        return render_template("payment.html", m=m, p=p, ref=ref, upi_id=UPI_ID, upi_name=UPI_NAME,
                               link=upi_link(p), secs=secs_left(p), window=WINDOW * 60,
                               tries_left=max(3 - (p.attempts or 0), 0), first=m.name.split()[0])

    @app.route("/<ref>/payment/qr.png")
    def payment_qr(ref):
        import qrcode
        p = current_payment(member_from_ref(ref))
        buf = io.BytesIO()
        qrcode.make(upi_link(p), box_size=9, border=2).save(buf, format="PNG")
        buf.seek(0)
        resp = send_file(buf, mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/<ref>/payment/status")
    def payment_status(ref):
        p = current_payment(member_from_ref(ref))
        return jsonify(status=p.status, seconds=secs_left(p))

    @app.route("/<ref>/payment/utr", methods=["POST"])
    def payment_utr(ref):
        m = member_from_ref(ref)
        p = current_payment(m)
        utr = re.sub(r"\D", "", request.form.get("utr", ""))
        if p.status != "pending":
            flash("This payment session is no longer open.", "danger")
        elif (p.attempts or 0) >= 3:
            flash("Too many attempts. Please contact the gym.", "danger")
        elif len(utr) != 12:
            p.attempts = (p.attempts or 0) + 1
            db.session.commit()
            flash("The UTR must be exactly 12 digits.", "danger")
        elif Payment.query.filter(Payment.utr == utr, Payment.id != p.id, Payment.status.in_(("submitted", "paid"))).first():
            p.attempts = (p.attempts or 0) + 1
            db.session.commit()
            flash("This UTR was already used. Check the number in your UPI app.", "danger")
        else:
            p.utr, p.status, p.submitted_at = utr, "submitted", datetime.utcnow()
            db.session.commit()
            if AUTO_APPROVE:
                finish(m, p, "auto, please verify in your bank app")
            else:
                notify.notify_owner(f"💰 Fee payment submitted\n{m.name} | 📞 {m.phone}\n₹{p.amount} | UTR {utr}\n"
                                    f"Check your bank app, then confirm: {request.url_root}admin/payments")
        return redirect(url_for("payment_page", ref=ref))

    @app.route("/<ref>/payment/new", methods=["POST"])
    def payment_new(ref):
        m = member_from_ref(ref)
        p = current_payment(m)
        if p.status in ("expired", "rejected"):
            new_payment(m)
        return redirect(url_for("payment_page", ref=ref))

    # ------------------------------------------------------------ admin side
    @app.route("/admin/payments")
    def admin_payments():
        if require_login():
            return redirect("/admin/login")
        waiting = Payment.query.filter_by(status="submitted").order_by(Payment.id.desc()).all()
        recent = Payment.query.filter(Payment.status != "submitted").order_by(Payment.id.desc()).limit(30).all()
        names = {x.id: x for x in Member.query.filter(Member.id.in_([p.member_id for p in waiting + recent])).all()}
        return render_template("admin_payments.html", waiting=waiting, recent=recent, names=names, auto=AUTO_APPROVE, upi_id=UPI_ID)

    @app.route("/admin/payments/<int:pid>/<action>", methods=["POST"])
    def admin_payment_action(pid, action):
        if require_login():
            return redirect("/admin/login")
        p = Payment.query.get_or_404(pid)
        m = Member.query.get_or_404(p.member_id)
        if p.status == "submitted" and action == "confirm":
            finish(m, p, "confirmed by owner")
            flash(f"{m.name} marked as paid.", "success")
        elif p.status == "submitted" and action == "reject":
            p.status = "rejected"
            db.session.commit()
            flash("Payment rejected. The member can try again.", "warning")
        return redirect(url_for("admin_payments"))
