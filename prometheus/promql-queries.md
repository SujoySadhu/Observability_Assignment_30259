# PromQL queries (Task 4)

All counters only go up, so we never graph them raw. `rate(x[1m])` = average
per-second increase over the last minute. Window >= 4 x scrape interval (15s).

## 1. CPU usage %
    100 * (1 - avg(rate(node_cpu_seconds_total{job="node", mode="idle"}[1m])))
- node_cpu_seconds_total counts seconds each CPU spent in each mode (from /proc/stat).
- rate(...mode="idle") = fraction of each second a CPU was idle (0..1), one series per CPU.
- avg() across the 4 CPUs, then 1 - idle = busy. x100 = percent.

## 2. RAM usage %
    100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})
- Gauges from /proc/meminfo, so no rate().
- Uses MemAvailable, NOT MemFree: Linux fills spare RAM with page cache, which is
  given back on demand. MemFree would wrongly show the VM as ~95% full.

## 3. Application requests per second
    sum(rate(http_requests_total{job="shoplite-api", route!~"/health|/ready|/metrics"}[1m]))
- http_requests_total is a counter; rate() turns it into requests/second.
- Excludes /health (Docker healthcheck) and /metrics (Prometheus' own scrape)
  so the number is customer traffic only. sum() adds all routes/status codes.

## 4. Error rate % (server errors)
    100 * sum(rate(http_requests_total{job="shoplite-api", status=~"5.."}[5m]))
        / sum(rate(http_requests_total{job="shoplite-api", route!~"/health|/ready|/metrics"}[5m]))
- 5xx = the server's fault (crash, DB down). 4xx (bad input, not logged in) are the
  client's fault and are not counted as errors.
- Uses the HTTP status counter, not orders_failed_total: an unexpected crash
  (the FLAT15 TypeError) never reaches the business counter but is always a 500.
- Empty result = no traffic in the window (0/0), not "0 % errors".

## 5. p95 request latency (seconds)
    histogram_quantile(0.95,
      sum by (le) (rate(http_request_duration_seconds_bucket{job="shoplite-api", route!~"/health|/ready|/metrics"}[5m])))
- Each bucket counts requests that took <= le seconds (cumulative).
- rate() per bucket, sum by (le) merges all routes but keeps the bucket boundaries.
- histogram_quantile finds the bucket where 95 % of requests are reached and
  interpolates inside it: "95 % of requests were faster than this".
- Accuracy is limited by the bucket boundaries (0.25, 0.5, 1, 2.5 ...).

## Extra host measurements
    Disk used %:  100 * (1 - node_filesystem_avail_bytes{job="node",mountpoint="/"} / node_filesystem_size_bytes{job="node",mountpoint="/"})
    Network in:   sum(rate(node_network_receive_bytes_total{job="node", device!~"lo|veth.*|cali.*|docker.*|br-.*|vxlan.*"}[1m]))
    Network out:  sum(rate(node_network_transmit_bytes_total{job="node", device!~"lo|veth.*|cali.*|docker.*|br-.*|vxlan.*"}[1m]))
    Uptime (s):   time() - node_boot_time_seconds{job="node"}
- Network excludes loopback and the virtual interfaces of Docker/Calico, so it
  counts only real NICs (enp0s3 = NAT/internet, eth1 = host-only).
