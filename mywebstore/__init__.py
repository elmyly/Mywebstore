import os
import secrets
from flask import Flask

from .config import BASE_DIR, STATIC_DIR, UPLOAD_FOLDER
from .database import init_db, ensure_default_admin, ensure_fake_reviews
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder=STATIC_DIR,
        template_folder=os.path.join(BASE_DIR, "templates"),
    )

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(16)),
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "myly"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "myly00myly"),
        TINYMCE_API_KEY=os.environ.get(
            "TINYMCE_API_KEY",
            "y67p36jn54fbxswq6am47k2sfdob516xwsgyicdqkx70gilr",
        ),
        NEWSLETTER_FROM_EMAIL=os.environ.get("NEWSLETTER_FROM_EMAIL", "elmylypro@gmail.com"),
        NEWSLETTER_FROM_NAME=os.environ.get("NEWSLETTER_FROM_NAME", "Bghitha"),
        NEWSLETTER_APP_PASSWORD=os.environ.get("NEWSLETTER_APP_PASSWORD", "nsaqigjjvrtmgnak"),
        SITE_URL=os.environ.get("SITE_URL", "https://bghitha.com"),
        FAQ_AI_API_KEY=os.environ.get("FAQ_AI_API_KEY", "AIzaSyD4hSRHztjgXFLc8bjLA0McDDnIjp2Js14"),
    )

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    init_db(app)
    ensure_default_admin(app)
    ensure_fake_reviews(app)

    register_routes(app)

    return app


__all__ = ["create_app"]
