#!/usr/bin/env python3
"""Realistic shopper simulator for ShopLite.

Each "virtual user" runs shopping sessions in a loop: register or log in,
browse categories, search, open products, fill a cart, sometimes try a coupon,
check out, look at past orders and log out, with think time between clicks.
Some sessions are anonymous browsers, and some users mistype their password.

Standard library only, so it runs anywhere python3 exists: your laptop, or a
Kubernetes pod (python image + this file in a ConfigMap).

Logging contract (one JSON object per line):
  * 2xx and expected 4xx results -> stdout
  * 5xx and network errors       -> stderr   (Kubernetes keeps the two streams apart)

Examples
  python3 loadgen.py --users 5 --duration 60            # ~5 req/s
  python3 loadgen.py --users 25 --duration 60 --quiet   # high traffic, summaries only
  TARGET=http://api:8000 USERS=5 python3 loadgen.py     # configured by env vars (K8s)
"""
import argparse
import json
import os
import random
import signal
import string
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

FIRST = ["Rahim", "Karim", "Ayesha", "Nusrat", "Tanvir", "Sadia", "Imran", "Farzana", "Arif", "Mitu"]
CITIES = ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi"]
CATEGORIES = ["laptops", "phones", "audio", "accessories", "gaming", "smart-home"]
SEARCH_WORDS = ["laptop", "phone", "wireless", "usb-c", "gaming", "speaker", "charger", "monitor",
                "smart", "pro", "mini", "keyboard", "mouse", "headphones", "camera", "cable"]
COUPONS = ["WELCOME10", "SAVE20", "FLAT15", "SUMMER25", "FREESTUFF"]   # valid, min-order, buggy, expired, unknown
SORTS = ["featured", "price_asc", "price_desc", "rating", "name"]

stop = threading.Event()
stats = Counter()
stats_lock = threading.Lock()
accounts: list[tuple[str, str]] = []          # (email, password) created by this run
accounts_lock = threading.Lock()
QUIET = False
TARGET = "http://192.168.56.20:8000"
THINK = 1.0


def log(stream, level, msg, **fields):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "level": level,
             "service": "loadgen", "msg": msg, **fields}
    print(json.dumps(entry), file=stream, flush=True)


class Session:
    """One shopper's browser session."""

    def __init__(self, vu: int):
        self.vu = vu
        self.token = None

    def call(self, action, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(TARGET + path, data=data, method=method, headers=headers)
        started = time.perf_counter()
        status, request_id, error, payload = 0, None, None, None
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                status, request_id = res.status, res.headers.get("X-Request-ID")
                raw = res.read()
                payload = json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            status, request_id = exc.code, exc.headers.get("X-Request-ID")
            exc.read()
        except Exception as exc:  # connection refused, timeout, DNS failure...
            error = f"{type(exc).__name__}: {exc}"
        ms = round((time.perf_counter() - started) * 1000, 1)
        with stats_lock:
            stats[status] += 1
        fields = dict(vu=self.vu, action=action, method=method, path=path.split("?")[0],
                      status=status, duration_ms=ms, request_id=request_id)
        if status == 0 or status >= 500:
            log(sys.stderr, "error", "request failed", error=error, **fields)
        elif not QUIET:
            log(sys.stdout, "warn" if status >= 400 else "info", "request completed", **fields)
        return status, payload

    def think(self):
        stop.wait(random.uniform(0.5 * THINK, 1.5 * THINK))
        return not stop.is_set()

    # ---- steps -------------------------------------------------------------
    def browse(self):
        products = []
        steps = random.randint(2, 5)
        for _ in range(steps):
            roll = random.random()
            if roll < 0.35:
                _, data = self.call("browse_category", "GET",
                                    f"/api/products?category={random.choice(CATEGORIES)}&sort={random.choice(SORTS)}")
            elif roll < 0.65:
                # Real users type all sorts of things: this keeps feeding the search cache.
                term = random.choice(SEARCH_WORDS)
                if random.random() < 0.6:
                    term += " " + "".join(random.choices(string.ascii_lowercase, k=random.randint(2, 5)))
                _, data = self.call("search", "GET", f"/api/products?q={urllib.request.quote(term)}")
            else:
                _, data = self.call("browse_all", "GET", "/api/products")
            if isinstance(data, list):
                products += [p for p in data if p.get("stock", 0) > 0]
            if products and random.random() < 0.7:
                self.call("view_product", "GET", f"/api/products/{random.choice(products)['id']}")
            if not self.think():
                return []
        return products

    def login_or_register(self):
        with accounts_lock:
            existing = random.choice(accounts) if accounts and random.random() < 0.6 else None
        if existing:
            email, password = existing
            if random.random() < 0.08:  # fat-fingered password
                self.call("login_bad_password", "POST", "/api/auth/login", {"email": email, "password": password + "x"})
                self.think()
            status, data = self.call("login", "POST", "/api/auth/login", {"email": email, "password": password})
        else:
            email = f"shopper-{uuid.uuid4().hex[:10]}@loadgen.shoplite.test"
            password = uuid.uuid4().hex
            name = f"{random.choice(FIRST)} {random.choice(string.ascii_uppercase)}."
            status, data = self.call("register", "POST", "/api/auth/register",
                                     {"email": email, "name": name, "password": password})
            if status == 201:
                with accounts_lock:
                    accounts.append((email, password))
        if status in (200, 201) and data:
            self.token = data["token"]
        return self.token is not None

    def shop(self, products):
        for product in random.sample(products, k=min(len(products), random.randint(1, 3))):
            self.call("add_to_cart", "POST", "/api/cart/items",
                      {"product_id": product["id"], "quantity": random.choice([1, 1, 1, 2, 3])})
            if not self.think():
                return
        status, cart = self.call("view_cart", "GET", "/api/cart")
        if status != 200 or not cart or not cart["items"]:
            return
        if random.random() < 0.2:
            item = random.choice(cart["items"])
            self.call("update_cart", "PATCH", f"/api/cart/items/{item['id']}", {"quantity": random.randint(0, 3)})

        coupon = None
        if random.random() < 0.3:
            coupon = random.choice(COUPONS)
            status, preview = self.call("apply_coupon", "GET", f"/api/cart?coupon={coupon}")
            if status != 200 or (preview and preview.get("coupon_error")):
                coupon = None  # the shopper gives up on the coupon
        if not self.think():
            return
        if random.random() < 0.75:  # some carts are abandoned
            body = {
                "payment_method": random.choice(["card", "card", "wallet", "cash"]),
                "shipping_name": f"{random.choice(FIRST)} Customer",
                "shipping_address": f"House {random.randint(1, 99)}, Road {random.randint(1, 30)}",
                "shipping_city": random.choice(CITIES),
                "coupon_code": coupon,
            }
            if random.random() < 0.03:
                body["shipping_city"] = ""  # broken client -> 422
            self.call("checkout", "POST", "/api/orders", body)

    def history(self):
        status, orders = self.call("order_history", "GET", "/api/orders")
        if status == 200 and orders and random.random() < 0.5:
            self.call("order_detail", "GET", f"/api/orders/{random.choice(orders)['id']}")
        if random.random() < 0.05:
            self.call("order_detail_missing", "GET", f"/api/orders/{random.randint(10**8, 10**9)}")

    def run_once(self):
        self.call("categories", "GET", "/api/categories")
        products = self.browse()
        if stop.is_set() or random.random() < 0.25:
            return  # anonymous window-shopper
        if not self.login_or_register() or not self.think():
            return
        if products:
            self.shop(products)
        if not stop.is_set() and random.random() < 0.5:
            self.think()
            self.history()
        self.call("logout", "POST", "/api/auth/logout")
        self.token = None


def virtual_user(vu: int, deadline):
    session = Session(vu)
    while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
        try:
            session.run_once()
        except Exception as exc:  # never let one bad response kill the generator
            log(sys.stderr, "error", "virtual user crashed", vu=vu, error=f"{type(exc).__name__}: {exc}")
        stop.wait(random.uniform(0.5, 2.0))


def main():
    global QUIET, TARGET, THINK
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default=os.getenv("TARGET", "http://192.168.56.20:8000"))
    p.add_argument("--users", type=int, default=int(os.getenv("USERS", "3")),
                   help="concurrent shoppers (each makes roughly 1 request/second)")
    p.add_argument("--think", type=float, default=float(os.getenv("THINK", "1.0")), help="average seconds between clicks")
    p.add_argument("--duration", type=float, default=float(os.getenv("DURATION", "0")), help="seconds, 0 = forever")
    p.add_argument("--quiet", action="store_true", default=os.getenv("QUIET") == "1",
                   help="only log errors and 10-second summaries")
    args = p.parse_args()
    QUIET, TARGET, THINK = args.quiet, args.target.rstrip("/"), args.think

    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # Kubernetes sends SIGTERM on pod shutdown
    log(sys.stdout, "info", "load generator starting", target=TARGET, users=args.users, duration_s=args.duration)
    deadline = time.monotonic() + args.duration if args.duration > 0 else None

    threads = [threading.Thread(target=virtual_user, args=(i + 1, deadline), daemon=True) for i in range(args.users)]
    for i, t in enumerate(threads):
        t.start()
        stop.wait(0.2)  # ramp up gradually

    try:
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            stop.wait(10)
            with stats_lock:
                snapshot = {str(k): v for k, v in sorted(stats.items())}
            log(sys.stdout, "info", "traffic summary", status_counts=snapshot, accounts=len(accounts))
    except KeyboardInterrupt:
        pass
    stop.set()
    for t in threads:
        t.join(timeout=20)
    with stats_lock:
        log(sys.stdout, "info", "load generator finished", status_counts={str(k): v for k, v in sorted(stats.items())})


if __name__ == "__main__":
    main()
