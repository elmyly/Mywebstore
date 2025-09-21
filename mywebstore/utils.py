import json
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from typing import Iterable, List

from flask import redirect, request, session, url_for
from werkzeug.utils import secure_filename

from .config import ALLOWED_EXTENSIONS


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def slugify(text: str) -> str:
    import re

    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def price_to_cents(price_str: str) -> int:
    try:
        return int(round(float(price_str) * 100))
    except Exception:
        return 0


def cents_to_price(cents: int) -> str:
    try:
        return f"MAD {cents/100:,.2f}"
    except Exception:
        return "MAD 0.00"


def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def save_uploaded_images(files: Iterable, upload_dir: str) -> List[str]:
    saved: List[str] = []
    for file in files:
        if not file or file.filename == "":
            continue
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            name, ext = os.path.splitext(filename)
            unique = f"{name}-{secrets.token_hex(4)}{ext}"
            path = os.path.join(upload_dir, unique)
            file.save(path)
            saved.append(f"uploads/{unique}")
    return saved


def effective_price_cents(row_or_dict) -> int:
    try:
        if isinstance(row_or_dict, (dict, sqlite3.Row)):
            price = int(row_or_dict["price_cents"])
            discount = row_or_dict.get("discount_cents") if isinstance(row_or_dict, dict) else row_or_dict["discount_cents"]
        else:
            price = int(row_or_dict)
            discount = None
        if (
            discount is not None
            and isinstance(discount, (int, float))
            and discount > 0
            and discount < price
        ):
            return int(discount)
        return int(price)
    except Exception:
        try:
            return int(row_or_dict["price_cents"])  # type: ignore[index]
        except Exception:
            return 0


__all__ = [
    "allowed_file",
    "slugify",
    "login_required",
    "price_to_cents",
    "cents_to_price",
    "now_utc_str",
    "save_uploaded_images",
    "effective_price_cents",
]
