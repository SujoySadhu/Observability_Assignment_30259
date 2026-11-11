# ShopLite: observability assessment project

> Work in progress. This README currently covers the **application** only.
> Prometheus, Grafana, Loki, Node Exporter, MicroK8s/Alloy and alerting are added in later steps.

## The application

ShopLite is a small online electronics store. It is the system we observe.

```
Browser ──► web (nginx :8080) ──/api──► api (FastAPI :8000) ──► postgres 17
            static SPA + proxy           │                       users, sessions, products,
                                         │                       carts, coupons, orders (100k seeded)
                                         └──► payment gateway (simulated: latency tail, declines, timeouts)
```

**Customer features:** registration and login, categories, search, sorting, product pages with
related items, a persistent cart with quantity changes, coupon codes, checkout with shipping and
payment method, order history and order details.

| Service | What it does | Port (localhost only) |
|---|---|---|
| `web` | Single-page storefront (plain JS) + reverse proxy to the API | `127.0.0.1:8080` |
| `api` | REST API, Prometheus `/metrics`, JSON logs | `127.0.0.1:8000` |
| `postgres` | Data; named volume `pgdata` | not published |

### API

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` · `/ready` · `/metrics` | – | liveness · readiness (checks DB) · Prometheus |
| POST | `/api/auth/register` · `/api/auth/login` | – | returns a bearer token (server-side session) |
| POST/GET | `/api/auth/logout` · `/api/auth/me` | ✓ | |
| GET | `/api/categories` · `/api/products?category=&q=&sort=` · `/api/products/{id}` | – | catalogue |
| GET | `/api/cart?coupon=CODE` | ✓ | cart + totals (coupon preview) |
| POST/PATCH/DELETE | `/api/cart/items[/{product_id}]` | ✓ | add · set quantity (0 removes) · remove |
| POST | `/api/orders` | ✓ | **checkout**: 201 · 400 empty cart / bad coupon · 402 declined · 409 out of stock · 422 invalid · 504 payment timeout · 503 DB down |
| GET | `/api/orders` · `/api/orders/{id}` | ✓ | order history / details |
| GET/PUT/POST | `/api/admin/chaos[/reset]` · `/api/admin/restock` | – | operator tools (local only) |

Interactive docs: http://localhost:8000/docs

### Custom metrics

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` / `http_request_duration_seconds` / `http_requests_in_progress` | counter / histogram / gauge | method, route, status |
| `orders_created_total` · `orders_failed_total` | counter | payment_method · reason |
| `order_value_dollars` · `order_items_per_order` | histogram | – |
| `auth_events_total` | counter | event (register/login/logout), result |
| `cart_operations_total` · `coupon_checks_total` | counter | action · result |
| `product_stock_units` | gauge | sku (24 products) |
| `payment_requests_total` / `payment_duration_seconds` | counter / histogram | method, result |
| `db_query_duration_seconds` / `db_errors_total` | histogram / counter | operation |
| `db_pool_connections` / `db_pool_waiting_requests` | gauge | state |
| `chaos_injection` · `order_api_build_info` | gauge · info | type · version |

Every label has a small, fixed set of values. `route` is the route *template*, and
coupon codes typed by users are **not** labels, so cardinality stays bounded.

### Deliberate flaws

The app contains four realistic bugs to find with observability tools: slow queries (N+1 queries
plus missing indexes), a memory leak, a coupon bug that causes 500s, and a CPU-heavy login.
Toggle them with `FLAWS` in `.env`. Details and fixes: [docs/known-flaws.md](docs/known-flaws.md).

## Run it (inside Ubuntu / WSL2)

```bash
cp .env.example .env          # set a real POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps             # all three services should be "healthy"
```

The first start seeds 100,000 historical orders, which takes about 20 seconds.

- Shop: http://localhost:8080 (create an account, then shop)
- API docs: http://localhost:8000/docs · Metrics: http://localhost:8000/metrics

## Generate traffic and failures

```bash
python3 scripts/loadgen.py --users 10 --duration 300   # 10 simulated shoppers (~10 req/s)
./scripts/traffic-test.sh                              # normal -> high -> failure; saves evidence/
./scripts/chaos.sh errors 30                           # 30% of /api requests return 500
./scripts/chaos.sh latency 400                         # +400 ms per request
./scripts/chaos.sh reset
```

## Clean up

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and delete the database volume
```
