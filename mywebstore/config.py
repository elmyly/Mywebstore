import os

# Project root (one directory above this package)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_FOLDER = os.path.join(STATIC_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

__all__ = [
    "BASE_DIR",
    "STATIC_DIR",
    "UPLOAD_FOLDER",
    "ALLOWED_EXTENSIONS",
]
