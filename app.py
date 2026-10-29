from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import secrets
import time
import qrcode
from zoneinfo import ZoneInfo
import uuid
import io
import re
import csv
import zipfile
from flask_mail import Mail, Message
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from io import BytesIO
from flask import send_file
from flask import url_for
from datetime import datetime, timezone, timedelta
from flask import abort
from flask_migrate import Migrate

load_dotenv()
app = Flask(__name__)


app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY is missing. Check your .env file.")

csrf = CSRFProtect(app)
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")
mail = Mail(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tagbandhu.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

migrate = Migrate(app, db)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Unique ID printed on the physical tag
    tag_code = db.Column(db.String(64), unique=True, nullable=False)

    # elderly, child, luggage, everyday
    tag_type = db.Column(db.String(30), nullable=False)

    # No owner until a customer activates the tag
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    # Inventory tags start inactive
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    activated_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship("User", backref=db.backref("tags", lazy=True))


class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    tag_id = db.Column(db.Integer, db.ForeignKey("tag.id"), nullable=False)

    sender_name = db.Column(db.String(100), nullable=False)
    sender_phone = db.Column(db.String(20), nullable=True, default="")
    sender_email = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)

    is_read = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    tag = db.relationship("Tag", backref=db.backref("messages", lazy=True))


class TagActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    tag_id = db.Column(
        db.Integer,
        db.ForeignKey("tag.id"),
        nullable=False
    )

    action = db.Column(db.String(30), nullable=False)
    details = db.Column(db.String(255), nullable=True, default="")

    created_at = db.Column(
    db.DateTime,
    nullable=False,
    default=lambda: datetime.now(ZoneInfo("Asia/Kolkata"))
)

    tag = db.relationship(
        "Tag",
        backref=db.backref("activity_history", lazy=True)
    )

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access your dashboard.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


@app.route("/test-email")
@login_required
def test_email():
    recipient = session.get("user_email")

    if not recipient:
        return "User email not found in session.", 400

    try:
        msg = Message(
            subject="Tagbandhu Email Test",
            recipients=[recipient],
            body="Your Tagbandhu email notification setup is working.",
        )
        mail.send(msg)
        return "Test email sent successfully!"
    except Exception:
        app.logger.exception("Tagbandhu test email failed.")
        return "Email failed. Check the Flask terminal logs.", 500


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped_view


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin_key = os.environ.get("TAGBANDHU_ADMIN_KEY")
        submitted_key = request.form.get("admin_key", "")

        if not admin_key:
            app.logger.error("TAGBANDHU_ADMIN_KEY is not configured.")
            abort(503, description="Admin functionality is not configured.")

        if not secrets.compare_digest(submitted_key, admin_key):
            flash("Invalid admin key.")
            return redirect(url_for("admin_login"))

        session["is_admin"] = True
        return redirect(url_for("admin_inventory"))

    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.")
    return redirect(url_for("admin_login"))


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/products")
def products():
    return render_template("products.html")


@app.route("/scan/<tag_code>")
def scan_tag(tag_code):
    tag = db.session.scalar(db.select(Tag).filter_by(tag_code=tag_code))

    if not tag or not tag.is_active:
        return render_template("scan.html", tag=None), 404

    return render_template("scan.html", tag=tag)


@app.route("/tag-qr/<tag_code>")
def tag_qr(tag_code):
    tag = db.session.scalar(db.select(Tag).filter_by(tag_code=tag_code, is_active=True))

    if not tag:
        abort(404, description="Tag not found or inactive.")


    base_url = os.environ.get(
        "BASE_URL",
        "http://10.75.90.87:5000"
    ).rstrip("/")

    scan_url = base_url + url_for(
        "scan_tag",
        tag_code=tag_code
    )

    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(scan_url)
    qr.make(fit=True)

    qr_image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    image_buffer = BytesIO()
    qr_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    return send_file(image_buffer, mimetype="image/png")


# Local development only: temporary OTP storage
otp_store = {}


@app.route("/request-otp", methods=["POST"])
def request_otp():
    phone = request.form.get("phone", "").strip()

    if not re.fullmatch(r"[6-9][0-9]{9}", phone):
        return {
            "success": False,
            "message": "Enter a valid 10-digit mobile number.",
        }, 400

    otp = str(secrets.randbelow(900000) + 100000)

    # Give this browser session its own OTP storage key
    if "otp_session_id" not in session:
        session["otp_session_id"] = secrets.token_urlsafe(32)

    otp_key = session["otp_session_id"] + ":" + phone

    existing_record = otp_store.get(otp_key)

    if existing_record and time.time() < existing_record.get("resend_after", 0):
        return {
            "success": False,
            "message": "Please wait 60 seconds before requesting another OTP.",
        }, 429

    otp_store[otp_key] = {
        "otp": otp,
        "expires": time.time() + 300,
        "attempts": 0,
        "verified": False,
        "resend_after": time.time() + 60,
    }

    # Local testing only. Never expose OTPs in production logs.
    app.logger.warning("TEST OTP for %s: %s", phone, otp)

    return {
        "success": True,
        "message": "Test OTP generated. Check the VS Code terminal.",
    }


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    phone = request.form.get("phone", "").strip()
    entered_otp = request.form.get("otp", "").strip()

    session_id = session.get("otp_session_id")

    if not session_id:
        return {"success": False, "message": "Request a new OTP."}, 400

    otp_key = session_id + ":" + phone
    record = otp_store.get(otp_key)

    if not record or time.time() > record["expires"]:
        otp_store.pop(otp_key, None)
        return {"success": False, "message": "OTP expired. Request a new one."}, 400

    if record["attempts"] >= 5:
        otp_store.pop(otp_key, None)
        return {
            "success": False,
            "message": "Too many attempts. Request a new OTP.",
        }, 429

    record["attempts"] += 1

    if not secrets.compare_digest(record["otp"], entered_otp):
        return {"success": False, "message": "Incorrect OTP. Try again."}, 400

    record["verified"] = True

    return {"success": True, "message": "Phone number verified successfully."}


@app.route("/contact/<tag_code>", methods=["POST"])
def send_contact_message(tag_code):
    tag = db.session.scalar(db.select(Tag).filter_by(tag_code=tag_code, is_active=True))

    if not tag:
        return "Tag not found or inactive.", 404

    sender_name = request.form.get("sender_name", "").strip()
    sender_phone = request.form.get("sender_phone", "").strip()
    sender_email = request.form.get("sender_email", "").strip().lower()
    message = request.form.get("message", "").strip()

    # Check required fields
    if not sender_name or not sender_email or not sender_phone or not message:
        flash("Please fill in all contact form fields.")
        return redirect(url_for("scan_tag", tag_code=tag_code))

    # Validate Indian mobile number format
    if not re.fullmatch(r"[6-9][0-9]{9}", sender_phone):
        flash("Please enter a valid 10-digit Indian mobile number.")
        return redirect(url_for("scan_tag", tag_code=tag_code))

    # Require successful OTP verification

    # Require OTP verification for this session and phone number
    session_id = session.get("otp_session_id")
    otp_key = f"{session_id}:{sender_phone}" if session_id else None
    otp_record = otp_store.get(otp_key) if otp_key else None

    if (
        not otp_record
        or not otp_record.get("verified")
        or time.time() > otp_record.get("expires", 0)
    ):
        flash("Please verify your mobile number with OTP first.")
        return redirect(url_for("scan_tag", tag_code=tag_code))

    # Check length limits
    if len(sender_name) > 100 or len(sender_email) > 120 or len(message) > 2000:
        flash("Please keep your details and message within the allowed limits.")
        return redirect(url_for("scan_tag", tag_code=tag_code))

    contact_message = ContactMessage(
        tag_id=tag.id,
        sender_name=sender_name,
        sender_phone=sender_phone,
        sender_email=sender_email,
        message=message,
        created_at=datetime.now(timezone.utc),
    )

    db.session.add(contact_message)
    db.session.commit()
    # Send an email notification to the tag owner


    # Send an email notification to the tag owner
    try:
        owner = tag.owner

        if owner and owner.email:
            email_body = f"""
Hello {owner.name},

Someone has sent you a message through your Tagbandhu tag.

Sender name: {contact_message.sender_name}
Sender email: {contact_message.sender_email}
Sender phone: {contact_message.sender_phone or 'Not provided'}

Message:
{contact_message.message}

Tag type: {tag.tag_type}
Tag ID: {tag.tag_code[:8]}

Please log in to your Tagbandhu dashboard to view your messages.

Regards,
Tagbandhu
"""

            email = Message(
                subject="New message received - Tagbandhu",
                recipients=[owner.email],
                body=email_body,
            )

            mail.send(email)

    except Exception:
        app.logger.exception(
            "Message saved, but owner email notification failed."
        )

    otp_store.pop(otp_key, None)

    flash("Your message has been sent to the item owner.")
    return redirect(url_for("scan_tag", tag_code=tag_code))

@app.route("/admin/inventory")
@admin_required


def admin_inventory():
    tags = Tag.query.order_by(Tag.id.asc()).all()

    total_tags = len(tags)
    available_tags = sum(
        1 for tag in tags
        if tag.owner_id is None and not tag.is_active
    )
    activated_tags = sum(
        1 for tag in tags
        if tag.owner_id is not None and tag.is_active
    )

    return render_template(
        "admin_inventory.html",
        tags=tags,
        total_tags=total_tags,
        available_tags=available_tags,
        activated_tags=activated_tags,
    )


@app.route("/admin/activity-history")
@admin_required
def admin_activity_history():
    activities = TagActivity.query.order_by(
        TagActivity.created_at.desc()
    ).all()

    return render_template(
        "admin_activity_history.html",
        activities=activities
    )

@app.route("/admin/tag/<int:tag_id>/deactivate", methods=["POST"])
@admin_required
def admin_deactivate_tag(tag_id):
    tag = db.session.get(Tag, tag_id)

    if tag is None:
        abort(404)

    if tag.owner_id is None:
        flash("This tag has no owner. It is already unavailable for activation.")
        return redirect(url_for("admin_inventory"))

    if not tag.is_active:
        flash("This tag is already deactivated.")
        return redirect(url_for("admin_inventory"))

    tag.is_active = False

    db.session.add(TagActivity(
        tag_id=tag.id,
        action="deactivated",
        details="Tag deactivated by admin",
        created_at=datetime.now(ZoneInfo("Asia/Kolkata"))
    ))

    db.session.commit()

    flash(f"Tag #{tag.id} has been deactivated.")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/tag/<int:tag_id>/reactivate", methods=["POST"])
@admin_required
def admin_reactivate_tag(tag_id):
    tag = db.session.get(Tag, tag_id)

    if tag is None:
        abort(404)

    if tag.owner_id is None:
        flash("This tag has no owner and cannot be reactivated.")
        return redirect(url_for("admin_inventory"))

    if tag.is_active:
        flash("This tag is already active.")
        return redirect(url_for("admin_inventory"))

    tag.is_active = True

    db.session.add(TagActivity(
        tag_id=tag.id,
        action="reactivated",
        details="Tag reactivated by admin",
        created_at=datetime.now(ZoneInfo("Asia/Kolkata"))
    ))

    db.session.commit()

    flash(f"Tag #{tag.id} has been reactivated.")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/generate-tags", methods=["POST"])
@admin_required
def generate_inventory_tags():

    tag_type = request.form.get("tag_type", "").strip().lower()

    try:
        quantity = int(request.form.get("quantity", "0"))
    except (ValueError, TypeError):
        abort(400, description="Quantity must be a number.")

    allowed_types = {"elderly", "child", "luggage", "everyday"}

    if tag_type not in allowed_types:
        abort(400, description="Invalid tag type.")

    if not 1 <= quantity <= 100:
        abort(400, description="Generate between 1 and 100 tags per batch.")

    new_tags = []

    try:
        for _ in range(quantity):
            tag = Tag(
                tag_code=uuid.uuid4().hex,
                tag_type=tag_type,
                owner_id=None,
                is_active=False,
            )
            db.session.add(tag)
            new_tags.append(tag)

        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Inventory tag generation failed.")
        abort(500, description="Unable to generate inventory tags.")

    flash(f"{len(new_tags)} inventory tags generated successfully.")
    return redirect(url_for("admin_inventory"))


@app.route("/admin/export-tags")
@admin_required
def export_inventory_tags():
    tags = (
        Tag.query.filter_by(owner_id=None, is_active=False).order_by(Tag.id.asc()).all()
    )

    text_output = io.StringIO()
    writer = csv.writer(text_output)

    writer.writerow(["Tag ID", "Tag Code", "Tag Type", "Status"])

    for tag in tags:
        writer.writerow(
            [tag.id, tag.tag_code, tag.tag_type, "Available for activation"]
        )

    csv_bytes = BytesIO(text_output.getvalue().encode("utf-8-sig"))
    csv_bytes.seek(0)

    return send_file(
        csv_bytes,
        mimetype="text/csv",
        as_attachment=True,
        download_name="tagbandhu_inventory.csv",
    )


@app.route("/admin/print-tags")
@admin_required
def print_inventory_tags():
    tags = (
        Tag.query.filter_by(owner_id=None, is_active=False).order_by(Tag.id.asc()).all()
    )

    if not tags:
        return "No available inventory tags found.", 404

    base_url = os.environ.get(
    "BASE_URL",
    "http://10.75.90.87:5000"
).rstrip("/")
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    page_width, page_height = A4

    margin = 35
    cell_width = (page_width - 2 * margin) / 2
    cell_height = 190

    for index, tag in enumerate(tags):
        position = index % 4

        if index > 0 and position == 0:
            pdf.showPage()

        col = position % 2
        row = position // 2
        x = margin + col * cell_width
        y = page_height - margin - (row + 1) * cell_height

        qr = qrcode.QRCode(box_size=8, border=3)
        qr.add_data(f"{base_url}/scan/{tag.tag_code}")
        qr.make(fit=True)

        qr_image = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = BytesIO()
        qr_image.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        image_size = 105

        pdf.drawImage(
            ImageReader(qr_buffer),
            x + (cell_width - image_size) / 2,
            y + 55,
            width=image_size,
            height=image_size,
        )

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(
            x + cell_width / 2, y + 40, f"Tag ID: {tag.id} | {tag.tag_type.title()}"
        )

        pdf.setFont("Helvetica", 7)
        pdf.drawCentredString(x + cell_width / 2, y + 27, f"Code: {tag.tag_code}")

        pdf.rect(x + 5, y + 10, cell_width - 10, cell_height - 20)

    pdf.save()
    output.seek(0)

    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="tagbandhu_qr_print_sheet.pdf",
    )


def get_email_typo_suggestion(email):
    """Suggest corrections for common email domain typos."""
    parts = email.strip().lower().rsplit("@", 1)

    if len(parts) != 2:
        return None

    domain_typos = {
        "gamil.com": "gmail.com",
        "gamil.in": "gmail.com",
        "gmial.com": "gmail.com",
        "gmail.con": "gmail.com",
        "gmai.com": "gmail.com",
        "hotnail.com": "hotmail.com",
        "yaho.com": "yahoo.com",
    }

    corrected_domain = domain_typos.get(parts[1])

    if corrected_domain:
        return f"{parts[0]}@{corrected_domain}"

    return None

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        consent = request.form.get("consent")

        # Reject common email domain typos
        suggested_email = get_email_typo_suggestion(email)

        if suggested_email:
            flash(
                f"Please check your email address. Did you mean {suggested_email}?",
                "error"
            )
            return redirect(url_for("register"))

        if not name or not phone or not email or not password:
            flash("Please fill in all required fields.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters long.")
            return redirect(url_for("register"))

        if not consent:
            flash("Please agree to the terms and privacy policy.")
            return redirect(url_for("register"))

        existing_user = db.session.scalar(db.select(User).filter_by(email=email))

        if existing_user:
            flash("An account with this email already exists.")
            return redirect(url_for("register"))

        user = User(
            name=name,
            phone=phone,
            email=email,
            password_hash=generate_password_hash(password),
        )

        db.session.add(user)
        db.session.commit()

        flash("Account created successfully. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.session.scalar(db.select(User).filter_by(email=email))

        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name
            session["user_email"] = user.email
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    user_tags = db.session.scalars(
        db.select(Tag).filter_by(owner_id=session["user_id"]).order_by(Tag.id.desc())
    ).all()

    received_messages = db.session.scalars(
        db.select(ContactMessage)
        .join(Tag)
        .filter(Tag.owner_id == session["user_id"])
        .order_by(ContactMessage.id.desc())
    ).all()

    unread_count = sum(1 for msg in received_messages if not msg.is_read)

    total_tags = len(user_tags)
    active_tags = sum(1 for tag in user_tags if tag.is_active)

    return render_template(
        "dashboard.html",
        name=session.get("user_name"),
        tags=user_tags,
        received_messages=received_messages,
        unread_count=unread_count,
        total_tags=total_tags,
        active_tags=active_tags,
        timedelta=timedelta,
    )


@app.route("/activate-tag", methods=["POST"])
@login_required

def activate_tag():
    tag_code = request.form.get("tag_code", "").strip()

    if not tag_code:
        flash("Please enter your tag code.")
        return redirect(url_for("dashboard"))

    result = db.session.execute(
        db.update(Tag)
        .where(
            Tag.tag_code == tag_code,
            Tag.owner_id.is_(None),
            Tag.is_active.is_(False)
        )
        .values(
            owner_id=session["user_id"],
            is_active=True,
            activated_at=datetime.now(timezone.utc),
        )
    )

    if result.rowcount != 1:
        db.session.rollback()
        flash("Tag code is invalid or has already been activated.")
        return redirect(url_for("dashboard"))

    tag = db.session.scalar(
        db.select(Tag).filter_by(tag_code=tag_code)
    )

    if tag is None:
        db.session.rollback()
        flash("Tag could not be found. Please try again.")
        return redirect(url_for("dashboard"))

    db.session.add(TagActivity(
        tag_id=tag.id,
        action="activated",
        details="Tag activated by customer",
        created_at=datetime.now(ZoneInfo("Asia/Kolkata"))
    ))

    db.session.commit()
    flash("Your tag has been activated successfully!")
    return redirect(url_for("dashboard"))


@app.route("/my-tag/<int:tag_id>/deactivate", methods=["POST"])
@login_required
def customer_deactivate_tag(tag_id):
    tag = db.session.scalar(
        db.select(Tag).where(
            Tag.id == tag_id,
            Tag.owner_id == session["user_id"]
        )
    )

    if tag is None:
        abort(404)

    if not tag.is_active:
        flash("This tag is already deactivated.")
        return redirect(url_for("dashboard"))

    tag.is_active = False

    db.session.add(TagActivity(
        tag_id=tag.id,
        action="deactivated",
        details="Tag deactivated by customer",
        created_at=datetime.now(ZoneInfo("Asia/Kolkata"))
    ))

    db.session.commit()

    flash("Your tag has been deactivated successfully.")
    return redirect(url_for("dashboard"))



@app.route("/my-tag/<int:tag_id>/reactivate", methods=["POST"])
@login_required
def customer_reactivate_tag(tag_id):
    tag = db.session.scalar(
        db.select(Tag).where(
            Tag.id == tag_id,
            Tag.owner_id == session["user_id"]
        )
    )

    if tag is None:
        abort(404)

    if tag.is_active:
        flash("This tag is already active.")
        return redirect(url_for("dashboard"))

    tag.is_active = True

    db.session.add(TagActivity(
        tag_id=tag.id,
        action="reactivated",
        details="Tag reactivated by customer",
        created_at=datetime.now(ZoneInfo("Asia/Kolkata"))
    ))

    db.session.commit()

    flash("Your tag has been reactivated successfully.")
    return redirect(url_for("dashboard"))


@app.route("/mark-message-read/<int:message_id>", methods=["POST"])
@login_required
def mark_message_read(message_id):
    contact_message = db.session.scalar(
        db.select(ContactMessage)
        .join(Tag)
        .filter(ContactMessage.id == message_id, Tag.owner_id == session["user_id"])
    )

    if not contact_message:
        flash("Message not found.")
        return redirect(url_for("dashboard"))

    if contact_message.is_read:
        flash("This message has already been marked as read.")
    else:
        contact_message.is_read = True
        db.session.commit()
        flash("Message marked as read.")

    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("home"))


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
