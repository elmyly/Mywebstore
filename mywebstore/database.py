import os
import random
import sqlite3
from typing import Optional

from flask import Flask, g, has_app_context
from werkzeug.security import generate_password_hash

from .utils import now_utc_str


def get_db(app: Flask) -> sqlite3.Connection:
    db_path = os.path.join(app.instance_path, "store.db")
    if has_app_context():
        cached = getattr(g, "_db_conn", None)
        if cached is not None:
            return cached
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        g._db_conn = conn
        return conn
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def release_db(conn: Optional[sqlite3.Connection]) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass
    if has_app_context() and getattr(g, "_db_conn", None) is conn:
        g._db_conn = None


def init_db(app: Flask) -> None:
    db_path = os.path.join(app.instance_path, "store.db")
    if os.path.exists(db_path):
        migrate_db_schema(app)
        return
    conn = get_db(app)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE,
            description_html TEXT,
            price_cents INTEGER NOT NULL DEFAULT 0,
            discount_cents INTEGER,
            images TEXT,
            category TEXT,
            tags TEXT,
            stock INTEGER DEFAULT 0,
            sku TEXT,
            published INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            city TEXT,
            country TEXT,
            notes TEXT,
            items TEXT,
            total_cents INTEGER,
            status TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            whatsapp TEXT,
            subject TEXT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            name TEXT,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            body TEXT,
            avatar_path TEXT,
            created_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        -- Key/value app settings (used for AI context, etc.)
        CREATE TABLE IF NOT EXISTS ai_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS newsletter_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_products_published_created ON products(published, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
        CREATE INDEX IF NOT EXISTS idx_orders_status_created ON orders(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
        """
    )
    conn.commit()
    release_db(conn)


def ensure_default_admin(app: Flask) -> None:
    conn = get_db(app)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM admins")
    count = cur.fetchone()[0]
    username = app.config["ADMIN_USERNAME"]
    password = app.config["ADMIN_PASSWORD"]
    if count == 0:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        conn.commit()
    else:
        cur.execute(
            "UPDATE admins SET username=?, password_hash=? WHERE id=(SELECT id FROM admins ORDER BY id LIMIT 1)",
            (username, generate_password_hash(password)),
        )
        conn.commit()
    release_db(conn)


def migrate_db_schema(app: Flask) -> None:
    conn = get_db(app)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(products)")
    cols = {row[1] for row in cur.fetchall()}
    if "discount_cents" not in cols:
        try:
            cur.execute("ALTER TABLE products ADD COLUMN discount_cents INTEGER")
            conn.commit()
        except Exception:
            pass

    cur.execute("PRAGMA table_info(products)")
    cols = {row[1] for row in cur.fetchall()}
    if "ticket_id" not in cols:
        try:
            cur.execute("ALTER TABLE products ADD COLUMN ticket_id TEXT UNIQUE")
            conn.commit()
        except Exception:
            pass

    try:
        import secrets
        import string

        digits = string.digits
        cur.execute("SELECT ticket_id FROM products WHERE ticket_id IS NOT NULL AND ticket_id != ''")
        existing = {row[0] for row in cur.fetchall() if row[0]}
        cur.execute("SELECT id FROM products WHERE ticket_id IS NULL OR ticket_id = ''")
        todo = [r[0] for r in cur.fetchall()]
        for pid in todo:
            while True:
                tid = ''.join(secrets.choice(digits) for _ in range(8))
                if tid not in existing:
                    existing.add(tid)
                    break
            cur.execute("UPDATE products SET ticket_id=? WHERE id=?", (tid, pid))
        if todo:
            conn.commit()
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            name TEXT,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            body TEXT,
            avatar_path TEXT,
            created_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id)")
    conn.commit()

    # Ensure ai_settings exists
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS newsletter_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT
        );
        """
    )
    conn.commit()

    cur.execute("PRAGMA table_info(messages)")
    mcols = {row[1] for row in cur.fetchall()}
    if "whatsapp" not in mcols:
        try:
            cur.execute("ALTER TABLE messages ADD COLUMN whatsapp TEXT")
            conn.commit()
        except Exception:
            pass

    cur.execute("PRAGMA table_info(orders)")
    ocols = {row[1] for row in cur.fetchall()}
    if "public_id" not in ocols:
        try:
            cur.execute("ALTER TABLE orders ADD COLUMN public_id TEXT UNIQUE")
            conn.commit()
        except Exception:
            pass

    try:
        import secrets
        import string

        digits = string.digits
        cur.execute("SELECT public_id FROM orders WHERE public_id IS NOT NULL AND public_id != ''")
        existing = {row[0] for row in cur.fetchall() if row[0]}
        cur.execute("SELECT id FROM orders WHERE public_id IS NULL OR public_id = ''")
        for (oid,) in cur.fetchall():
            while True:
                pid = ''.join(secrets.choice(digits) for _ in range(8))
                if pid not in existing:
                    existing.add(pid)
                    break
            cur.execute("UPDATE orders SET public_id=? WHERE id=?", (pid, oid))
        conn.commit()
    except Exception:
        pass

    try:
        for tbl in ("orders", "products", "messages", "reviews"):
            cur.execute(
                f"UPDATE {tbl} SET created_at = substr(replace(created_at, 'T', ' '), 1, 19) WHERE created_at LIKE '%T%'"
            )
        cur.execute(
            "UPDATE products SET updated_at = substr(replace(updated_at, 'T', ' '), 1, 19) WHERE updated_at LIKE '%T%'"
        )
        conn.commit()
    except Exception:
        pass

    release_db(conn)


def ensure_fake_reviews(app: Flask) -> None:
    names = [
        "Alex",
        "Sam",
        "Jordan",
        "Taylor",
        "Casey",
        "Riley",
        "Avery",
        "Jamie",
        "Drew",
        "Morgan",
        "Cameron",
        "Quinn",
    ]
    blurbs = [
        "Excellent quality and fast delivery!",
        "Looks even better in person.",
        "Great value for the price.",
        "Beautiful design — highly recommend.",
        "Five stars, will buy again.",
        "Exactly what I was looking for.",
        "Packaging was premium and eco-friendly.",
        "Customer support was super helpful.",
        "Feels solid and well made.",
        "Stunning! Got lots of compliments.",
    ]
    conn = get_db(app)
    cur = conn.cursor()
    cur.execute("SELECT id FROM products")
    pids = [row[0] for row in cur.fetchall()]
    for pid in pids:
        cur.execute("SELECT COUNT(*) FROM reviews WHERE product_id=?", (pid,))
        if cur.fetchone()[0] == 0:
            for _ in range(random.randint(3, 7)):
                name = random.choice(names)
                rating = random.choices([3, 4, 5], weights=[1, 3, 6], k=1)[0]
                body = random.choice(blurbs)
                cur.execute(
                    "INSERT INTO reviews (product_id, name, rating, body, created_at) VALUES (?, ?, ?, ?, ?)",
                    (pid, name, rating, body, now_utc_str()),
                )
    conn.commit()
    release_db(conn)


def table_has_column(app: Flask, table: str, column: str) -> bool:
    """Check schema with a short-lived connection so we don't close shared ones."""
    db_path = os.path.join(app.instance_path, "store.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())
    finally:
        conn.close()


__all__ = [
    "get_db",
    "release_db",
    "init_db",
    "ensure_default_admin",
    "ensure_fake_reviews",
    "migrate_db_schema",
    "table_has_column",
]
