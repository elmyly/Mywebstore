import hashlib
import json
import os
import secrets
import sqlite3
import string
from datetime import datetime

from flask import (
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from ..config import BASE_DIR
from ..database import get_db, release_db, table_has_column
from ..media import generate_barcode_svg_data_uri, generate_qr_data_uri
from ..newsletter import add_subscriber, is_valid_email, queue_new_product_email
from ..database import get_db, release_db
from ..utils import (
    cents_to_price,
    login_required,
    now_utc_str,
    price_to_cents,
    save_uploaded_images,
    slugify,
)


def register_admin_routes(app):
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            conn = get_db(app)
            cur = conn.cursor()
            cur.execute("SELECT * FROM admins WHERE username=?", (username,))
            admin = cur.fetchone()
            release_db(conn)
            if admin and check_password_hash(admin["password_hash"], password):
                session["admin_id"] = admin["id"]
                session["admin_username"] = admin["username"]
                flash("Welcome back!", "success")
                next_url = request.args.get("next")
                return redirect(next_url or url_for("admin_dashboard"))
            flash("Invalid credentials", "danger")
        return render_template("admin/login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("admin_id", None)
        session.pop("admin_username", None)
        flash("Logged out", "info")
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @login_required
    def admin_dashboard():
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM products")
        product_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) as c FROM orders WHERE status=?", ("new",))
        new_order_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) as c FROM messages WHERE is_read=0")
        unread_messages = cur.fetchone()[0]

        statuses = ["new", "processing", "shipped", "completed", "cancelled"]
        cur.execute("SELECT status, COUNT(*) AS c FROM orders GROUP BY status")
        rows = cur.fetchall()
        status_counts = {s: 0 for s in statuses}
        for r in rows:
            s = r["status"]
            if s in status_counts:
                status_counts[s] = int(r["c"])
        total_orders = sum(status_counts.values())

        def sum_since(delta_expr: str) -> int:
            cur.execute(
                """
                SELECT COALESCE(SUM(total_cents), 0) AS s
                FROM orders
                WHERE status IN ('completed','shipped')
                  AND julianday(created_at) >= julianday('now', ?)
                """,
                (delta_expr,),
            )
            row = cur.fetchone()
            return int(row[0] or 0)

        earn_day = sum_since("-1 day")
        earn_week = sum_since("-7 day")
        earn_month = sum_since("-30 day")

        cur.execute(
            "SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE status IN ('completed','shipped')"
        )
        revenue_total_cents = int(cur.fetchone()[0] or 0)

        cur.execute("SELECT COUNT(*) FROM products WHERE published=1")
        published_count = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM products WHERE published=0")
        draft_count = int(cur.fetchone()[0] or 0)

        cur.execute(
            "SELECT id, title, stock FROM products WHERE stock <= 5 ORDER BY stock ASC, title ASC LIMIT 8"
        )
        low_stock = cur.fetchall()

        cur.execute(
            "SELECT items FROM orders WHERE julianday(created_at) >= julianday('now','-30 day')"
        )
        top_map = {}
        for row in cur.fetchall():
            try:
                its = json.loads(row["items"] or "[]")
            except Exception:
                its = []
            for it in its:
                key = str(it.get("id") or it.get("title"))
                qty = int(it.get("quantity") or 0)
                rev = int(it.get("line_total") or 0)
                title = it.get("title") or f"#{key}"
                if key not in top_map:
                    top_map[key] = {"title": title, "qty": 0, "revenue": 0}
                top_map[key]["qty"] += qty
                top_map[key]["revenue"] += rev
        top_products = sorted(top_map.values(), key=lambda x: (-x["qty"], -x["revenue"]))[:5]
        release_db(conn)
        return render_template(
            "admin/dashboard.html",
            product_count=product_count,
            new_order_count=new_order_count,
            unread_messages=unread_messages,
            status_counts=status_counts,
            total_orders=total_orders,
            price=cents_to_price,
            earn_day=earn_day,
            earn_week=earn_week,
            earn_month=earn_month,
            revenue_total_cents=revenue_total_cents,
            published_count=published_count,
            draft_count=draft_count,
            low_stock=low_stock,
            top_products=top_products,
        )

    @app.route("/admin/order-lookup", methods=["GET", "POST"])
    @login_required
    def admin_order_lookup():
        if request.method == "POST":
            code = (request.form.get("order_code") or "").strip()
            if not code:
                flash("Please enter an order ID or code.", "warning")
                return render_template("admin/order_lookup.html")
            conn = get_db(app)
            cur = conn.cursor()
            found_id = None

            if table_has_column(app, "orders", "public_id"):
                cur.execute("SELECT id FROM orders WHERE public_id=?", (code,))
                row = cur.fetchone()
                if row:
                    found_id = int(row["id"])

            if found_id is None:
                cur.execute("SELECT id, created_at, total_cents FROM orders")
                for oid, created_at, total_cents in cur.fetchall():
                    seed = f"{oid}-{created_at}-{total_cents}"
                    num = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % (10 ** 8)
                    if f"{num:08d}" == code:
                        found_id = int(oid)
                        break

            if found_id is None:
                try:
                    int_id = int(code.lstrip("0") or "0")
                    cur.execute("SELECT id FROM orders WHERE id=?", (int_id,))
                    row = cur.fetchone()
                    if row:
                        found_id = int(row[0])
                except Exception:
                    found_id = None

            if found_id is not None:
                cur.execute("SELECT * FROM orders WHERE id=?", (found_id,))
                order = cur.fetchone()
                order_items = json.loads(order["items"] or "[]")
                release_db(conn)

                public_code = None
                if table_has_column(app, "orders", "public_id"):
                    if ("public_id" in order.keys()) and order["public_id"]:
                        public_code = str(order["public_id"])
                    else:
                        conn2 = get_db(app)
                        cur2 = conn2.cursor()
                        pid = "".join(secrets.choice(string.digits) for _ in range(8))
                        try:
                            cur2.execute("UPDATE orders SET public_id=? WHERE id=?", (pid, found_id))
                            conn2.commit()
                            public_code = pid
                        finally:
                            release_db(conn2)
                if not public_code:
                    seed = f"{order['id']}-{order['created_at']}-{order['total_cents']}"
                    num = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % (10 ** 8)
                    public_code = f"{num:08d}"

                return render_template(
                    "admin/order_lookup.html",
                    order=order,
                    items=order_items,
                    public_code=public_code,
                    price=cents_to_price,
                )

            release_db(conn)
            flash("Order not found.", "danger")
            return render_template("admin/order_lookup.html")

        return render_template("admin/order_lookup.html")

    @app.route("/admin/products")
    @login_required
    def admin_products():
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM products ORDER BY created_at DESC")
        products = cur.fetchall()
        release_db(conn)
        return render_template("admin/products.html", products=products, price=cents_to_price)

    @app.route("/admin/orders/clear", methods=["POST"])
    @login_required
    def admin_orders_clear():
        conn = get_db(app)
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM orders")
            try:
                cur.execute("DELETE FROM sqlite_sequence WHERE name='orders'")
            except Exception:
                pass
            conn.commit()
            flash("All orders cleared.", "warning")
        finally:
            release_db(conn)
        return redirect(url_for("admin_orders"))

    @app.route("/admin/products/new", methods=["GET", "POST"])
    @login_required
    def admin_product_new():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description_html = request.form.get("description", "").strip()
            price_cents_val = price_to_cents(request.form.get("price", "0"))
            discount_cents_val = (
                price_to_cents(request.form.get("discount_price", ""))
                if request.form.get("discount_price")
                else None
            )
            category = request.form.get("category", "").strip()
            tags = request.form.get("tags", "").strip()
            sku = request.form.get("sku", "").strip()
            stock = int(request.form.get("stock", 0) or 0)
            published = 1 if request.form.get("published") == "on" else 0
            slug = slugify(title)

            images = save_uploaded_images(request.files.getlist("images"), app.config["UPLOAD_FOLDER"])
            created_at = now_utc_str()

            conn = get_db(app)
            cur = conn.cursor()
            base_slug = slug or slugify(f"produit-{created_at}") or "produit"
            slug_candidate = base_slug
            suffix = 1
            while True:
                cur.execute("SELECT id FROM products WHERE slug=?", (slug_candidate,))
                if not cur.fetchone():
                    break
                suffix += 1
                slug_candidate = f"{base_slug}-{suffix}"
            slug = slug_candidate
            has_ticket_column = table_has_column(app, "products", "ticket_id")
            digits = string.digits
            ticket_id = "".join(secrets.choice(digits) for _ in range(8)) if has_ticket_column else None
            inserted = False
            for _ in range(5):
                try:
                    if has_ticket_column:
                        cur.execute(
                            "INSERT INTO products (title, slug, description_html, price_cents, discount_cents, images, category, tags, stock, sku, published, created_at, updated_at, ticket_id)\n                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                title,
                                slug,
                                description_html,
                                price_cents_val,
                                discount_cents_val,
                                json.dumps(images),
                                category,
                                tags,
                                stock,
                                sku,
                                published,
                                created_at,
                                created_at,
                                ticket_id,
                            ),
                        )
                    else:
                        cur.execute(
                            "INSERT INTO products (title, slug, description_html, price_cents, discount_cents, images, category, tags, stock, sku, published, created_at, updated_at)\n                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                title,
                                slug,
                                description_html,
                                price_cents_val,
                                discount_cents_val,
                                json.dumps(images),
                                category,
                                tags,
                                stock,
                                sku,
                                published,
                                created_at,
                                created_at,
                            ),
                        )
                    inserted = True
                    break
                except Exception:
                    if has_ticket_column:
                        ticket_id = "".join(secrets.choice(digits) for _ in range(8))
            if not inserted:
                conn.rollback()
                release_db(conn)
                flash("Unable to create product. Please review the details and try again.", "danger")
                return render_template("admin/product_form.html", product=None)
            conn.commit()
            new_id = cur.lastrowid
            cur.execute("SELECT * FROM products WHERE id=?", (new_id,))
            new_product = cur.fetchone()
            release_db(conn)
            if new_product:
                queue_new_product_email(app, dict(new_product))
            flash("Product created", "success")
            return redirect(url_for("admin_products"))
        return render_template("admin/product_form.html", product=None)

    @app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
    @login_required
    def admin_product_edit(pid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description_html = request.form.get("description", "").strip()
            price_cents_val = price_to_cents(request.form.get("price", "0"))
            discount_cents_val = (
                price_to_cents(request.form.get("discount_price", ""))
                if request.form.get("discount_price")
                else None
            )
            category = request.form.get("category", "").strip()
            tags = request.form.get("tags", "").strip()
            sku = request.form.get("sku", "").strip()
            stock = int(request.form.get("stock", 0) or 0)
            published = 1 if request.form.get("published") == "on" else 0
            slug = slugify(title)

            existing_images = json.loads(product["images"] or "[]")
            remove_list = request.form.getlist("remove_images")
            keep_images = [img for img in existing_images if img not in remove_list]
            for img_path in remove_list:
                try:
                    os.remove(os.path.join(BASE_DIR, "static", img_path))
                except Exception:
                    pass
            new_images = save_uploaded_images(request.files.getlist("images"), app.config["UPLOAD_FOLDER"])
            all_images = keep_images + new_images

            base_slug = slug or slugify(title) or f"produit-{pid}"
            slug_candidate = base_slug
            suffix = 1
            while True:
                cur.execute("SELECT id FROM products WHERE slug=?", (slug_candidate,))
                row = cur.fetchone()
                if not row or row["id"] == pid:
                    break
                suffix += 1
                slug_candidate = f"{base_slug}-{suffix}"
            slug = slug_candidate

            cur.execute(
                "UPDATE products SET title=?, slug=?, description_html=?, price_cents=?, discount_cents=?, images=?, category=?, tags=?, stock=?, sku=?, published=?, updated_at=? WHERE id=?",
                (
                    title,
                    slug,
                    description_html,
                    price_cents_val,
                    discount_cents_val,
                    json.dumps(all_images),
                    category,
                    tags,
                    stock,
                    sku,
                    published,
                    datetime.utcnow().isoformat(),
                    pid,
                ),
            )
            conn.commit()
            release_db(conn)
            flash("Product updated", "success")
            return redirect(url_for("admin_products"))
        release_db(conn)
        return render_template("admin/product_form.html", product=product)

    @app.route("/admin/products/<int:pid>/delete", methods=["POST"])
    @login_required
    def admin_product_delete(pid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT images FROM products WHERE id=?", (pid,))
        row = cur.fetchone()
        if row:
            imgs = json.loads(row["images"] or "[]")
            for img in imgs:
                try:
                    os.remove(os.path.join(BASE_DIR, "static", img))
                except Exception:
                    pass
        cur.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        release_db(conn)
        flash("Product deleted", "info")
        return redirect(url_for("admin_products"))

    @app.route("/admin/products/<int:pid>/draft", methods=["POST"])
    @login_required
    def admin_product_draft(pid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT id, published FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)
        if product["published"]:
            cur.execute(
                "UPDATE products SET published=0, updated_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), pid),
            )
            conn.commit()
            flash("Product moved to drafts", "info")
        release_db(conn)
        return redirect(url_for("admin_products"))

    @app.route("/admin/products/<int:pid>/publish", methods=["POST"])
    @login_required
    def admin_product_publish(pid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT id, published FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)
        if not product["published"]:
            cur.execute(
                "UPDATE products SET published=1, updated_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), pid),
            )
            conn.commit()
            flash("Product published", "success")
        release_db(conn)
        return redirect(url_for("admin_products"))

    @app.route("/admin/products/<int:pid>/duplicate", methods=["POST"])
    @login_required
    def admin_product_duplicate(pid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)

        base_title = product["title"] or "Product"
        suffix = 1
        while True:
            copy_title = f"{base_title} {suffix}"
            cur.execute("SELECT 1 FROM products WHERE title=?", (copy_title,))
            if not cur.fetchone():
                break
            suffix += 1

        base_slug = slugify(copy_title) or slugify(f"produit-{pid}") or f"produit-{pid}"
        slug_candidate = base_slug
        slug_suffix = 1
        while True:
            cur.execute("SELECT 1 FROM products WHERE slug=?", (slug_candidate,))
            if not cur.fetchone():
                break
            slug_candidate = f"{base_slug}-{slug_suffix}"
            slug_suffix += 1

        now_ts = datetime.utcnow().isoformat()
        discount_cents = product["discount_cents"] if product["discount_cents"] else None
        has_ticket_column = table_has_column(app, "products", "ticket_id")
        ticket_id = None
        if has_ticket_column:
            digits = string.digits
            ticket_id = "".join(secrets.choice(digits) for _ in range(8))

        sku_copy = product["sku"] or ""
        sku_duplicate = f"{sku_copy}-COPY" if sku_copy else ""

        inserted = False
        digits = string.digits
        for _ in range(5):
            try:
                if has_ticket_column:
                    if ticket_id is None:
                        ticket_id = "".join(secrets.choice(digits) for _ in range(8))
                    cur.execute(
                        "INSERT INTO products (title, slug, description_html, price_cents, discount_cents, images, category, tags, stock, sku, published, created_at, updated_at, ticket_id)\n                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            copy_title,
                            slug_candidate,
                            product["description_html"],
                            product["price_cents"],
                            discount_cents,
                            product["images"],
                            product["category"],
                            product["tags"],
                            product["stock"],
                            sku_duplicate,
                            product["published"],
                            now_ts,
                            now_ts,
                            ticket_id,
                        ),
                    )
                else:
                    cur.execute(
                        "INSERT INTO products (title, slug, description_html, price_cents, discount_cents, images, category, tags, stock, sku, published, created_at, updated_at)\n                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            copy_title,
                            slug_candidate,
                            product["description_html"],
                            product["price_cents"],
                            discount_cents,
                            product["images"],
                            product["category"],
                            product["tags"],
                            product["stock"],
                            sku_duplicate,
                            product["published"],
                            now_ts,
                            now_ts,
                        ),
                    )
                inserted = True
                break
            except Exception:
                slug_suffix += 1
                slug_candidate = f"{base_slug}-{slug_suffix}"
                if has_ticket_column:
                    ticket_id = "".join(secrets.choice(digits) for _ in range(8))
        if not inserted:
            conn.rollback()
            release_db(conn)
            flash("Could not duplicate product. Please try again.", "danger")
            return redirect(url_for("admin_products"))
        conn.commit()
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM products WHERE id=?", (new_id,))
        new_product = cur.fetchone()
        release_db(conn)
        if new_product:
            queue_new_product_email(app, dict(new_product))
        flash("Product duplicated", "success")
        return redirect(url_for("admin_products"))

    @app.route("/admin/newsletter", methods=["GET", "POST"])
    @login_required
    def admin_newsletter():
        conn = get_db(app)
        cur = conn.cursor()
        if request.method == "POST":
            action = request.form.get("action", "").strip().lower()
            if action == "add":
                email = (request.form.get("email") or "").strip()
                if not email:
                    flash("Please provide an email address.", "danger")
                else:
                    added = add_subscriber(app, email)
                    if added:
                        flash("Subscriber added.", "success")
                    else:
                        flash("Email invalid or already subscribed.", "info")
                release_db(conn)
                return redirect(url_for("admin_newsletter"))

            sid_raw = request.form.get("id")
            try:
                subscriber_id = int(sid_raw or "0")
            except ValueError:
                subscriber_id = 0
            if not subscriber_id:
                flash("Subscriber not found.", "danger")
                release_db(conn)
                return redirect(url_for("admin_newsletter"))

            if action == "delete":
                cur.execute("DELETE FROM newsletter_subscribers WHERE id=?", (subscriber_id,))
                if cur.rowcount:
                    conn.commit()
                    flash("Subscriber removed.", "success")
                else:
                    flash("Subscriber not found.", "warning")
                release_db(conn)
                return redirect(url_for("admin_newsletter"))

            if action == "update":
                email = (request.form.get("email") or "").strip().lower()
                if not is_valid_email(email):
                    flash("Please enter a valid email address.", "danger")
                    release_db(conn)
                    return redirect(url_for("admin_newsletter"))
                try:
                    cur.execute(
                        "UPDATE newsletter_subscribers SET email=? WHERE id=?",
                        (email, subscriber_id),
                    )
                    if cur.rowcount:
                        conn.commit()
                        flash("Subscriber updated.", "success")
                    else:
                        flash("Subscriber not found.", "warning")
                except sqlite3.IntegrityError:
                    flash("This email is already subscribed.", "info")
                release_db(conn)
                return redirect(url_for("admin_newsletter"))

            flash("Unsupported action.", "danger")
            release_db(conn)
            return redirect(url_for("admin_newsletter"))

        cur.execute(
            "SELECT id, email, created_at FROM newsletter_subscribers ORDER BY created_at DESC"
        )
        subscribers = cur.fetchall()
        release_db(conn)
        return render_template("admin/newsletter.html", subscribers=subscribers)

    @app.route("/admin/ai", methods=["GET", "POST"])
    @login_required
    def admin_ai():
        conn = get_db(app)
        cur = conn.cursor()
        if request.method == "POST":
            context = (request.form.get("context") or "").strip()
            cur.execute(
                "INSERT INTO ai_settings (key, value) VALUES ('faq_context', ?)\n                 ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (context,),
            )
            conn.commit()
            release_db(conn)
            flash("AI data updated.", "success")
            return redirect(url_for("admin_ai"))
        cur.execute("SELECT value FROM ai_settings WHERE key='faq_context'")
        row = cur.fetchone()
        context = (row[0] or "") if row else ""
        release_db(conn)
        return render_template("admin/ai_data.html", context=context)

    @app.route("/admin/orders")
    @login_required
    def admin_orders():
        status = request.args.get("status", "")
        order_by = "created_at DESC"
        conn = get_db(app)
        cur = conn.cursor()
        if status:
            cur.execute(f"SELECT * FROM orders WHERE status=? ORDER BY {order_by}", (status,))
        else:
            cur.execute(f"SELECT * FROM orders ORDER BY {order_by}")
        orders = cur.fetchall()

        statuses = ["new", "processing", "shipped", "completed", "cancelled"]
        cur.execute("SELECT status, COUNT(*) AS c FROM orders GROUP BY status")
        rows = cur.fetchall()
        counts = {s: 0 for s in statuses}
        for row in rows:
            s = row["status"]
            if s in counts:
                counts[s] = row["c"]
        counts["total"] = sum(counts.values())

        release_db(conn)
        return render_template(
            "admin/orders.html",
            orders=orders,
            current_status=status,
            counts=counts,
            price=cents_to_price,
        )

    @app.route("/admin/orders/<int:oid>", methods=["GET", "POST"])
    @login_required
    def admin_order_detail(oid):
        conn = get_db(app)
        cur = conn.cursor()
        if request.method == "POST":
            status = request.form.get("status", "new")
            cur.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
            conn.commit()
            flash("Order status updated", "success")
        cur.execute("SELECT * FROM orders WHERE id=?", (oid,))
        order = cur.fetchone()
        release_db(conn)
        if not order:
            abort(404)
        order_items = json.loads(order["items"] or "[]")
        return render_template(
            "admin/order_detail.html",
            order=order,
            order_items=order_items,
            price=cents_to_price,
        )

    @app.route("/admin/orders/<int:oid>/ticket")
    @login_required
    def admin_order_ticket(oid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id=?", (oid,))
        order = cur.fetchone()
        release_db(conn)
        if not order:
            abort(404)
        order_items = json.loads(order["items"] or "[]")
        order_url = url_for("order_success", oid=oid, _external=True)
        qr_img = generate_qr_data_uri(order_url)
        public_code = None
        if table_has_column(app, "orders", "public_id"):
            if ("public_id" in order.keys()) and order["public_id"]:
                public_code = str(order["public_id"])
            else:
                conn = get_db(app)
                cur = conn.cursor()
                pid = "".join(secrets.choice(string.digits) for _ in range(8))
                try:
                    cur.execute("UPDATE orders SET public_id=? WHERE id=?", (pid, oid))
                    conn.commit()
                    public_code = pid
                finally:
                    release_db(conn)
        if not public_code:
            seed = f"{order['id']}-{order['created_at']}-{order['total_cents']}"
            num = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % (10 ** 8)
            public_code = f"{num:08d}"
        display_code = public_code
        barcode_img = generate_barcode_svg_data_uri(display_code)
        html = render_template(
            "admin/order_ticket.html",
            order=order,
            items=order_items,
            order_url=order_url,
            qr_img=qr_img,
            barcode_img=barcode_img,
            public_code=display_code,
            price=cents_to_price,
        )
        return html

    @app.route("/admin/messages", methods=["GET", "POST"])
    @login_required
    def admin_messages():
        conn = get_db(app)
        cur = conn.cursor()
        if request.method == "POST":
            action = request.form.get("action")
            mid = int(request.form.get("id"))
            if action == "toggle":
                cur.execute("UPDATE messages SET is_read = 1 - is_read WHERE id=?", (mid,))
                conn.commit()
            elif action == "delete":
                cur.execute("DELETE FROM messages WHERE id=?", (mid,))
                conn.commit()
        cur.execute("SELECT * FROM messages ORDER BY created_at DESC")
        messages = cur.fetchall()
        release_db(conn)
        return render_template("admin/messages.html", messages=messages)

    @app.route("/admin/reviews")
    @login_required
    def admin_reviews():
        product_id = request.args.get("product_id")
        conn = get_db(app)
        cur = conn.cursor()
        if product_id:
            cur.execute(
                """
                SELECT r.*, p.title as product_title
                FROM reviews r LEFT JOIN products p ON p.id = r.product_id
                WHERE r.product_id = ?
                ORDER BY r.created_at DESC
                """,
                (product_id,),
            )
        else:
            cur.execute(
                """
                SELECT r.*, p.title as product_title
                FROM reviews r LEFT JOIN products p ON p.id = r.product_id
                ORDER BY r.created_at DESC
                """
            )
        reviews = cur.fetchall()
        cur.execute("SELECT id, title FROM products ORDER BY title ASC")
        products = cur.fetchall()
        release_db(conn)
        return render_template(
            "admin/reviews.html",
            reviews=reviews,
            products=products,
            current_pid=product_id,
        )

    @app.route("/admin/reviews/new", methods=["GET", "POST"])
    @login_required
    def admin_review_new():
        conn = get_db(app)
        cur = conn.cursor()
        if request.method == "POST":
            product_id = int(request.form.get("product_id"))
            name = request.form.get("name", "").strip() or "Anonymous"
            try:
                rating = int(request.form.get("rating", 5))
            except Exception:
                rating = 5
            rating = min(5, max(1, rating))
            body = request.form.get("body", "").strip()
            cur.execute(
                "INSERT INTO reviews (product_id, name, rating, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (product_id, name, rating, body, datetime.utcnow().isoformat()),
            )
            conn.commit()
            if hasattr(g, "_ratings_cache"):
                g._ratings_cache = None
            release_db(conn)
            flash("Review added", "success")
            return redirect(url_for("admin_reviews", product_id=product_id))
        cur.execute("SELECT id, title FROM products ORDER BY title ASC")
        products = cur.fetchall()
        release_db(conn)
        return render_template("admin/review_form.html", review=None, products=products)

    @app.route("/admin/reviews/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def admin_review_edit(rid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute(
            "SELECT r.*, p.title as product_title FROM reviews r LEFT JOIN products p ON p.id=r.product_id WHERE r.id=?",
            (rid,),
        )
        review = cur.fetchone()
        if not review:
            release_db(conn)
            abort(404)
        if request.method == "POST":
            try:
                product_id = int(request.form.get("product_id", review["product_id"]))
            except Exception:
                product_id = review["product_id"]
            name = request.form.get("name", review["name"]).strip() or "Anonymous"
            try:
                rating = int(request.form.get("rating", review["rating"]))
            except Exception:
                rating = review["rating"]
            rating = min(5, max(1, rating))
            body = request.form.get("body", review["body"]).strip()
            cur.execute(
                "UPDATE reviews SET product_id=?, name=?, rating=?, body=? WHERE id=?",
                (product_id, name, rating, body, rid),
            )
            conn.commit()
            if hasattr(g, "_ratings_cache"):
                g._ratings_cache = None
            release_db(conn)
            flash("Review updated", "success")
            return redirect(url_for("admin_reviews", product_id=product_id))
        cur.execute("SELECT id, title FROM products ORDER BY title ASC")
        products = cur.fetchall()
        release_db(conn)
        return render_template("admin/review_form.html", review=review, products=products)

    @app.route("/admin/reviews/<int:rid>/delete", methods=["POST"])
    @login_required
    def admin_review_delete(rid):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT product_id FROM reviews WHERE id=?", (rid,))
        row = cur.fetchone()
        if not row:
            release_db(conn)
            abort(404)
        product_id = row["product_id"]
        cur.execute("DELETE FROM reviews WHERE id=?", (rid,))
        conn.commit()
        if hasattr(g, "_ratings_cache"):
            g._ratings_cache = None
        release_db(conn)
        flash("Review deleted", "info")
        return redirect(url_for("admin_reviews", product_id=product_id))
