"""Shopping cart (stored in Postgres per user) and coupon/price calculation."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import db, flaws, metrics
from .deps import apply_chaos, current_user
from .logs import log

logger = logging.getLogger("orderapi")
router = APIRouter(prefix="/api/cart", dependencies=[Depends(apply_chaos)])

FREE_SHIPPING_FROM_CENTS = 5000
SHIPPING_CENTS = 499


class AddItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=50)


class UpdateItemIn(BaseModel):
    quantity: int = Field(ge=0, le=50)  # 0 removes the item


# ---------------------------------------------------------------------------
# Helpers shared with checkout (orders.py)
# ---------------------------------------------------------------------------
def load_cart(conn, user_id: int) -> list[dict]:
    if flaws.on("slow_queries"):
        # FLAW (N+1): one query for the cart, then ONE MORE QUERY PER ITEM.
        with db.timed("select_cart"):
            lines = conn.execute(
                "SELECT product_id, quantity FROM cart_items WHERE user_id = %s ORDER BY added_at", (user_id,)
            ).fetchall()
        items = []
        for line in lines:
            with db.timed("select_cart_product"):
                product = conn.execute(
                    "SELECT id, sku, name, category, price_cents, stock FROM products WHERE id = %s",
                    (line["product_id"],),
                ).fetchone()
            items.append({**product, "quantity": line["quantity"]})
        return items
    # Fixed version: a single JOIN.
    with db.timed("select_cart"):
        return conn.execute(
            "SELECT p.id, p.sku, p.name, p.category, p.price_cents, p.stock, c.quantity "
            "FROM cart_items c JOIN products p ON p.id = c.product_id "
            "WHERE c.user_id = %s ORDER BY c.added_at",
            (user_id,),
        ).fetchall()


class CouponError(Exception):
    def __init__(self, reason: str, message: str):
        self.reason, self.message = reason, message


def lookup_coupon(conn, code: str, subtotal_cents: int) -> dict:
    """Return the coupon row or raise CouponError. Counts coupon_checks_total."""
    with db.timed("select_coupon"):
        coupon = conn.execute(
            "SELECT code, description, percent_off, amount_off_cents, min_order_cents, "
            "(expires_at IS NOT NULL AND expires_at < now()) AS expired FROM coupons WHERE code = %s",
            (code.strip().upper(),),
        ).fetchone()
    if coupon is None:
        result, error = "unknown", CouponError("invalid_coupon", "This coupon code doesn't exist.")
    elif coupon["expired"]:
        result, error = "expired", CouponError("invalid_coupon", "This coupon has expired.")
    elif subtotal_cents < coupon["min_order_cents"]:
        result = "min_order_not_met"
        error = CouponError("invalid_coupon", f"This coupon needs an order of at least ${coupon['min_order_cents'] / 100:.2f}.")
    else:
        result, error = "valid", None
    metrics.COUPON_CHECKS.labels(result=result).inc()
    if error:
        raise error
    return coupon


def compute_totals(items: list[dict], coupon: dict | None) -> dict:
    subtotal = sum(i["price_cents"] * i["quantity"] for i in items)
    discount = 0
    if coupon:
        if flaws.on("coupon_bug"):
            # FLAW (coupon_bug): assumes every coupon is a percentage. Fixed-amount
            # coupons (FLAT15) have percent_off = NULL -> None -> TypeError -> HTTP 500.
            discount = subtotal * coupon["percent_off"] // 100
        elif coupon["percent_off"] is not None:
            discount = subtotal * coupon["percent_off"] // 100
        else:
            discount = min(coupon["amount_off_cents"], subtotal)
    after_discount = subtotal - discount
    shipping = 0 if not items or after_discount >= FREE_SHIPPING_FROM_CENTS else SHIPPING_CENTS
    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "shipping_cents": shipping,
        "total_cents": after_discount + shipping,
        "units": sum(i["quantity"] for i in items),
    }


def cart_response(conn, user_id: int, coupon_code: str | None = None) -> dict:
    items = load_cart(conn, user_id)
    coupon, coupon_error = None, None
    if coupon_code and items:
        subtotal = sum(i["price_cents"] * i["quantity"] for i in items)
        try:
            coupon = lookup_coupon(conn, coupon_code, subtotal)
        except CouponError as exc:
            coupon_error = exc.message
    return {
        "items": items,
        "totals": compute_totals(items, coupon),
        "coupon": {"code": coupon["code"], "description": coupon["description"]} if coupon else None,
        "coupon_error": coupon_error,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
def get_cart(coupon: str | None = Query(default=None, max_length=40), user: dict = Depends(current_user)):
    with db.connection() as conn:
        return cart_response(conn, user["id"], coupon)


@router.post("/items", status_code=201)
def add_item(body: AddItemIn, user: dict = Depends(current_user)):
    with db.connection() as conn:
        with db.timed("select_product"):
            product = conn.execute("SELECT id, stock FROM products WHERE id = %s", (body.product_id,)).fetchone()
        if product is None:
            raise HTTPException(404, detail={"reason": "not_found", "message": "Product not found."})
        if product["stock"] < body.quantity:
            raise HTTPException(409, detail={"reason": "out_of_stock", "message": "Not enough stock."})
        with db.timed("upsert_cart_item"):
            conn.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, product_id) DO UPDATE "
                "SET quantity = LEAST(cart_items.quantity + EXCLUDED.quantity, 50)",
                (user["id"], body.product_id, body.quantity),
            )
        metrics.CART_OPERATIONS.labels(action="add").inc()
        log(logger, logging.INFO, "cart item added", user_id=user["id"], product_id=body.product_id, quantity=body.quantity)
        return cart_response(conn, user["id"])


@router.patch("/items/{product_id}")
def update_item(product_id: int, body: UpdateItemIn, user: dict = Depends(current_user)):
    with db.connection() as conn:
        if body.quantity == 0:
            with db.timed("delete_cart_item"):
                conn.execute("DELETE FROM cart_items WHERE user_id = %s AND product_id = %s", (user["id"], product_id))
            metrics.CART_OPERATIONS.labels(action="remove").inc()
        else:
            with db.timed("update_cart_item"):
                updated = conn.execute(
                    "UPDATE cart_items SET quantity = %s WHERE user_id = %s AND product_id = %s RETURNING product_id",
                    (body.quantity, user["id"], product_id),
                ).fetchone()
            if updated is None:
                raise HTTPException(404, detail={"reason": "not_in_cart", "message": "That item is not in your cart."})
            metrics.CART_OPERATIONS.labels(action="update").inc()
        return cart_response(conn, user["id"])


@router.delete("/items/{product_id}")
def remove_item(product_id: int, user: dict = Depends(current_user)):
    with db.connection() as conn:
        with db.timed("delete_cart_item"):
            conn.execute("DELETE FROM cart_items WHERE user_id = %s AND product_id = %s", (user["id"], product_id))
        metrics.CART_OPERATIONS.labels(action="remove").inc()
        return cart_response(conn, user["id"])
