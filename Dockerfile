# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies into a local prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Non-root user for security
RUN addgroup --system monitor && adduser --system --ingroup monitor monitor

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application
COPY monitor.py .

# Give ownership to the non-root user
RUN chown -R monitor:monitor /app

USER monitor

# ── Environment variable defaults (override at runtime) ─────────────────────────
# REQUIRED — no defaults provided intentionally:
#   OMF_ENDPOINT, OMF_USERNAME, OMF_PASSWORD
#
# OPTIONAL with defaults:
ENV INTERVAL_SECONDS=60 \
    OMF_TYPE_ID=SystemMetrics \
    OMF_CONTAINER_ID="" \
    OMF_STREAM_ID="" \
    OMF_PRODUCER_TOKEN="" \
    DISK_PATH=/ \
    NET_INTERFACES="" \
    VERIFY_SSL=true \
    LOG_LEVEL=INFO

# Host PID namespace is recommended (docker run --pid=host) so psutil
# can read accurate system-wide metrics rather than container-scoped ones.
# See docker-compose.yml for the pid: host setting.

ENTRYPOINT ["python", "-u", "monitor.py"]
