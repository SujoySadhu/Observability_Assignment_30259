#!/usr/bin/env bash
# Controlled failure injection for demos (operator tool, not part of the shop UI).
#
#   ./scripts/chaos.sh status
#   ./scripts/chaos.sh errors 30      # 30% of /api requests fail with HTTP 500
#   ./scripts/chaos.sh latency 400    # add ~400 ms to every /api request
#   ./scripts/chaos.sh payments 50    # 50% of card/wallet payments are declined
#   ./scripts/chaos.sh reset          # back to normal
#
# Settings combine: "errors 30" then "latency 400" gives both.
set -euo pipefail

API="${API:-http://localhost:8000}"
put() { curl -fsS -X PUT "$API/api/admin/chaos" -H 'Content-Type: application/json' -d "$1"; echo; }
pct() { awk -v p="$1" 'BEGIN { printf "%.4f", p / 100 }'; }

case "${1:-status}" in
  status)   curl -fsS "$API/api/admin/chaos"; echo ;;
  errors)   put "{\"error_rate\": $(pct "${2:?percent}")}" ;;
  latency)  put "{\"extra_latency_ms\": ${2:?milliseconds}}" ;;
  payments) put "{\"payment_failure_rate\": $(pct "${2:?percent}")}" ;;
  reset)    curl -fsS -X POST "$API/api/admin/chaos/reset"; echo ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
