# System & Application Observability — Candidate 30259

**Candidate:** Sujoy Sadhu · **ID:** 30259 · **Instructor:** Lipton Ahammed

A working observability platform on Ubuntu 26.04:
- **Metrics:** Ubuntu host (Node Exporter) + HTTP app (ShopLite) → Prometheus → Grafana
- **Logs:** a MicroK8s workload → Grafana Alloy → Loki → Grafana
- **Alerts:** Grafana alert rule → Gmail SMTP → email inbox

## Architecture

```
Windows 11 host
└── VirtualBox VM "obs-lab" (Ubuntu 26.04, 192.168.56.20, host-only network)
    ├── Docker Compose (compose.yaml)
    │   ├── ShopLite: web (nginx) :8080, api (FastAPI) :8000, postgres (no port)
    │   ├── Node Exporter :9100   reads the VM's /proc, /sys and / (read-only)
    │   ├── Prometheus    :9090   scrapes node + shoplite-api every 15 s
    │   ├── Loki          :3100   receives logs from Alloy
    │   └── Grafana       :3000   dashboards, Explore, alerting, SMTP
    └── MicroK8s (Kubernetes)
        ├── namespace shop-worker: Deployment "order-worker" (calls the API, logs INFO/ERROR)
        └── namespace alloy: Grafana Alloy (Helm) → pushes pod logs to Loki
```

| Flow | Path |
|---|---|
| Metrics | Node Exporter / api `/metrics` → Prometheus (pull, 15 s) → Grafana (PromQL) |
| Logs | pod stdout/stderr → Alloy (`loki.source.kubernetes`) → `http://192.168.56.20:3100/loki/api/v1/push` → Loki → Grafana (LogQL) |
| Alerts | Grafana rule `up{job="shoplite-api"} < 1` for 1 m → contact point `email-oncall` → `smtp.gmail.com:587` → inbox |

### How Alloy reaches Loki (networking)
Loki runs in Docker Compose and publishes port 3100 on the VM's host-only IP `192.168.56.20`.
The Alloy pod runs in MicroK8s on the same VM; its traffic to `192.168.56.20` leaves the pod
network (Calico) and reaches the VM's own interface, where Docker forwards it to the Loki container.
The order-worker reaches the ShopLite API the same way (`http://192.168.56.20:8000`).

### Security
- Every port is bound to `192.168.56.20` (VirtualBox host-only network): reachable only from this PC, never from the LAN or internet. Postgres publishes no port.
- Secrets (database, Grafana admin, SMTP App Password, recipient) live only in `.env`, which is git-ignored. `.env.example` has placeholders.
- Node Exporter mounts the host filesystem **read-only**.

## Deviations from the reference architecture
| Brief | This project | Reason |
|---|---|---|
| Ubuntu laptop | Ubuntu 26.04 in a Vagrant/VirtualBox VM | reproducible with `vagrant up`; real systemd and kernel |
| Ports on localhost | ports on host-only IP `192.168.56.20` | Kubernetes pods must reach the API and Loki; still private |
| Minimal Order API | ShopLite (shop with `/health`, `POST /api/orders`, `/metrics`) | more realistic traffic and business metrics |
| Log workload | `order-worker`, which calls the real API | its errors line up with the app's metrics and alerts |

## Repository structure
```
├── Vagrantfile                 VM definition (Ubuntu 26.04, 6 GB, 4 CPU, clock sync)
├── compose.yaml                app + observability stack
├── .env.example                settings template (copy to .env)
├── app/                        ShopLite source (backend, frontend, db)
├── prometheus/                 prometheus.yml, promql-queries.md (5 queries explained)
├── loki/config.yml             Loki single-node config
├── kubernetes/                 namespace.yaml, worker.py, workload.yaml, alloy-values.yaml
├── grafana/provisioning/       data sources, dashboard provider, alerting (contact point, policy, rule)
├── grafana/dashboards/         shoplite-overview.json (exported dashboard)
├── alerting/                   configuration-notes.md
├── scripts/                    setup-vm.sh, verify.sh, traffic-test.sh, loadgen.py, chaos.sh
├── docs/known-flaws.md         4 deliberate app flaws used for the demo
└── evidence/task1..task8       screenshots and command output
```

## Setup (from zero)

**On Windows** (VirtualBox 7.2, Vagrant 2.4), in the project folder:
```bash
vagrant up
vagrant ssh
```

**In the VM:** copy the project to the Linux disk (the shared folder breaks permissions):
```bash
mkdir -p ~/30259_observability && cp -r /vagrant/. ~/30259_observability && cd ~/30259_observability
./scripts/setup-vm.sh          # Docker Engine, MicroK8s, Helm, timezone
exit                           # log out and in again (docker/microk8s groups)
```

**Settings:**
```bash
vagrant ssh
cd ~/30259_observability
cp .env.example .env && chmod 600 .env
nano .env                      # set passwords, Gmail address + App Password, recipient
```

**Start the Compose stack:**
```bash
docker compose up -d --build
docker compose ps              # all services Up / healthy
```

**Start the Kubernetes part:**
```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl -n shop-worker create configmap order-worker-script --from-file=worker.py=kubernetes/worker.py
kubectl apply -f kubernetes/workload.yaml
helm repo add grafana https://grafana.github.io/helm-charts && helm repo update
helm install alloy grafana/alloy --version 1.5.2 -n alloy --create-namespace -f kubernetes/alloy-values.yaml
```

**Start background shoppers** (so the graphs have data):
```bash
nohup python3 scripts/loadgen.py --users 3 --quiet > /tmp/loadgen.log 2>&1 &
```

## Access (from the Windows browser)
| Service | URL |
|---|---|
| ShopLite shop | http://192.168.56.20:8080 |
| Grafana | http://192.168.56.20:3000 (admin / password from `.env`) |
| Prometheus | http://192.168.56.20:9090/targets |
| API metrics | http://192.168.56.20:8000/metrics |

Grafana → Dashboards → ShopLite → **ShopLite - Host & App Overview** (8 metric panels + Kubernetes error logs).

## Verify
```bash
./scripts/verify.sh            # expected: 12 passed, 0 failed
```

## Tests and demo
1. **Normal traffic:** dashboard with 3 background shoppers.
2. **Traffic phases + failure:** `DUR=30 ./scripts/traffic-test.sh` runs 2 users, then 20 users, then 5 users with 30 % injected 5xx and +300 ms. Before/after metrics are saved to `evidence/task3/`.
3. **Logs:** Grafana → Explore → Loki → `{namespace="shop-worker"} |= "level=ERROR"`
4. **Alert:** `docker compose stop api` → Pending (~30 s) → Firing (~1.5 min) → email.
   `docker compose start api` → Normal + RESOLVED email.
   During the outage: requests/s drops to 0 and the order-worker logs `api unreachable` (seen in Loki).

PromQL explained: `prometheus/promql-queries.md` · Alerting explained: `alerting/configuration-notes.md`

## Cleanup
```bash
pkill -f loadgen.py                                  # stop background shoppers
helm uninstall alloy -n alloy                        # remove Alloy
kubectl delete namespace shop-worker alloy           # remove the workload
docker compose down                                  # stop the stack, KEEP data (volumes)
docker compose down -v                               # stop the stack, DELETE all data
```
On Windows: `vagrant destroy` deletes the VM.

## Known issues
- **Clock drift:** VirtualBox running on Hyper-V makes the VM clock fall behind, so Prometheus "now" queries come back empty.
  Fixed with Guest Additions time sync (threshold 1 s, set in the `Vagrantfile`) and chrony disabled.
- **Deliberate app flaws** (slow queries, memory leak, coupon bug, slow login): see `docs/known-flaws.md`. They exist to make problems visible on the dashboards.

## Limitations and improvements
- **Limitation:** the admin/chaos endpoints of the API have no authentication. This is acceptable only because the API is on a private host-only network.
- **Limitation:** single node only. Loki and Prometheus use local disk, with no high availability.
- **Improvement:** run ShopLite itself in Kubernetes (Postgres as a StatefulSet), add a second alert for a high 5xx error rate, and add traces (OpenTelemetry + Tempo).
