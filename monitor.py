"""
System Resource Monitor — sends metrics via OMF (OSIsoft Message Format)
to a PI Web API or OSIsoft EDS / AVEVA Data Hub endpoint.

OMF flow: Type → Container → Data  (each as separate HTTP POST)
"""

import os
import time
import logging
import socket
import json
from datetime import datetime, timezone

import psutil
import requests
from requests.auth import HTTPBasicAuth

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
log = logging.getLogger(__name__)

# ── Environment variables ──────────────────────────────────────────────────────
OMF_ENDPOINT   = os.environ["OMF_ENDPOINT"]          # e.g. https://host/omf
OMF_USERNAME   = os.environ["OMF_USERNAME"]
OMF_PASSWORD   = os.environ["OMF_PASSWORD"]
INTERVAL_SEC   = int(os.environ.get("INTERVAL_SECONDS", "60"))
PRODUCER_TOKEN = os.environ.get("OMF_PRODUCER_TOKEN", "")   # needed by some endpoints
VERIFY_SSL     = os.environ.get("VERIFY_SSL", "true").lower() != "false"
TYPE_ID        = os.environ.get("OMF_TYPE_ID", "SystemMetrics")
CONTAINER_ID   = os.environ.get("OMF_CONTAINER_ID", socket.gethostname())
STREAM_ID      = os.environ.get("OMF_STREAM_ID", f"{CONTAINER_ID}_metrics")

# Disk partition to monitor (default: root)
DISK_PATH      = os.environ.get("DISK_PATH", "/")

# Comma-separated list of network interfaces to include (empty = all)
NET_IFACES_RAW = os.environ.get("NET_INTERFACES", "")
NET_IFACES     = [i.strip() for i in NET_IFACES_RAW.split(",") if i.strip()]

# ── OMF definitions ────────────────────────────────────────────────────────────
OMF_TYPE = [
    {
        "id": TYPE_ID,
        "version": "1.0.0.0",
        "type": "object",
        "classification": "dynamic",
        "properties": {
            "Timestamp":        {"type": "string", "format": "date-time", "isindex": True},
            "CPU_Percent":      {"type": "number", "description": "CPU utilisation %"},
            "Mem_Total_GB":     {"type": "number", "description": "Total RAM (GB)"},
            "Mem_Used_GB":      {"type": "number", "description": "Used RAM (GB)"},
            "Mem_Percent":      {"type": "number", "description": "RAM utilisation %"},
            "Swap_Total_GB":    {"type": "number", "description": "Total swap (GB)"},
            "Swap_Used_GB":     {"type": "number", "description": "Used swap (GB)"},
            "Swap_Percent":     {"type": "number", "description": "Swap utilisation %"},
            "Disk_Total_GB":    {"type": "number", "description": "Disk total (GB)"},
            "Disk_Used_GB":     {"type": "number", "description": "Disk used (GB)"},
            "Disk_Percent":     {"type": "number", "description": "Disk utilisation %"},
            "Net_Bytes_Sent":   {"type": "number", "description": "Network bytes sent (cumulative)"},
            "Net_Bytes_Recv":   {"type": "number", "description": "Network bytes received (cumulative)"},
            "Load_1m":          {"type": "number", "description": "1-minute load average"},
            "Load_5m":          {"type": "number", "description": "5-minute load average"},
            "Load_15m":         {"type": "number", "description": "15-minute load average"},
            "CPU_Cores_Logical": {"type": "integer", "description": "Logical CPU core count"},
            "Boot_Time_UTC":    {"type": "string",  "description": "Host boot time (ISO-8601)"},
        },
    }
]

OMF_CONTAINER = [
    {
        "id": CONTAINER_ID,
        "typeid": TYPE_ID,
    }
]


def _bytes_to_gb(b: float) -> float:
    return round(b / (1024 ** 3), 3)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect_metrics() -> dict:
    """Gather system metrics from psutil and return as a flat dict."""
    cpu     = psutil.cpu_percent(interval=1)
    mem     = psutil.virtual_memory()
    swap    = psutil.swap_memory()
    disk    = psutil.disk_usage(DISK_PATH)
    boot_ts = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)

    # Network counters — filter by interface if specified
    if NET_IFACES:
        net_raw = psutil.net_io_counters(pernic=True)
        bytes_sent = sum(net_raw[i].bytes_sent for i in NET_IFACES if i in net_raw)
        bytes_recv = sum(net_raw[i].bytes_recv for i in NET_IFACES if i in net_raw)
    else:
        net = psutil.net_io_counters()
        bytes_sent, bytes_recv = net.bytes_sent, net.bytes_recv

    # Load average (Unix only; Windows returns (0,0,0))
    try:
        load1, load5, load15 = psutil.getloadavg()
    except AttributeError:
        load1 = load5 = load15 = 0.0

    return {
        "Timestamp":         _iso_now(),
        "CPU_Percent":       round(cpu, 2),
        "Mem_Total_GB":      _bytes_to_gb(mem.total),
        "Mem_Used_GB":       _bytes_to_gb(mem.used),
        "Mem_Percent":       round(mem.percent, 2),
        "Swap_Total_GB":     _bytes_to_gb(swap.total),
        "Swap_Used_GB":      _bytes_to_gb(swap.used),
        "Swap_Percent":      round(swap.percent, 2),
        "Disk_Total_GB":     _bytes_to_gb(disk.total),
        "Disk_Used_GB":      _bytes_to_gb(disk.used),
        "Disk_Percent":      round(disk.percent, 2),
        "Net_Bytes_Sent":    bytes_sent,
        "Net_Bytes_Recv":    bytes_recv,
        "Load_1m":           round(load1, 3),
        "Load_5m":           round(load5, 3),
        "Load_15m":          round(load15, 3),
        "CPU_Cores_Logical": psutil.cpu_count(logical=True),
        "Boot_Time_UTC":     boot_ts.isoformat(timespec="seconds"),
    }


# ── OMF HTTP helpers ───────────────────────────────────────────────────────────

def _omf_headers(msg_type: str) -> dict:
    """Build the required OMF HTTP headers."""
    headers = {
        "Content-Type":       "application/json",
        "omfversion":         "1.1",
        "action":             "create",
        "messageformat":      "json",
        "messagetype":        msg_type,   # "type" | "container" | "data"
    }
    if PRODUCER_TOKEN:
        headers["producertoken"] = PRODUCER_TOKEN
    return headers


def _post(msg_type: str, payload: list, session: requests.Session) -> None:
    """POST an OMF message and raise on non-2xx."""
    resp = session.post(
        OMF_ENDPOINT,
        headers=_omf_headers(msg_type),
        data=json.dumps(payload),
        verify=VERIFY_SSL,
        timeout=30,
    )
    if not resp.ok:
        log.error(
            "OMF %s POST failed — HTTP %s: %s",
            msg_type, resp.status_code, resp.text[:400],
        )
        resp.raise_for_status()
    log.debug("OMF %s → HTTP %s", msg_type, resp.status_code)


def send_type_and_container(session: requests.Session) -> None:
    """Send Type and Container definitions (idempotent — safe to re-send)."""
    _post("type",      OMF_TYPE,      session)
    _post("container", OMF_CONTAINER, session)
    log.info("OMF Type and Container registered (container_id=%s)", CONTAINER_ID)


def send_data(metrics: dict, session: requests.Session) -> None:
    """Wrap metrics in an OMF Data message and POST it."""
    payload = [
        {
            "containerid": CONTAINER_ID,
            "values": [metrics],
        }
    ]
    _post("data", payload, session)
    log.info(
        "Sent metrics — CPU=%.1f%% MEM=%.1f%% DISK=%.1f%%",
        metrics["CPU_Percent"],
        metrics["Mem_Percent"],
        metrics["Disk_Percent"],
    )


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info(
        "Starting system monitor | endpoint=%s container=%s interval=%ds",
        OMF_ENDPOINT, CONTAINER_ID, INTERVAL_SEC,
    )

    auth = HTTPBasicAuth(OMF_USERNAME, OMF_PASSWORD)
    session = requests.Session()
    session.auth = auth

    # Register Type + Container on startup (and retry on failure)
    registered = False
    while not registered:
        try:
            send_type_and_container(session)
            registered = True
        except Exception as exc:
            log.error("Failed to register OMF schema, retrying in 10s: %s", exc)
            time.sleep(10)

    # Main polling loop
    while True:
        start = time.monotonic()
        try:
            metrics = collect_metrics()
            send_data(metrics, session)
        except requests.RequestException as exc:
            log.error("OMF send error: %s", exc)
        except Exception as exc:
            log.exception("Unexpected error: %s", exc)

        elapsed = time.monotonic() - start
        sleep_for = max(0.0, INTERVAL_SEC - elapsed)
        log.debug("Sleeping %.1fs", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
