# System Resource Monitor — OMF Docker Image

Collects host CPU, memory, disk, network, and load metrics at a configurable interval and forwards them via **OMF 1.1** (OSIsoft Message Format) to any compatible endpoint: PI Web API, AVEVA Data Hub, OSIsoft EDS, or a custom OMF relay.

## Quick Start

```bash
# 1. Copy and edit the env file
cp .env.example .env
$EDITOR .env          # set OMF_ENDPOINT, OMF_USERNAME, OMF_PASSWORD at minimum

# 2. Build and run
docker compose up -d --build

# 3. Tail logs
docker compose logs -f
```

## Manual Docker Run

```bash
docker build -t system-monitor .

docker run -d \
  --pid=host \
  --name system-monitor \
  --restart unless-stopped \
  -e OMF_ENDPOINT="https://my-pi-server/piwebapi/omf" \
  -e OMF_USERNAME="piuser" \
  -e OMF_PASSWORD="secret" \
  -e INTERVAL_SECONDS=30 \
  -e OMF_CONTAINER_ID="webserver-01" \
  -e LOG_LEVEL=INFO \
  system-monitor
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OMF_ENDPOINT` | ✅ | — | Full OMF HTTP(S) URL |
| `OMF_USERNAME` | ✅ | — | Basic auth username |
| `OMF_PASSWORD` | ✅ | — | Basic auth password |
| `INTERVAL_SECONDS` | | `60` | Polling frequency in seconds |
| `OMF_TYPE_ID` | | `SystemMetrics` | OMF Type / schema name |
| `OMF_CONTAINER_ID` | | hostname | OMF Container / stream name |
| `OMF_PRODUCER_TOKEN` | | _(empty)_ | Producer token (PI Relay only) |
| `DISK_PATH` | | `/` | Partition to monitor |
| `NET_INTERFACES` | | _(all)_ | Comma-separated NIC list |
| `VERIFY_SSL` | | `true` | Verify TLS certificates |
| `LOG_LEVEL` | | `INFO` | DEBUG / INFO / WARNING / ERROR |

## Metrics Collected

| Field | Unit |
|---|---|
| `CPU_Percent` | % |
| `Mem_Total_GB` / `Mem_Used_GB` / `Mem_Percent` | GB / % |
| `Swap_Total_GB` / `Swap_Used_GB` / `Swap_Percent` | GB / % |
| `Disk_Total_GB` / `Disk_Used_GB` / `Disk_Percent` | GB / % |
| `Net_Bytes_Sent` / `Net_Bytes_Recv` | bytes (cumulative) |
| `Load_1m` / `Load_5m` / `Load_15m` | load average |
| `CPU_Cores_Logical` | count |
| `Boot_Time_UTC` | ISO-8601 string |

## OMF Flow

The container sends three OMF message types on startup:

1. **Type** — defines the schema (once, idempotent)
2. **Container** — creates the stream linked to the type (once, idempotent)
3. **Data** — sends a new values payload every `INTERVAL_SECONDS`

## Notes

- `--pid=host` (or `pid: host` in Compose) is strongly recommended so `psutil` reads real system-wide metrics rather than container-namespaced values.
- For **PI Web API**, ensure the account has write access to the target AF database.
- For **AVEVA Data Hub**, replace Basic Auth with the token flow and adapt headers if needed.
- SSL verification can be disabled with `VERIFY_SSL=false` for self-signed PI certs (not recommended in production).
