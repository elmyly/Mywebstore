# Bghitha (Flask)

Une boutique Flask lumineuse et prête pour la production, avec un tableau de bord complet pour gérer produits, commandes et messages.

## Features

- Modern, responsive UI with custom CSS (no external framework required)
- Storefront: home, shop, product detail, cart, checkout, contact
- Cart stored in session; checkout creates orders in SQLite
- Admin login with session auth (default admin: `admin` / `admin123` — change these!)
- Admin dashboard: products CRUD (multi-image upload, publish toggle), orders (status updates), messages inbox
- Rich text editing for product descriptions (TinyMCE via CDN), supports tables, images, links, code
- Discounts: optional discount price, shown across storefront and used in cart/checkout
- Printable product ticket (Admin → Ticket): includes product info, QR to product page, and a barcode of product ID (server-side with fallbacks)

## Quickstart

1. Python 3.9+
2. Create a venv and install requirements:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

3. Set env vars (recommended):

```bash
export SECRET_KEY="change-me"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="choose-a-strong-password"
export TINYMCE_API_KEY="y67p36jn54fbxswq6am47k2sfdob516xwsgyicdqkx70gilr"  # change if you have your own

Optional server-side code generation (QR/Barcode) is enabled when these are installed (already in requirements):
- qrcode, Pillow, python-barcode
If unavailable at runtime, the ticket view gracefully renders placeholder SVGs so you can still print.
```

4. Run the app:

```bash
python app.py
# or
FLASK_APP=app.py flask run --debug
```

Open http://127.0.0.1:5000

On first run, the SQLite database is created in `instance/store.db` and a default admin user is seeded.

## Project Structure

- `app.py` — Flask app, routes, DB init, helpers
- `templates/` — Jinja templates for storefront and admin
- `static/` — CSS/JS and uploads (`static/uploads`)
- `instance/` — SQLite database (`store.db`)

## Admin

- Login: `/admin/login`
- Dashboard: `/admin`
- Products: create, edit (rich text), upload multiple images, remove images, publish toggle
- Orders: view details, update status (new, processing, shipped, completed, cancelled)
- Messages: mark read/unread, delete

## Deployment

- Set `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` via environment variables
- Use a WSGI server, e.g. Gunicorn or Waitress

Gunicorn example:

```bash
pip install gunicorn
export SECRET_KEY=your-secret
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=strong-pass
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Nginx can reverse-proxy to Gunicorn. Ensure `static/` is served efficiently. Create the `static/uploads` directory with write permissions.

## Notes

- Rich text editor is loaded via TinyMCE CDN. For offline or restricted environments, swap to a local bundle or fallback to plain textarea (it already works without JS, just without WYSIWYG).
- This demo trusts admin HTML for product descriptions. If multiple editors or untrusted input is expected, sanitize with a library like `bleach`.
- SQLite is great for small deployments; for higher scale, migrate to PostgreSQL with SQLAlchemy.

## License

This template is provided as-is. You’re free to adapt it for your store.
