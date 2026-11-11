-- The FIX for the "slow database queries" flaw (part 1: missing indexes).
-- Run it only after you have observed the problem in Grafana:
--   docker compose exec -T postgres psql -U orders -d orders < app/db/fix-indexes.sql
-- Then compare p95 of GET /api/orders and db_query_duration_seconds before/after.

CREATE INDEX IF NOT EXISTS orders_user_id_created_at_idx ON orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS order_items_order_id_idx      ON order_items (order_id);
ANALYZE orders;
ANALYZE order_items;
