import json
from typing import Dict, List, Tuple

from flask import Flask, g

from .database import get_db, release_db
from .utils import effective_price_cents


def build_cart_items(app: Flask, cart: Dict[str, int]) -> Tuple[List[dict], int]:
    if not cart:
        return [], 0
    ids = [int(pid) for pid in cart.keys()]
    placeholders = ",".join(["?"] * len(ids))
    conn = get_db(app)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM products WHERE id IN ({placeholders})", ids)
    rows = cur.fetchall()
    release_db(conn)

    items: List[dict] = []
    total = 0
    by_id = {str(row["id"]): row for row in rows}
    for pid, qty in cart.items():
        row = by_id.get(str(pid))
        if not row:
            continue
        qty = max(1, int(qty))
        unit_cents = effective_price_cents(row)
        line_total = unit_cents * qty
        total += line_total
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "price_cents": unit_cents,
                "images": json.loads(row["images"] or "[]"),
                "quantity": qty,
                "line_total": line_total,
                "orig_price_cents": row["price_cents"],
                "discount_cents": row["discount_cents"],
            }
        )
    return items, total


def get_ratings_cache(app: Flask):
    cache = getattr(g, "_ratings_cache", None)
    if cache is not None:
        return cache
    conn = get_db(app)
    cur = conn.cursor()
    cur.execute("SELECT product_id, AVG(rating) as avg_r, COUNT(*) as c FROM reviews GROUP BY product_id")
    data = {row[0]: (float(row[1]) if row[1] is not None else 0.0, int(row[2] or 0)) for row in cur.fetchall()}
    g._ratings_cache = data
    return data


def rating_for(app: Flask, product_id: int):
    cache = get_ratings_cache(app)
    return cache.get(int(product_id), (0.0, 0))


__all__ = ["build_cart_items", "get_ratings_cache", "rating_for"]
 
def get_top_sellers(app: Flask, limit: int = 1) -> List[int]:
    """Return product IDs of top sellers by quantity from shipped/completed orders.
    Cached per-request in Flask g.
    """
    cache_key = f"_top_sellers_{limit}"
    cached = getattr(g, cache_key, None)
    if cached is not None:
        return cached
    conn = get_db(app)
    cur = conn.cursor()
    # Consider only shipped/completed as actually sold
    cur.execute(
        "SELECT items FROM orders WHERE status IN ('completed','shipped')"
    )
    counts: Dict[int, int] = {}
    for row in cur.fetchall():
        try:
            items = json.loads(row[0] or "[]")
        except Exception:
            items = []
        for it in items:
            try:
                pid = int(it.get("id"))
                qty = int(it.get("quantity") or 0)
            except Exception:
                continue
            counts[pid] = counts.get(pid, 0) + qty
    # If no shipped/completed sales found, fall back to all orders
    if not counts:
        cur.execute("SELECT items FROM orders")
        for row in cur.fetchall():
            try:
                items = json.loads(row[0] or "[]")
            except Exception:
                items = []
            for it in items:
                try:
                    pid = int(it.get("id"))
                    qty = int(it.get("quantity") or 0)
                except Exception:
                    continue
                counts[pid] = counts.get(pid, 0) + qty

    # Sort by quantity desc then by product id for stability
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    result = [pid for pid, _ in top[: max(1, int(limit))]]
    setattr(g, cache_key, result)
    # Do NOT close the connection here. get_db() stores it in flask.g and
    # callers may still be using the same connection in the same request
    # lifecycle. Teardown will handle closing.
    return result
