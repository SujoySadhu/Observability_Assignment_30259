# System & Application Observability

**Candidate:** Sujoy Sadhu · **Candidate ID:** 30259 · **Instructor:** Lipton Ahammed · **Submission:** 12 Nov 2026

This project watches a small online shop and the Ubuntu machine it runs on. It collects
**numbers** (how busy is the CPU? how many orders per minute?), **log messages** (what went
wrong and when?) and sends an **email** when something breaks. Everything runs on one laptop,
inside one Ubuntu virtual machine.

If you are new to this topic, read the sections in order. Every tool and word is explained
the first time it appears.

---

## Contents
1. [The idea in one minute](#1-the-idea-in-one-minute)
2. [Words you will meet](#2-words-you-will-meet)
3. [The big picture](#3-the-big-picture)
4. [What runs where](#4-what-runs-where)
5. [Part A: Metrics (numbers)](#5-part-a-metrics-numbers)
6. [Part B: Kubernetes logs (messages)](#6-part-b-kubernetes-logs-messages)
7. [Part C: Email alerts](#7-part-c-email-alerts)
8. [The dashboard](#8-the-dashboard)
9. [Folder guide](#9-folder-guide)
10. [How to set it up](#10-how-to-set-it-up)
11. [How to check that it works](#11-how-to-check-that-it-works)
12. [How to see it in action (demo)](#12-how-to-see-it-in-action-demo)
13. [Keeping secrets safe](#13-keeping-secrets-safe)
14. [Differences from the reference design](#14-differences-from-the-reference-design)
15. [Problems we hit and how we fixed them](#15-problems-we-hit-and-how-we-fixed-them)
16. [Limitations and next steps](#16-limitations-and-next-steps)
17. [How to clean up](#17-how-to-clean-up)
18. [Evidence](#18-evidence)

---

## 1. The idea in one minute

Imagine you run an online shop. Customers say "the site is slow" or "checkout failed".
How do you find out **what** happened, **when**, and **why**? You need to *observe* your
system. That is called **observability**, and it uses three kinds of signals:

| Signal | Question it answers | Example from this project |
|---|---|---|
| **Metrics** (numbers over time) | *Is something wrong? How bad?* | "5 % of requests failed in the last 5 minutes" |
| **Logs** (text messages) | *Why did it go wrong?* | `TypeError ... cart.py line 91` |
| **Alerts** (notifications) | *Does a human need to act now?* | an email: "ShopLite API is down" |

This project builds all three, end to end, with real data:

- **Metrics:** real CPU, RAM, disk and network of the Ubuntu machine, plus real traffic, errors
  and speed of a working web shop.
- **Logs:** real log messages from a program running in a Kubernetes cluster, searchable in Grafana.
- **Alerts:** a rule that notices when the shop is down and sends a real email through Gmail.

---

## 2. Words you will meet

| Word | Simple meaning |
|---|---|
| **VM (virtual machine)** | A computer simulated inside your real computer. Ours runs Ubuntu 26.04. |
| **Vagrant** | A tool that creates a VM from a short text file (`Vagrantfile`). `vagrant up` builds the same VM every time. |
| **Docker / container** | A way to run a program in its own small, isolated box with everything it needs. |
| **Docker Compose** | Starts several containers together from one file (`compose.yaml`). |
| **Kubernetes** | A system that runs and looks after containers (restarts them if they crash, etc.). |
| **MicroK8s** | A small, single-machine version of Kubernetes. |
| **Pod** | The smallest thing Kubernetes runs: one or more containers together. |
| **Namespace** | A "folder" inside Kubernetes to keep things separate. |
| **Helm** | Like `apt` for Kubernetes: installs ready-made apps ("charts"). |
| **Prometheus** | Collects numbers (metrics) from programs every 15 seconds and stores them. |
| **Node Exporter** | Reads the Linux machine's CPU, RAM, disk and network and offers them to Prometheus. |
| **Loki** | Stores log messages and lets you search them. |
| **Grafana Alloy** | A log collector. It reads the logs of Kubernetes pods and sends them to Loki. |
| **Grafana** | The website where you see graphs (dashboards), search logs and set up alerts. |
| **PromQL** | The question language for Prometheus, e.g. "requests per second". |
| **LogQL** | The question language for Loki, e.g. "show error lines from namespace X". |
| **SMTP** | The standard way programs send email. Grafana uses Gmail's SMTP server. |
| **Scrape** | Prometheus *pulling* the current numbers from a program's `/metrics` page. |
| **Target** | A place Prometheus scrapes. It is **UP** when the last scrape worked. |
| **Counter** | A number that only goes up (e.g. total requests). We look at how *fast* it grows. |
| **Gauge** | A number that goes up and down (e.g. RAM in use). |
| **Histogram** | Counts how many requests were faster than 0.1 s, 0.25 s, 0.5 s ... Used for "p95". |
| **p95 latency** | 95 % of requests were faster than this time. A good measure of "slow for real users". |

---

## 3. The big picture

```
Windows 11 laptop
└── VirtualBox VM "obs-lab"  (Ubuntu 26.04, IP 192.168.56.20)
    │
    ├── Docker Compose ─────────────────────────────────────────────────────────
    │     ShopLite web shop      web (:8080) → api (:8000) → postgres database
    │     Node Exporter (:9100)  reads the VM's real CPU / RAM / disk / network
    │     Prometheus   (:9090)   collects numbers from Node Exporter and the api
    │     Loki         (:3100)   stores log messages
    │     Grafana      (:3000)   dashboards, log search, alerts, sends email
    │
    └── MicroK8s (Kubernetes) ──────────────────────────────────────────────────
          namespace "shop-worker":  order-worker pod  (calls the shop, writes logs)
          namespace "alloy":        Grafana Alloy pod (sends those logs to Loki)
```

The three flows:

```
METRICS:  Node Exporter + ShopLite api ──(scraped every 15 s)──► Prometheus ──► Grafana graphs

LOGS:     order-worker pod (Kubernetes) ──► Alloy ──► Loki (Docker) ──► Grafana log search

ALERTS:   Grafana rule "is the api down?" ──► Gmail SMTP ──► email in the inbox
```

---

## 4. What runs where

| Component | Version | Runs in | Address (from Windows) | Job |
|---|---|---|---|---|
| ShopLite web | - | Docker Compose | http://192.168.56.20:8080 | the shop website |
| ShopLite api | 2.0.0 | Docker Compose | http://192.168.56.20:8000 | shop backend, exposes `/metrics` |
| PostgreSQL | 17 | Docker Compose | (not published) | shop database |
| Node Exporter | 1.9.1 | Docker Compose | 192.168.56.20:9100 | host metrics |
| Prometheus | 3.5.0 | Docker Compose | http://192.168.56.20:9090 | metric storage |
| Loki | 3.5.3 | Docker Compose | 192.168.56.20:3100 | log storage |
| Grafana | 12.1.0 | Docker Compose | http://192.168.56.20:3000 | dashboards, logs, alerts |
| order-worker | - | MicroK8s | - | log-producing workload |
| Grafana Alloy | chart 1.5.2 | MicroK8s | - | log collector |

Tool versions in the VM: Ubuntu 26.04.1, Docker Engine 29.9.3, Docker Compose 5.7.0,
MicroK8s / Kubernetes 1.35.6, Helm 3.19.2.

**Why `192.168.56.20`?** This is a *host-only* network address. Only this laptop can reach it,
not other computers on the Wi-Fi or the internet. So the tools are private, as the assignment requires.

---

## 5. Part A: Metrics (numbers)

### 5.1 The shop (ShopLite)

ShopLite is a small but complete online shop: register, log in, browse 24 products, add to cart,
use coupons, check out, see order history. It is written in Python (FastAPI) with a PostgreSQL
database.

The important part for observability: the shop **measures itself**. It has a page `/metrics`
that shows numbers like:

| Metric | Type | What it counts |
|---|---|---|
| `http_requests_total{method, route, status}` | counter | every request, with its result code (200, 404, 500 ...) |
| `http_request_duration_seconds` | histogram | how long requests take |
| `orders_created_total{payment_method}` | counter | successful orders (a **business** number) |
| `orders_failed_total{reason}` | counter | failed checkouts and why (empty cart, invalid input ...) |

The required endpoints are there: `GET /health`, `POST /api/orders`, `GET /metrics`.

**Labels are kept small on purpose.** For example `route` stores `/api/orders/{order_id}`,
not `/api/orders/17`, `/api/orders/18` ... Otherwise every order would create a new data series
and Prometheus would slowly run out of memory.

**Deliberate flaws.** The shop has 4 bugs *on purpose*, so problems become visible on the
dashboard (details in `docs/known-flaws.md`): slow database queries, a memory leak, a coupon
(`FLAT15`) that crashes checkout with an error 500, and a very slow login.

### 5.2 The Ubuntu machine (Node Exporter)

Linux shows its live state as text files in `/proc` and `/sys` (for example `/proc/meminfo`
for memory). Node Exporter reads these files and turns them into metrics.

Node Exporter runs in a container, but a container normally sees only its *own* small world
(its own network, its own disk). To see the **real** VM it gets three settings in `compose.yaml`:

- `network_mode: host`: use the VM's real network cards
- `pid: host`: see the VM's real processes
- `/:/host:ro,rslave`: the VM's whole disk, mounted **read-only** (`ro`), so it can look but never change anything

### 5.3 Prometheus

Prometheus visits ("scrapes") two places every **15 seconds** (`prometheus/prometheus.yml`):

| Job name | Address | What |
|---|---|---|
| `node` | `192.168.56.20:9100` | the Ubuntu VM |
| `shoplite-api` | `api:8000` | the shop |

`api` is a name, not an IP address: Docker Compose gives every service a name that the other
containers can use. This is called *service discovery*.

### 5.4 The 5 required questions (PromQL)

Full explanations: `prometheus/promql-queries.md`.

| Question | PromQL | In plain words |
|---|---|---|
| CPU % | `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])))` | how much of each second the CPUs were *not* idle |
| RAM % | `100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)` | used = 1 - available / total |
| Requests per second | `sum(rate(http_requests_total{route!~"/health\|/metrics"}[1m]))` | customer requests per second (health checks and Prometheus' own visits removed) |
| Error rate % | `100 * sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` | server errors (5xx) out of all requests |
| p95 latency | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` | 95 % of requests were faster than this |

Two ideas worth knowing:
- **`rate(...)`**: a counter only grows, so its raw value says nothing about *now*. `rate`
  turns it into "per second over the last minute".
- **Why `MemAvailable`, not `MemFree`**: Linux fills spare RAM with cache and gives it back
  when needed. `MemFree` would make the VM look almost full; `MemAvailable` is the honest number.

**Cross-check with Linux:** the numbers were compared with the Linux commands `free -m`
(RAM) and `df -m /` (disk). The totals matched exactly (`evidence/task4/crosscheck-linux.txt`).

---

## 6. Part B: Kubernetes logs (messages)

### 6.1 The workload: order-worker

A small Python program (`kubernetes/worker.py`) runs as a Kubernetes **Deployment** in its own
namespace `shop-worker`. Every 5 seconds it asks the shop for the product list:

- success → `level=INFO catalog check ok ... status=200` on **stdout** (normal output)
- every 6th call it asks for a product that does not exist (**intentional error**) →
  `level=ERROR catalog check failed ... status=404` on **stderr** (error output)
- if the shop is down → `level=ERROR api unreachable ...` on stderr

No custom image is built: it uses the official `python:3.12-alpine` image, and the script is
put inside it with a **ConfigMap** (Kubernetes' way to store a file).

### 6.2 The collector: Grafana Alloy

Alloy is installed with Helm (`kubernetes/alloy-values.yaml`). Its configuration does 4 things:

1. find every pod in the cluster
2. label its logs with `namespace`, `pod`, `container` and `app`
3. read the logs through the Kubernetes API
4. send them to Loki

### 6.3 How the logs travel from Kubernetes to Docker (networking)

Alloy runs in Kubernetes and Loki runs in Docker. They are two separate worlds, but both live
on the **same VM**. Loki's port 3100 is published on the VM's address `192.168.56.20`.
So Alloy simply sends to:

```
http://192.168.56.20:3100/loki/api/v1/push
```

The packet leaves the pod network, reaches the VM's own network card, and Docker forwards it to
the Loki container. The order-worker reaches the shop the same way (`http://192.168.56.20:8000`).

### 6.4 Searching the logs (LogQL)

In Grafana → **Explore** → data source **Loki**:

| Query | Shows |
|---|---|
| `{namespace="shop-worker"}` | all logs of the workload's namespace |
| `{namespace="shop-worker", pod=~"order-worker.*", container="worker"}` | filtered by pod and container |
| `{namespace="shop-worker"} \|= "level=ERROR"` | only the error lines, with timestamps |

The same lines appear in `kubectl -n shop-worker logs deploy/order-worker`, which proves the logs
come from the live pod and not from a sample file.

---

## 7. Part C: Email alerts

Everything is configured with files in `grafana/provisioning/alerting/`, so it is created
automatically when Grafana starts. Full explanation: `alerting/configuration-notes.md`.

| Piece | File | Setting |
|---|---|---|
| **Alert rule** (what to check) | `rules.yaml` | `up{job="shoplite-api"} < 1` → the shop's api did not answer Prometheus |
| How often | | checked every 30 s |
| How long before alerting | | must stay down for **1 minute** (short restarts do not send email) |
| **Contact point** (where to send) | `contact-points.yaml` | email to the address in `ALERT_EMAIL_TO` |
| **Notification policy** (which alert goes where) | `policies.yaml` | all alerts → email, wait 30 s to group, repeat every 4 h |
| **Email server** | `compose.yaml` + `.env` | Gmail `smtp.gmail.com:587`, encrypted (STARTTLS), Gmail **App Password** |
| **What the operator should do** | in the email (`runbook`) | check `docker compose ps api` and the logs, then `docker compose up -d api` |

**Tested:** `docker compose stop api` → rule *Pending* after ~30 s → *Firing* after ~1.5 min →
email "[FIRING] ShopLite API is down" arrived → `docker compose start api` → rule back to *Normal*
→ email "[RESOLVED]" arrived.

---

## 8. The dashboard

Grafana → **Dashboards** → folder **ShopLite** → **ShopLite - Host & App Overview**.
It is stored as a file (`grafana/dashboards/shoplite-overview.json`) and loaded automatically.

```
[ CPU usage     ] [ RAM usage           ] [ Disk usage (/)   ]   ← the Ubuntu machine
[ Network       ] [ Requests per second ] [ Error rate (5xx) ]   ← machine + shop
[ Latency p95             ] [ Orders created (last 5 min)    ]   ← shop speed + business
[ Order-worker errors (Kubernetes logs, from Loki)           ]   ← logs
```

8 metric panels with titles, legends and units (%, bytes/s, requests/s, seconds), plus one log panel.

---

## 9. Folder guide

```
30259_observability/
├── README.md                    this file
├── Vagrantfile                  builds the Ubuntu 26.04 VM (6 GB RAM, 4 CPUs, clock sync)
├── compose.yaml                 starts the shop + Prometheus, Loki, Grafana, Node Exporter
├── .env.example                 list of settings and secrets (copy to .env and fill in)
├── app/                         the ShopLite shop (backend, frontend, database schema)
├── prometheus/
│   ├── prometheus.yml           what Prometheus scrapes, and how often
│   └── promql-queries.md        the 5 queries, explained
├── loki/config.yml              Loki settings (storage on disk, keep logs 7 days)
├── kubernetes/
│   ├── namespace.yaml           the "shop-worker" namespace
│   ├── worker.py                the log-producing program
│   ├── workload.yaml            the Deployment that runs it
│   └── alloy-values.yaml        Alloy settings (collect pod logs → Loki)
├── grafana/
│   ├── provisioning/            auto-setup: data sources, dashboard loader, alerting
│   └── dashboards/              shoplite-overview.json (the exported dashboard)
├── alerting/configuration-notes.md   the alert explained
├── scripts/
│   ├── setup-vm.sh              installs Docker, MicroK8s, Helm in the VM
│   ├── verify.sh                checks every part, prints PASS / FAIL
│   ├── traffic-test.sh          normal → high → failing traffic, saves before/after numbers
│   ├── loadgen.py               simulated shoppers
│   └── chaos.sh                 turns error/latency injection on and off
├── docs/known-flaws.md          the 4 deliberate shop bugs
└── evidence/                    screenshots and command output for each task
```

---

## 10. How to set it up

You need a Windows PC with **VirtualBox 7.2** and **Vagrant 2.4**, and about 8 GB of free RAM.

### Step 1: Create the VM (Windows PowerShell, in the project folder)
```bash
vagrant up        # first time: downloads Ubuntu 26.04 and builds the VM (5-15 min)
vagrant ssh       # log in to the VM
```

### Step 2: Copy the project onto the VM's own disk
The project folder is shared into the VM as `/vagrant`, but shared folders break Linux file
permissions, so we work on a copy:
```bash
mkdir -p ~/30259_observability
cp -r /vagrant/. ~/30259_observability
cd ~/30259_observability
```

### Step 3: Install Docker, MicroK8s and Helm
```bash
./scripts/setup-vm.sh
exit              # log out and in again so your user can use docker and microk8s
```
```bash
vagrant ssh
cd ~/30259_observability
```

### Step 4: Fill in your settings
```bash
cp .env.example .env
chmod 600 .env    # only you can read it
nano .env         # set the passwords, your Gmail address, Gmail App Password, recipient
```
A Gmail **App Password** is created at Google Account → Security → App passwords
(2-Step Verification must be on).

### Step 5: Start the shop and the monitoring tools
```bash
docker compose up -d --build
docker compose ps             # all services should be "Up" / "healthy"
```

### Step 6: Start the Kubernetes part
```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl -n shop-worker create configmap order-worker-script --from-file=worker.py=kubernetes/worker.py
kubectl apply -f kubernetes/workload.yaml

helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm install alloy grafana/alloy --version 1.5.2 -n alloy --create-namespace -f kubernetes/alloy-values.yaml
```

### Step 7: Start simulated shoppers (so the graphs have data)
```bash
nohup python3 scripts/loadgen.py --users 3 --quiet > /tmp/loadgen.log 2>&1 &
```

### Step 8: Open in the Windows browser
| What | URL |
|---|---|
| Shop | http://192.168.56.20:8080 |
| Grafana | http://192.168.56.20:3000 (user `admin`, password from `.env`) |
| Prometheus targets | http://192.168.56.20:9090/targets |
| Shop metrics | http://192.168.56.20:8000/metrics |

---

## 11. How to check that it works

One command checks every part:
```bash
./scripts/verify.sh
```
It tests the shop, both Prometheus targets, the Kubernetes node and pods, whether Loki received
Kubernetes logs, Grafana, the dashboard and the alert rule. Expected result:
```
== Result: 12 passed, 0 failed
```

---

## 12. How to see it in action (demo)

| Step | Do | What you will see |
|---|---|---|
| 1. Normal | open the dashboard | steady CPU, requests/s, orders from 3 shoppers |
| 2. High traffic + failure | `DUR=30 ./scripts/traffic-test.sh` | phase 2 (20 users): requests/s rises. Phase 3: 30 % injected errors, the 5xx line and error rate jump, p95 rises |
| 3. Logs | Explore → `{namespace="shop-worker"} \|= "level=ERROR"` | error lines from the Kubernetes pod |
| 4. Outage | `docker compose stop api` | requests/s drops to 0, worker logs `api unreachable`, alert goes Pending → Firing, email arrives |
| 5. Recovery | `docker compose start api` | everything returns to normal, "RESOLVED" email arrives |

Step 4 is the key idea: **one failure, three signals**. The metric says *something is wrong*,
the log says *what*, and the alert tells a *person*.

---

## 13. Keeping secrets safe

- All passwords (database, Grafana admin, Gmail App Password) and the recipient address are only in `.env`.
- `.env` is listed in `.gitignore`, so it is never committed and never in the zip. `.env.example` contains only placeholders.
- Gmail uses an **App Password**, not the real account password, and the connection is encrypted (STARTTLS).
- Every port listens only on the private host-only address `192.168.56.20`. The database has no published port at all.
- Node Exporter can read the host disk but not change it (read-only mount).

---

## 14. Differences from the reference design

The assignment allows equivalent setups if they are documented:

| Assignment says | This project | Why |
|---|---|---|
| Ubuntu laptop | Ubuntu 26.04 in a Vagrant / VirtualBox VM | anyone can rebuild the same machine with `vagrant up` |
| keep ports private | ports on host-only IP `192.168.56.20` (not `127.0.0.1`) | Kubernetes pods must reach the shop and Loki; the address is still private |
| a simple Order API | ShopLite, a full shop that includes the Order API | more realistic traffic and business metrics |
| a log-generating workload | order-worker, which calls the real shop | its errors appear together with the shop's metrics and alerts |

---

## 15. Problems we hit and how we fixed them

| Problem | Cause | Fix |
|---|---|---|
| Prometheus "Table" view said *no data* while the graph worked | the VM clock was 4-6 minutes behind Windows (VirtualBox running on Hyper-V loses time) | VirtualBox Guest Additions now copies the Windows time into the VM whenever it is more than 1 s off (set in the `Vagrantfile`); the Ubuntu time service was turned off so the two do not fight |
| every file was marked executable, `.env` readable by everyone | files copied from the Windows shared folder keep Windows-style permissions | `chmod 644` for files, `755` for scripts, `600` for `.env` |
| the app could not be reached from the Kubernetes pods | ports were bound to `127.0.0.1`, which a pod cannot reach | bound to the host-only IP `192.168.56.20` |

---

## 16. Limitations and next steps

- **Limitation:** the shop's admin endpoints (used to inject errors for the demo) have no login. This is acceptable only because the shop is on a private network.
- **Limitation:** everything runs on one machine. If the VM fails, monitoring fails too, and Loki / Prometheus keep data on a local disk only.
- **Next step:** run the shop itself in Kubernetes (with the database as a StatefulSet).
- **Next step:** add a second alert for a high error rate (for example 5xx above 5 % for 5 minutes).
- **Next step:** add the third signal, **traces** (OpenTelemetry + Grafana Tempo), to follow one request through every component.

---

## 17. How to clean up

```bash
pkill -f loadgen.py                          # stop the simulated shoppers
helm uninstall alloy -n alloy                # remove Alloy
kubectl delete namespace shop-worker alloy   # remove the Kubernetes workload
docker compose down                          # stop the containers, KEEP the data
docker compose down -v                       # stop the containers and DELETE all data
```
On Windows, `vagrant destroy` deletes the whole VM.

---

## 18. Evidence

| File / folder | Shows |
|---|---|
| `evidence/task2/compose-ps.txt`, `evidence/task5/cluster-pods.txt` | Compose services and Kubernetes pods running |
| `evidence/prometheus-targets.png` | both Prometheus targets UP |
| `evidence/grafana-metrics.png` | the dashboard with live data |
| `evidence/kubernetes-logs.png` | Kubernetes logs in Grafana (LogQL) |
| `evidence/email-alert.png` | the received alert email |
| `evidence/task1/` | tool versions, VM details |
| `evidence/task2/` | Compose config (no secrets), running services, data kept after restart |
| `evidence/task3/` | successful and failed requests, metric values before and after traffic |
| `evidence/task4/` | targets, the 5 PromQL results, Linux cross-checks |
| `evidence/task5/` | Alloy running, `kubectl logs`, Loki queries |
| `evidence/task6/` | dashboard screenshots |
| `evidence/task7/` | alert Pending, Firing, email received, email resolved |
| `evidence/task8/` | `verify.sh` result: 12 passed, 0 failed |
