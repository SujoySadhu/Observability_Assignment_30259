#!/usr/bin/env bash
# Three traffic phases for the demo: normal -> high -> controlled failure.
# Saves application metric values before and after into evidence/.
#
#   ./scripts/traffic-test.sh                  # 60 s per phase
#   DUR=30 ./scripts/traffic-test.sh           # shorter phases
set -euo pipefail

API="${API:-http://localhost:8000}"
DUR="${DUR:-60}"
HERE="$(cd "$(dirname "$0")" && pwd)"
EVIDENCE="$HERE/../evidence"
mkdir -p "$EVIDENCE"

snapshot() {
  curl -fsS "$API/metrics" \
    | grep -E '^(http_requests_total|orders_created_total|orders_failed_total|http_request_duration_seconds_count)' \
    | sort > "$1"
  echo "  saved $(wc -l < "$1") metric lines to $1"
}

chaos() {
  curl -fsS -X PUT "$API/api/admin/chaos" -H 'Content-Type: application/json' -d "$1" > /dev/null
}

trap 'curl -fsS -X POST "$API/api/admin/chaos/reset" > /dev/null || true' EXIT

curl -fsS "$API/health" > /dev/null || { echo "API not reachable at $API"; exit 1; }

echo "== Snapshot BEFORE"
snapshot "$EVIDENCE/metrics-before.txt"

echo "== Phase 1: normal traffic (2 shoppers for ${DUR}s)"
python3 "$HERE/loadgen.py" --target "$API" --users 2 --duration "$DUR" --quiet

echo "== Phase 2: high traffic (20 shoppers for ${DUR}s)"
python3 "$HERE/loadgen.py" --target "$API" --users 20 --duration "$DUR" --quiet

echo "== Phase 3: controlled failure (30% injected 5xx, +300 ms latency, 5 shoppers for ${DUR}s)"
chaos '{"extra_latency_ms": 300, "error_rate": 0.3, "payment_failure_rate": 0.03}'
python3 "$HERE/loadgen.py" --target "$API" --users 5 --duration "$DUR" --quiet 2> "$EVIDENCE/failure-phase-errors.log" || true
echo "  $(wc -l < "$EVIDENCE/failure-phase-errors.log") error lines written to evidence/failure-phase-errors.log"
curl -fsS -X POST "$API/api/admin/chaos/reset" > /dev/null

echo "== Snapshot AFTER"
snapshot "$EVIDENCE/metrics-after.txt"

echo "== What changed"
diff "$EVIDENCE/metrics-before.txt" "$EVIDENCE/metrics-after.txt" || true
