"""Product catalogue: categories, listing/search, product details."""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from . import db, flaws, metrics
from .deps import apply_chaos

router = APIRouter(prefix="/api", dependencies=[Depends(apply_chaos)])

COLUMNS = "id, sku, name, category, description, price_cents, stock, rating"
# Whitelisted ORDER BY clauses: user input never goes into SQL text directly.
SORTS = {
    "featured": "id",
    "price_asc": "price_cents ASC",
    "price_desc": "price_cents DESC",
    "rating": "rating DESC, id",
    "name": "name ASC",
}

# FLAW (memory_leak): a "performance" cache for search results.
# The key includes free text typed by users, so the number of keys is unbounded,
# nothing is ever evicted, and every entry also keeps a full copy of the catalogue
# "for recommendations". Memory grows with every new search term until the
# container hits its memory limit and gets OOM-killed.
_search_cache: dict[str, dict] = {}


@router.get("/categories")
def categories():
    with db.connection() as conn, db.timed("select_categories"):
        return conn.execute(
            "SELECT category AS name, count(*) AS products FROM products GROUP BY category ORDER BY category"
        ).fetchall()


@router.get("/products")
def list_products(
    category: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=100),
    sort: str = "featured",
):
    q = q.strip() if q else None
    cache_key = f"{category}|{q}|{sort}"
    if flaws.on("memory_leak") and q:
        hit = _search_cache.get(cache_key)
        if hit is not None:
            return hit["results"]

    sql = f"SELECT {COLUMNS} FROM products WHERE TRUE"
    params: list = []
    if category:
        sql += " AND category = %s"
        params.append(category)
    if q:
        sql += " AND (name ILIKE %s OR description ILIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    sql += f" ORDER BY {SORTS.get(sort, 'id')}"

    with db.connection() as conn:
        with db.timed("select_products"):
            rows = conn.execute(sql, params).fetchall()
        if flaws.on("memory_leak") and q:
            with db.timed("select_recommendations"):
                suggestions = conn.execute(f"SELECT {COLUMNS} FROM products ORDER BY rating DESC").fetchall()
            _search_cache[cache_key] = {
                "results": rows,
                "suggestions": suggestions,
                # "Pre-render" the suggestions for every sort order so later requests are instant.
                "rendered": {name: json.dumps(suggestions, default=str) for name in SORTS},
                "cached_at": time.time(),
            }

    if not category and not q:
        for row in rows:
            metrics.PRODUCT_STOCK.labels(sku=row["sku"]).set(row["stock"])
    return rows


@router.get("/products/{product_id}")
def product_detail(product_id: int):
    with db.connection() as conn:
        with db.timed("select_product"):
            product = conn.execute(f"SELECT {COLUMNS} FROM products WHERE id = %s", (product_id,)).fetchone()
        if product is None:
            raise HTTPException(404, detail={"reason": "not_found", "message": "Product not found."})
        with db.timed("select_related"):
            related = conn.execute(
                f"SELECT {COLUMNS} FROM products WHERE category = %s AND id <> %s ORDER BY rating DESC LIMIT 4",
                (product["category"], product_id),
            ).fetchall()
    return {**product, "related": related}
