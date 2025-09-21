import json
import secrets
import string

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..database import get_db, release_db, table_has_column
from ..faqai import ask_faq_ai
from ..newsletter import add_subscriber
from ..services import build_cart_items, get_top_sellers
from ..utils import (
    cents_to_price,
    effective_price_cents,
    now_utc_str,
)


def register_public_routes(app):
    @app.route("/")
    def index():
        conn = get_db(app)
        cur = conn.cursor()

        # Try to promote the top-selling product to the front of the homepage
        top_ids = get_top_sellers(app, 1)
        top_product = None
        if top_ids:
            cur.execute(
                "SELECT * FROM products WHERE id=? AND published=1",
                (int(top_ids[0]),),
            )
            top_product = cur.fetchone()

        if top_product:
            cur.execute(
                "SELECT * FROM products WHERE published=1 AND id != ? ORDER BY created_at DESC LIMIT 7",
                (int(top_product["id"]),),
            )
            rest = cur.fetchall()
            products = [top_product] + rest
        else:
            cur.execute(
                "SELECT * FROM products WHERE published=1 ORDER BY created_at DESC LIMIT 8"
            )
            products = cur.fetchall()

        release_db(conn)
        return render_template("index.html", products=products, price=cents_to_price)

    @app.route("/shop")
    def shop():
        q = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip()
        conn = get_db(app)
        cur = conn.cursor()
        sql = "SELECT * FROM products WHERE published=1"
        params = []
        if q:
            sql += " AND (title LIKE ? OR tags LIKE ? OR category LIKE ?)"
            like = f"%{q}%"
            params += [like, like, like]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY created_at DESC"
        cur.execute(sql, params)
        products = cur.fetchall()
        release_db(conn)
        return render_template(
            "shop.html",
            products=products,
            q=q,
            category=category,
            price=cents_to_price,
        )

    @app.route("/product/<int:pid>/<slug>")
    def product_detail(pid, slug):
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=? AND published=1", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)
        cur.execute(
            "SELECT name, rating, body, created_at FROM reviews WHERE product_id=? ORDER BY created_at DESC",
            (pid,),
        )
        reviews = cur.fetchall()
        cur.execute("SELECT AVG(rating), COUNT(*) FROM reviews WHERE product_id=?", (pid,))
        row = cur.fetchone()
        release_db(conn)
        avg = float(row[0]) if row and row[0] is not None else 0.0
        count = int(row[1]) if row and row[1] is not None else 0
        return render_template(
            "product_detail.html",
            product=product,
            price=cents_to_price,
            reviews=reviews,
            rating_avg=avg,
            rating_count=count,
        )

    @app.route("/product/<int:pid>/<slug>/quick-checkout", methods=["POST"])
    def product_quick_checkout(pid, slug):
        qty = 1
        try:
            qty = max(1, int(request.form.get("quantity", 1)))
        except Exception:
            qty = 1
        first = (request.form.get("first_name") or "").strip()
        last = (request.form.get("last_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        city = (request.form.get("city") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        if not first or not last or not city:
            flash("Please fill first name, last name and city.", "danger")
            return redirect(url_for("product_detail", pid=pid, slug=slug))

        conn = get_db(app)
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=? AND published=1", (pid,))
        product = cur.fetchone()
        if not product:
            release_db(conn)
            abort(404)
        unit_cents = effective_price_cents(product)
        line_total = unit_cents * qty
        items = [
            {
                "id": product["id"],
                "title": product["title"],
                "price_cents": unit_cents,
                "quantity": qty,
                "line_total": line_total,
                "images": json.loads(product["images"] or "[]"),
            }
        ]
        total_cents = line_total
        if table_has_column(app, "orders", "public_id"):
            pub = "".join(secrets.choice(string.digits) for _ in range(8))
            cur.execute(
                "INSERT INTO orders (customer_name, email, phone, address, city, country, notes, items, total_cents, status, created_at, public_id)\n                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{first} {last}",
                    "",
                    phone,
                    "",
                    city,
                    "",
                    notes,
                    json.dumps(items),
                    total_cents,
                    "new",
                    now_utc_str(),
                    pub,
                ),
            )
        else:
            cur.execute(
                "INSERT INTO orders (customer_name, email, phone, address, city, country, notes, items, total_cents, status, created_at)\n                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{first} {last}",
                    "",
                    phone,
                    "",
                    city,
                    "",
                    notes,
                    json.dumps(items),
                    total_cents,
                    "new",
                    now_utc_str(),
                ),
            )
        order_id = cur.lastrowid
        cur.execute(
            "UPDATE products SET stock = MAX(stock - ?, 0) WHERE id = ?",
            (qty, pid),
        )
        conn.commit()
        release_db(conn)
        flash("Order placed successfully!", "success")
        return redirect(url_for("order_success", oid=order_id))

    @app.route("/add-to-cart", methods=["POST"])
    def add_to_cart():
        pid = request.form.get("product_id")
        qty = int(request.form.get("quantity", 1))
        if not pid:
            return redirect(url_for("shop"))
        cart = session.get("cart", {})
        cart[pid] = cart.get(pid, 0) + max(1, qty)
        session["cart"] = cart
        flash("Added to cart", "success")
        return redirect(request.referrer or url_for("cart"))

    @app.route("/newsletter", methods=["GET", "POST"])
    def newsletter():
        featured = []
        conn = get_db(app)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, images, price_cents, discount_cents, slug FROM products WHERE published=1 ORDER BY created_at DESC LIMIT 3"
        )
        featured = cur.fetchall()
        release_db(conn)

        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            if not email:
                flash("Merci d'indiquer votre adresse e-mail.", "danger")
            else:
                added = add_subscriber(app, email)
                if added:
                    flash("Vous êtes inscrit(e) à notre newsletter !", "success")
                else:
                    flash("Cette adresse est déjà inscrite.", "info")
            return redirect(url_for("newsletter"))

        return render_template(
            "newsletter.html",
            featured=featured,
            price=cents_to_price,
        )

    @app.route("/cart")
    def cart():
        cart = session.get("cart", {})
        items, total_cents = build_cart_items(app, cart)
        return render_template("cart.html", items=items, total_cents=total_cents, price=cents_to_price)

    @app.route("/update-cart", methods=["POST"])
    def update_cart():
        data = request.form
        cart = {}
        for key, value in data.items():
            if key.startswith("qty_"):
                pid = key[4:]
                try:
                    qty = int(value)
                except Exception:
                    qty = 1
                if qty > 0:
                    cart[pid] = qty
        session["cart"] = cart
        flash("Cart updated", "info")
        return redirect(url_for("cart"))

    @app.route("/remove-from-cart/<pid>")
    def remove_from_cart(pid):
        cart = session.get("cart", {})
        cart.pop(str(pid), None)
        session["cart"] = cart
        flash("Item removed", "info")
        return redirect(url_for("cart"))

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        cart = session.get("cart", {})
        items, total_cents = build_cart_items(app, cart)
        if request.method == "POST":
            if not items:
                flash("Your cart is empty", "warning")
                return redirect(url_for("shop"))
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            city = request.form.get("city", "").strip()
            notes = request.form.get("notes", "").strip()
            if not name or not phone or not city:
                flash("Veuillez renseigner le nom, le téléphone et la ville.", "danger")
                return render_template(
                    "checkout.html",
                    items=items,
                    total_cents=total_cents,
                    price=cents_to_price,
                )
            email = ""
            address = ""
            country = ""
            conn = get_db(app)
            cur = conn.cursor()
            if table_has_column(app, "orders", "public_id"):
                pub = "".join(secrets.choice(string.digits) for _ in range(8))
                cur.execute(
                    "INSERT INTO orders (customer_name, email, phone, address, city, country, notes, items, total_cents, status, created_at, public_id)\n                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        email,
                        phone,
                        address,
                        city,
                        country,
                        notes,
                        json.dumps(items),
                        total_cents,
                        "new",
                        now_utc_str(),
                        pub,
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO orders (customer_name, email, phone, address, city, country, notes, items, total_cents, status, created_at)\n                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        email,
                        phone,
                        address,
                        city,
                        country,
                        notes,
                        json.dumps(items),
                        total_cents,
                        "new",
                        now_utc_str(),
                    ),
                )
            order_id = cur.lastrowid
            for item in items:
                cur.execute(
                    "UPDATE products SET stock = MAX(stock - ?, 0) WHERE id = ?",
                    (item["quantity"], item["id"]),
                )
            conn.commit()
            release_db(conn)
            session.pop("cart", None)
            return redirect(url_for("order_success", oid=order_id))
        return render_template("checkout.html", items=items, total_cents=total_cents, price=cents_to_price)

    @app.route("/order-success/<int:oid>")
    def order_success(oid):
        return render_template("order_success.html", oid=oid)

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            whatsapp = request.form.get("whatsapp", "").strip()
            subject = request.form.get("subject", "").strip()
            message = request.form.get("message", "").strip()
            if not name or not whatsapp or not message:
                flash("Please fill required fields.", "danger")
            else:
                conn = get_db(app)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO messages (name, whatsapp, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, whatsapp, subject, message, now_utc_str()),
                )
                conn.commit()
                release_db(conn)
                flash("Message received! We will get back to you soon.", "success")
                return redirect(url_for("contact"))
        return render_template("contact.html")

    @app.route("/faq", methods=["GET", "POST"])
    def faq():
        faqs = [
            {"q": "How do I place an order?", "a": "Browse products, add to cart, and proceed to checkout."},
            {
                "q": "What payment methods are accepted?",
                "a": "Cash on delivery by default; other options can be enabled by the store.",
            },
            {
                "q": "How long does delivery take?",
                "a": "Usually 2–5 business days depending on your location.",
            },
            {
                "q": "Can I return a product?",
                "a": "Yes, within 14 days if unused and in original packaging.",
            },
        ]
        ai_question = None
        ai_answer = None
        if request.method == "POST":
            ai_question = (request.form.get("question") or "").strip()
            ai_answer = ask_faq_ai(app, ai_question)
        return render_template(
            "faq.html",
            faqs=faqs,
            ai_question=ai_question,
            ai_answer=ai_answer,
        )
