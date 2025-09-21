import base64
import mimetypes
import os
import re
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Dict, Iterable, Mapping, Optional

from flask import current_app, render_template, url_for

from .config import STATIC_DIR

from .database import get_db, release_db
from .utils import now_utc_str

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    return EMAIL_RE.match(email.strip().lower()) is not None


def add_subscriber(app, email: str) -> bool:
    email = email.strip().lower()
    if not is_valid_email(email):
        return False
    conn = get_db(app)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO newsletter_subscribers (email, created_at) VALUES (?, ?)",
            (email, now_utc_str()),
        )
        conn.commit()
        cur.execute("SELECT changes()")
        changed = cur.fetchone()[0]
        return changed > 0
    finally:
        release_db(conn)


def _gather_recipients(app) -> Iterable[str]:
    conn = get_db(app)
    cur = conn.cursor()
    try:
        cur.execute("SELECT email FROM newsletter_subscribers ORDER BY created_at ASC")
        return [row["email"] for row in cur.fetchall()]
    finally:
        release_db(conn)


def send_new_product_announcement(app, product_row: Mapping[str, object]) -> None:
    sender = app.config.get("NEWSLETTER_FROM_EMAIL")
    password = app.config.get("NEWSLETTER_APP_PASSWORD")
    if password:
        password = password.replace(" ", "")
    sender_name = app.config.get("NEWSLETTER_FROM_NAME", "Bghitha")

    if not sender or not password:
        app.logger.warning("Newsletter credentials missing; skipping announcement email.")
        return

    recipients = list(_gather_recipients(app))
    if not recipients:
        return

    slug = product_row.get("slug") or product_row.get("id")
    product_url = url_for(
        "product_detail",
        pid=product_row.get("id"),
        slug=slug,
        _external=True,
    )

    subject = f"Nouveau produit \u2728 {product_row.get('title', 'Bghitha')}"
    cover: Optional[str] = None
    images = product_row.get("images")
    if images:
        try:
            import json

            parsed = json.loads(images)
            if parsed:
                rel_path = parsed[0]
                abs_path = os.path.join(STATIC_DIR, rel_path)
                if os.path.exists(abs_path):
                    mime, _ = mimetypes.guess_type(abs_path)
                    if mime is None:
                        mime = "image/jpeg"
                    with open(abs_path, "rb") as fp:
                        encoded = base64.b64encode(fp.read()).decode("ascii")
                    cover = f"data:{mime};base64,{encoded}"
                else:
                    cover = url_for("static", filename=rel_path, _external=True)
        except Exception:
            cover = None

    html_body = render_template(
        "emails/new_product.html",
        product=product_row,
        product_url=product_url,
        product_cover_url=cover,
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(sender, password)
            for email in recipients:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = formataddr((sender_name, sender))
                msg["To"] = email
                msg.attach(MIMEText(html_body, "html", "utf-8"))
                server.sendmail(sender, [email], msg.as_string())
        app.logger.info("Sent newsletter announcement for product %s to %d subscribers", product_row.get("title"), len(recipients))
    except Exception as exc:
        app.logger.exception("Failed sending newsletter: %s", exc)


def queue_new_product_email(app, product_row: Mapping[str, object]) -> None:
    sender = app.config.get("NEWSLETTER_FROM_EMAIL")
    password = app.config.get("NEWSLETTER_APP_PASSWORD")
    if not sender or not password:
        return
    data = dict(product_row)

    def _runner():
        with app.app_context():
            base_url = app.config.get("SITE_URL", "http://localhost:5000")
            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
            with app.test_request_context("/", base_url=base_url):
                send_new_product_announcement(app, data)

    threading.Thread(target=_runner, daemon=True).start()


__all__ = [
    "add_subscriber",
    "send_new_product_announcement",
    "queue_new_product_email",
    "is_valid_email",
]
