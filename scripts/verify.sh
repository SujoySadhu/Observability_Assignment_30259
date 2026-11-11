#!/usr/bin/env bash
# Checks every part of the project and prints PASS / FAIL for each.
# Usage: ./scripts/verify.sh
set -u

HOST=192.168.56.20
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a          # Grafana password for the API checks
PASS=0
FAIL=0

# check "description" command  -> runs the command, prints PASS or FAIL
check() {
  local description="$1"; shift
  if "$@" > /dev/null 2>&1; then
    echo "PASS  $description"; PASS=$((PASS + 1))
  else
    echo "FAIL  $description"; FAIL=$((FAIL + 1))
  fi
}

# Is this Prometheus target up? (value "1")
target_up() {
  curl -fsG "http://$HOST:9090/api/v1/query" --data-urlencode "query=up{job=\"$1\"}" \
    | jq -e '.data.result[0].value[1] == "1"'
}

# Did Loki receive logs from the Kubernetes namespace shop-worker in the last hour?
loki_has_k8s_logs() {
  curl -fsG "http://$HOST:3100/loki/api/v1/query_range" \
    --data-urlencode 'query={namespace="shop-worker"}' --data-urlencode 'limit=1' \
    | jq -e '.data.result | length > 0'
}

# Call the Grafana API as admin
grafana_get() {
  curl -fs -u "admin:$GRAFANA_ADMIN_PASSWORD" "http://$HOST:3000$1"
}

echo "== Application"
check "ShopLite API answers /health"         curl -fs "http://$HOST:8000/health"
check "ShopLite API exposes /metrics"        curl -fs "http://$HOST:8000/metrics"
check "ShopLite web page loads"              curl -fs "http://$HOST:8080/"

echo "== Metrics"
check "Prometheus target 'node' is UP"         target_up node
check "Prometheus target 'shoplite-api' is UP" target_up shoplite-api

echo "== Kubernetes logs"
check "MicroK8s node is Ready"               sh -c "kubectl get nodes | grep -q ' Ready'"
check "order-worker pod is running"          sh -c "kubectl -n shop-worker get pods | grep -q Running"
check "Alloy pod is running"                 sh -c "kubectl -n alloy get pods | grep -q Running"
check "Loki has logs from namespace shop-worker" loki_has_k8s_logs

echo "== Grafana"
check "Grafana is healthy"                   curl -fs "http://$HOST:3000/api/health"
check "Dashboard 'shoplite-overview' loaded" grafana_get /api/dashboards/uid/shoplite-overview
check "Alert rule 'shoplite-api-down' loaded" grafana_get /api/v1/provisioning/alert-rules/shoplite-api-down

echo "== Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]        # exit code 0 only if everything passed
