"""Structured (JSON) logging to stdout.

Containers should log to stdout/stderr and let the platform collect the stream
(Docker keeps it for `docker compose logs`; Kubernetes writes it to /var/log/pods).
One JSON object per line lets Loki's `| json` parser turn every field into a
filterable value, e.g. {container="api"} | json | level="error".
"""
import json
import logging
import sys
import time
from contextvars import ContextVar

# The request ID of the request being handled right now. ContextVar keeps it
# correct even when many requests run concurrently.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            entry.update(fields)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Send uvicorn's own messages through our JSON handler too.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    # We write our own, richer access log line per request (see main.py).
    logging.getLogger("uvicorn.access").disabled = True


def log(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    """logger.info() with structured key/value fields attached."""
    logger.log(level, msg, extra={"fields": fields})
