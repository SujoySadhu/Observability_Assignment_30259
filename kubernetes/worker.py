"""Order-worker: calls the ShopLite API every few seconds and logs the result.

INFO  lines go to stdout (normal events).
ERROR lines go to stderr (failures, including one intentional error).
"""
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = os.environ["API_URL"]                      # e.g. http://192.168.56.20:8000
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "5"))
ERROR_EVERY = int(os.environ.get("ERROR_EVERY", "6"))  # every Nth call is a deliberate error


def log(level, message):
    """Print one log line. ERROR goes to stderr, everything else to stdout."""
    stream = sys.stderr if level == "ERROR" else sys.stdout
    print(f"level={level} {message}", file=stream, flush=True)


def get_status(path):
    """Call the API and return the HTTP status code."""
    try:
        with urllib.request.urlopen(API_URL + path, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:   # the API answered, but with 4xx/5xx
        return error.code


log("INFO", f"order-worker started api={API_URL}")
call_number = 0

while True:
    call_number += 1

    # Every ERROR_EVERY-th call asks for a product that does not exist (intentional error).
    if call_number % ERROR_EVERY == 0:
        path = "/api/products/999999"
    else:
        path = "/api/products"

    try:
        status = get_status(path)
    except OSError as error:                  # no answer at all: API down or network problem
        log("ERROR", f"api unreachable path={path} error={error}")
    else:
        if status < 400:
            log("INFO", f"catalog check ok path={path} status={status}")
        else:
            log("ERROR", f"catalog check failed path={path} status={status}")

    time.sleep(INTERVAL)
