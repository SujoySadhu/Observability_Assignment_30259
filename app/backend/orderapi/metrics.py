"""Every Prometheus metric the Order API exposes, in one place.

Naming rules followed (from the Prometheus naming guide):
  * snake_case, base units in the name (_seconds, _dollars, _units)
  * counters end in _total (the client library adds it)
  * every label has a small, fixed set of values -> bounded cardinality

Signal map:
  RED  (Rate, Errors, Duration)   -> http_requests_total, http_request_duration_seconds
  USE  (Utilization, Saturation)  -> db_pool_*, http_requests_in_progress
  Business                        -> orders_created_total, orders_failed_total, order_value_dollars
  Dependencies                    -> payment_*, db_query_*
"""
from prometheus_client import Counter, Gauge, Histogram, Info

HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
DB_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

# ---- HTTP layer (RED) --------------------------------------------------------
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time from receiving a request to finishing the response.",
    ["method", "route"],
    buckets=HTTP_BUCKETS,
)
HTTP_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests currently being handled (a saturation signal).",
    ["method"],
)

# ---- Business events ---------------------------------------------------------
ORDERS_CREATED = Counter(
    "orders_created_total",
    "Orders successfully placed.",
    ["payment_method"],
)
ORDERS_FAILED = Counter(
    "orders_failed_total",
    "Checkout attempts that did not create an order, by reason.",
    # validation | empty_cart | invalid_coupon | out_of_stock | payment_declined
    # | payment_timeout | db_error | injected
    ["reason"],
)
ORDER_VALUE = Histogram(
    "order_value_dollars",
    "Value of successfully placed orders.",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
)
ORDER_ITEMS = Histogram(
    "order_items_per_order",
    "Number of units in each placed order.",
    buckets=(1, 2, 3, 5, 8, 13, 21),
)
AUTH_EVENTS = Counter(
    "auth_events_total",
    "Registrations, logins and logouts, by result.",
    ["event", "result"],  # event: register | login | logout ; result: success | failure
)
CART_OPERATIONS = Counter(
    "cart_operations_total",
    "Cart changes made by customers.",
    ["action"],  # add | update | remove
)
COUPON_CHECKS = Counter(
    "coupon_checks_total",
    "Coupon codes checked, by result. The code itself is NOT a label: users can type anything.",
    ["result"],  # valid | unknown | expired | min_order_not_met
)
PRODUCT_STOCK = Gauge(
    "product_stock_units",
    "Units in stock per product (a gauge: goes up and down).",
    ["sku"],
)

# ---- Downstream dependency: payment gateway (simulated) ----------------------
PAYMENT_REQUESTS = Counter(
    "payment_requests_total",
    "Calls to the payment gateway, by result.",
    ["method", "result"],  # result: approved | declined | timeout
)
PAYMENT_DURATION = Histogram(
    "payment_duration_seconds",
    "Payment gateway call latency.",
    ["method"],
    buckets=HTTP_BUCKETS,
)

# ---- Downstream dependency: PostgreSQL ---------------------------------------
DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "Database query latency, by logical operation.",
    ["operation"],
    buckets=DB_BUCKETS,
)
DB_ERRORS = Counter(
    "db_errors_total",
    "Database operations that raised an error.",
    ["operation"],
)
DB_POOL_CONNECTIONS = Gauge(
    "db_pool_connections",
    "Pool connections: managed = open or being opened, idle = ready to hand out.",
    ["state"],
)
DB_POOL_WAITING = Gauge(
    "db_pool_waiting_requests",
    "Requests queued for a database connection (pool saturation). psycopg_pool "
    "removes timed-out waiters lazily, so this can stay high while the DB is down.",
)

# ---- Fault injection state (lets dashboards explain a demo failure) -----------
CHAOS = Gauge(
    "chaos_injection",
    "Currently active fault injection settings.",
    ["type"],  # extra_latency_ms | error_rate | payment_failure_rate
)

# ---- Build info: the "info metric" pattern (value is always 1) ----------------
BUILD_INFO = Info("order_api_build", "Order API build information.")
