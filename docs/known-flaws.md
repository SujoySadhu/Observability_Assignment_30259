# Known flaws (deliberate, for learning observability)

ShopLite ships with four realistic bugs. Each one shows up in a **different signal**.
The exercise: find each one in Grafana first, *then* read its section here to confirm it.

Switch them on or off with the `FLAWS` variable in `.env`:

```bash
FLAWS=slow_queries,memory_leak,coupon_bug,slow_login   # default: all on
FLAWS=                                                 # all off ("fixed" build)
```

Then run `docker compose up -d api`. Compare the dashboards before and after.

| Flaw | Symptom | Where you see it | Signal type |
|---|---|---|---|
| `slow_queries` | "My orders" page is slow, and gets slower over time | p95 latency by route, `db_query_duration_seconds` | Metrics (latency) |
| `memory_leak` | API memory climbs steadily, then the container restarts | `process_resident_memory_bytes`, `up` drops, restart count | Metrics (saturation) |
| `coupon_bug` | Applying coupon `FLAT15` shows "something went wrong" | 5xx rate on `/api/cart` and `/api/orders`, plus a stack trace in logs | Metrics + logs |
| `slow_login` | Login takes about 1–2 s; host CPU jumps during login bursts | p95 of `/api/auth/login`, Node Exporter CPU % | Metrics (host + app) |

---

## 1. `slow_queries`: missing indexes + N+1 queries

**Cause**
- `orders.user_id` and `order_items.order_id` have **no index**. Postgres does *not* index foreign keys automatically. Every lookup is a sequential scan over 100k orders and roughly 250k order lines, and the tables grow as traffic places orders.
- `GET /api/orders` runs **1 + N queries**: the order list, then one query per order for its lines. Each of those is another sequential scan. The cart has the same N+1 pattern.

**Find it**
```promql
histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))
sum by (operation) (rate(db_query_duration_seconds_count[5m]))     # select_order_items dominates
histogram_quantile(0.95, sum by (le, operation) (rate(db_query_duration_seconds_bucket[5m])))
```

**Fix**: `app/db/fix-indexes.sql` (indexes) and `FLAWS` without `slow_queries` (single JOIN query).

## 2. `memory_leak`: unbounded search cache

**Cause**: `catalog.py` caches search results in a Python dict, keyed by the free text users type. Keys are unbounded, nothing is evicted, and each entry also stores a full catalogue copy "for recommendations". The container has `mem_limit: 512m`, so the kernel eventually OOM-kills it and Docker restarts it.

**Find it**
```promql
process_resident_memory_bytes{job="app"}
deriv(process_resident_memory_bytes{job="app"}[15m])    # positive and steady = leak
changes(process_start_time_seconds{job="app"}[1h])      # restarts
```
Also check: `docker inspect obs-api-1 --format '{{.State.OOMKilled}} {{.RestartCount}}'`

**Fix**: a bounded LRU cache with a TTL, and never key a cache directly on raw user input.

## 3. `coupon_bug`: unhandled exception on fixed-amount coupons

**Cause**: `compute_totals()` assumes every coupon has `percent_off`. `FLAT15` is a fixed $15 coupon (`percent_off = NULL`), so `subtotal * None` raises `TypeError`, which returns HTTP 500.

**Find it**
```promql
sum by (route) (rate(http_requests_total{status=~"5.."}[5m]))
```
```logql
{container="api"} | json | level="error" |= "TypeError"
```
Note that `orders_failed_total` does **not** count this failure. The crash happens before the code that records business failures. The business metric misses it; the generic RED metric catches it.

**Fix**: handle both coupon types (see the `else` branches in `compute_totals`).

## 4. `slow_login`: password hashing set too expensive

**Cause**: PBKDF2-SHA256 with 3,000,000 iterations, 5× the OWASP recommendation of 600,000. Each login or registration burns about 1 s of CPU, so concurrent logins saturate the CPU cores.

**Find it**
```promql
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/api/auth/login"}[5m])))
100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])))
rate(process_cpu_seconds_total{job="app"}[1m])          # API process CPU in cores
```

**Fix**: use 600,000 iterations (or argon2id), and re-hash old passwords on their next successful login. Hashes keep the iteration count they were created with, so changing the constant only helps new passwords.
