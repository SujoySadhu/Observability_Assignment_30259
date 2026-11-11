# Email alerting (Task 7)

## Alert rule: "ShopLite API is down"
| Item | Value | Why |
|---|---|---|
| Query | `up{job="shoplite-api"}` | Prometheus sets `up` = 1 when a scrape works, 0 when it fails |
| Threshold | `up < 1` | the API did not answer the last scrape |
| Evaluation | every 30 s | quick enough to notice an outage within a minute |
| Pending period (`for`) | 1 min | ignores short restarts; only a real outage alerts |
| No data / error | treated as Alerting | if we cannot see the API, assume it is down |
| Severity | critical | customers cannot shop at all |

## Notification
- Contact point: `email-oncall` (type email), recipient from `ALERT_EMAIL_TO` in `.env`
- Policy: all alerts -> `email-oncall`, grouped by alert name,
  group_wait 30 s, repeat every 4 h while still firing
- A "RESOLVED" email is sent automatically when the API is back

## SMTP and secrets
- Gmail SMTP `smtp.gmail.com:587` with STARTTLS (encrypted)
- Login uses a Gmail **App Password**, not the account password
- `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` live only in `.env` (git-ignored);
  `.env.example` contains placeholders only
- Files: `grafana/provisioning/alerting/{contact-points,policies,rules}.yaml`

## Recommended operator action
1. `docker compose ps api` - is the container running?
2. `docker compose logs api --tail 50` - why did it stop? (crash, out of memory)
3. Restart: `docker compose up -d api`
4. Confirm: rule returns to Normal and a RESOLVED email arrives

## How it was tested
`docker compose stop api` -> Pending after ~30 s -> Firing after ~1.5 min ->
email received -> `docker compose start api` -> Normal + RESOLVED email.
