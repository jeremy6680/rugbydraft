# syntax=docker/dockerfile:1

# ─────────────────────────────────────────
# Stage 1: builder — install dependencies
# ─────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# gcc is required to compile some Python packages (e.g. cryptography for python-jose)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency file first — Docker layer cache: deps only reinstalled if this changes
COPY requirements.txt .

# Install production dependencies into an isolated prefix (not system Python)
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────────
# Stage 2: runtime — lean production image
# ─────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy all application modules
# app/       — FastAPI routers, middleware, config, main entrypoint
# draft/     — snake draft engine (DraftStatus, DraftState, etc.)
# trades/    — trade logic module
# waivers/   — waiver logic module
# infirmary/ — IR (injury reserve) logic module
COPY app/ ./app/
COPY draft/ ./draft/
COPY trades/ ./trades/
COPY waivers/ ./waivers/
COPY infirmary/ ./infirmary/

# Create a non-root user for security — never run as root in production
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# Expose the port Uvicorn will listen on inside the container
EXPOSE 8000

# Health check — Coolify and Docker Compose use this to detect readiness
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 2 workers for CPX21 (2 vCPU) — rule of thumb: 2 × vCPU
# --no-access-log: reduces noise in Coolify logs (access logs go to Traefik)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]