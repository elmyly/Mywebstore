import json
import os

from flask import g, session, url_for

from ..config import BASE_DIR
from ..database import release_db
from ..services import rating_for, get_top_sellers
from ..utils import cents_to_price, effective_price_cents
from .admin import register_admin_routes
from .public import register_public_routes


def register_routes(app):
    @app.teardown_appcontext
    def close_db(exception):  # type: ignore[unused-variable]
        conn = getattr(g, "_db_conn", None)
        if conn is not None:
            release_db(conn)

    @app.context_processor
    def inject_globals():  # type: ignore[unused-variable]
        cart = session.get("cart", {})
        cart_count = sum(int(q or 0) for q in cart.values())

        def first_image(images_json: str):
            try:
                lst = json.loads(images_json or "[]")
                return lst[0] if lst else None
            except Exception:
                return None

        def images_list(images_json: str):
            try:
                return json.loads(images_json or "[]")
            except Exception:
                return []

        logo_file = os.path.join(BASE_DIR, "static", "logo.png")
        logo_url = url_for("static", filename="logo.png") if os.path.exists(logo_file) else None
        return {
            "cart_count": cart_count,
            "admin_username": session.get("admin_username"),
            "price": cents_to_price,
            "first_image": first_image,
            "images_list": images_list,
            "TINYMCE_API_KEY": app.config.get("TINYMCE_API_KEY"),
            "effective_price": effective_price_cents,
            "rating_for": lambda pid: rating_for(app, pid),
            "store_logo": logo_url,
            # Top seller helpers for product cards
            "bestseller_ids": set(get_top_sellers(app, 1)),
        }

    register_public_routes(app)
    register_admin_routes(app)


__all__ = ["register_routes"]
