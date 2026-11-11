"""Checkout (POST /api/orders) and order history."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, flaws, metrics, payment
from .cart import CouponError, compute_totals, load_cart, lookup_coupon
from .deps import apply_chaos, current_user
from .logs import log

logger = logging.getLogger("orderapi")
router = APIRouter(prefix="/api/orders", dependencies=[Depends(apply_chaos)])

ORDER_COLUMNS = (
    "id, status, subtotal_cents, discount_cents, shipping_cents, total_cents, coupon_code, "
    "payment_method, shipping_name, shipping_address, shipping_city, created_at"
)
ITEMS_SQL = (
    "SELECT oi.product_id, p.sku, p.name, p.category, oi.quantity, oi.unit_price_cents "
    "FROM order_items oi JOIN products p ON p.id = oi.product_id WHERE oi.order_id = %s ORDER BY oi.id"
)


class CheckoutIn(BaseModel):
    payment_method: Literal["card", "wallet", "cash"]
    shipping_name: str = Field(min_length=1, max_length=80)
    shipping_address: str = Field(min_length=3, max_length=200)
    shipping_city: str = Field(min_length=2, max_length=60)
    coupon_code: str | None = Field(default=None, max_length=40)


def order_failed(reason: str, status: int, message: str, **fields) -> HTTPException:
    """Count + log a failed checkout and build the HTTP error to raise."""
    metrics.ORDERS_FAILED.labels(reason=reason).inc()
    log(logger, logging.ERROR if status >= 500 else logging.WARNING, f"checkout failed: {message}",
        reason=reason, **fields)
    return HTTPException(status, detail={"reason": reason, "message": message})


@router.post("", status_code=201)
def checkout(body: CheckoutIn, user: dict = Depends(current_user)):
    # 1. Read the cart and validate the coupon.
    with db.connection() as conn:
        items = load_cart(conn, user["id"])
        if not items:
            raise order_failed("empty_cart", 400, "Your cart is empty.", user_id=user["id"])
        coupon = None
        if body.coupon_code:
            subtotal = sum(i["price_cents"] * i["quantity"] for i in items)
            try:
                coupon = lookup_coupon(conn, body.coupon_code, subtotal)
            except CouponError as exc:
                raise order_failed(exc.reason, 400, exc.message, user_id=user["id"])

    totals = compute_totals(items, coupon)  # coupon_bug lives in here

    # 2. Check stock before charging money.
    for item in items:
        if item["stock"] < item["quantity"]:
            raise order_failed("out_of_stock", 409, f"Only {item['stock']} x {item['name']} left in stock.",
                               user_id=user["id"], sku=item["sku"], requested=item["quantity"], available=item["stock"])

    # 3. Charge via the (simulated) payment gateway.
    result = payment.charge(totals["total_cents"], body.payment_method)
    if result == "declined":
        raise order_failed("payment_declined", 402, "Your payment was declined. Please try another method.",
                           user_id=user["id"], payment_method=body.payment_method)
    if result == "timeout":
        raise order_failed("payment_timeout", 504, "The payment service timed out. You have not been charged.",
                           user_id=user["id"], payment_method=body.payment_method)

    # 4. One transaction: reserve stock for every line, write order + lines, empty the cart.
    #    Any exception inside the block rolls everything back.
    stock_after: dict[str, int] = {}
    with db.connection() as conn:
        for item in items:
            with db.timed("reserve_stock"):
                row = conn.execute(
                    "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s RETURNING stock",
                    (item["quantity"], item["id"], item["quantity"]),
                ).fetchone()
            if row is None:
                raise order_failed("out_of_stock", 409, f"{item['name']} sold out during checkout. You have been refunded.",
                                   user_id=user["id"], sku=item["sku"])
            stock_after[item["sku"]] = row["stock"]
        with db.timed("insert_order"):
            order = conn.execute(
                "INSERT INTO orders (user_id, subtotal_cents, discount_cents, shipping_cents, total_cents, coupon_code, "
                "payment_method, shipping_name, shipping_address, shipping_city) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at",
                (user["id"], totals["subtotal_cents"], totals["discount_cents"], totals["shipping_cents"],
                 totals["total_cents"], coupon["code"] if coupon else None, body.payment_method,
                 body.shipping_name, body.shipping_address, body.shipping_city),
            ).fetchone()
        with db.timed("insert_order_items"):
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) VALUES (%s, %s, %s, %s)",
                    [(order["id"], i["id"], i["quantity"], i["price_cents"]) for i in items],
                )
        with db.timed("clear_cart"):
            conn.execute("DELETE FROM cart_items WHERE user_id = %s", (user["id"],))

    # 5. Business metrics + log.
    for sku, stock in stock_after.items():
        metrics.PRODUCT_STOCK.labels(sku=sku).set(stock)
    metrics.ORDERS_CREATED.labels(payment_method=body.payment_method).inc()
    metrics.ORDER_VALUE.observe(totals["total_cents"] / 100)
    metrics.ORDER_ITEMS.observe(totals["units"])
    log(logger, logging.INFO, "order created", order_id=order["id"], user_id=user["id"],
        total_cents=totals["total_cents"], units=totals["units"], payment_method=body.payment_method,
        coupon=coupon["code"] if coupon else None)
    return {"id": order["id"], "created_at": order["created_at"], **totals}


@router.get("")
def order_history(user: dict = Depends(current_user)):
    with db.connection() as conn:
        if flaws.on("slow_queries"):
            # FLAW: no index on orders.user_id -> sequential scan of every order ever placed...
            with db.timed("select_orders"):
                orders = conn.execute(
                    f"SELECT {ORDER_COLUMNS} FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
                    (user["id"],),
                ).fetchall()
            # ...then N+1: one more query per order, each a sequential scan of order_items
            # (no index on order_items.order_id).
            for order in orders:
                with db.timed("select_order_items"):
                    order["items"] = conn.execute(ITEMS_SQL, (order["id"],)).fetchall()
            return orders
        # Fixed version: one round trip that aggregates the lines as JSON.
        with db.timed("select_orders"):
            return conn.execute(
                f"SELECT o.{ORDER_COLUMNS.replace(', ', ', o.')}, "
                "coalesce(json_agg(json_build_object('product_id', oi.product_id, 'sku', p.sku, 'name', p.name, "
                "'category', p.category, 'quantity', oi.quantity, 'unit_price_cents', oi.unit_price_cents) "
                "ORDER BY oi.id) FILTER (WHERE oi.id IS NOT NULL), '[]') AS items "
                "FROM (SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 20) o "
                "LEFT JOIN order_items oi ON oi.order_id = o.id LEFT JOIN products p ON p.id = oi.product_id "
                "GROUP BY o.id, o.status, o.subtotal_cents, o.discount_cents, o.shipping_cents, o.total_cents, "
                "o.coupon_code, o.payment_method, o.shipping_name, o.shipping_address, o.shipping_city, o.created_at "
                "ORDER BY o.created_at DESC",
                (user["id"],),
            ).fetchall()


@router.get("/{order_id}")
def order_detail(order_id: int, user: dict = Depends(current_user)):
    with db.connection() as conn:
        with db.timed("select_order"):
            order = conn.execute(
                f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = %s AND user_id = %s", (order_id, user["id"])
            ).fetchone()
        if order is None:
            raise HTTPException(404, detail={"reason": "not_found", "message": "Order not found."})
        with db.timed("select_order_items"):
            order["items"] = conn.execute(ITEMS_SQL, (order_id,)).fetchall()
    return order
