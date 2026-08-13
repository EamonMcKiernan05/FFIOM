# FFIOM single-image build
# Stage 1: build the .NET FullTime scraper from source
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS dotnet-build
WORKDIR /src
COPY FullTimeAPI/FullTimeAPI/ ./FullTimeAPI/
RUN dotnet publish FullTimeAPI/FullTimeAPI.csproj -c Release -o /out

# Stage 2: runtime — aspnet base + python + s6-overlay + cloudflared
FROM mcr.microsoft.com/dotnet/aspnet:9.0

# --- base tooling ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv bash curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*

# --- s6-overlay v3 (process supervisor) ---
ARG S6_OVERLAY_VERSION=v3.2.0.2
ADD https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/s6-noarch.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/s6-x86.tar.xz
RUN tar -C / -Jxpf /tmp/s6-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-x86.tar.xz \
    && rm /tmp/s6-noarch.tar.xz /tmp/s6-x86.tar.xz

# --- cloudflared (tunnel sidecar) ---
ARG CLOUDFLARED_VERSION=2025.2.1
ADD https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64 /usr/local/bin/cloudflared
RUN chmod +x /usr/local/bin/cloudflared

# --- app user ---
RUN useradd -m -u 1000 -s /bin/bash ffiom

# --- python venv + deps ---
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /app/venv \
    && /app/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /app/venv/bin/pip install --no-cache-dir -r /app/requirements.txt \
    && /app/venv/bin/pip install --no-cache-dir curl_cffi

# --- app code (venv created first, then copy code) ---
COPY app/ /app/app/
COPY static/ /app/static/
COPY scripts/ /app/scripts/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY run.py /app/run.py
COPY FullTimeAPI/fa_proxy.py /app/FullTimeAPI/fa_proxy.py

# --- published .NET scraper ---
COPY --from=dotnet-build /out /opt/fulltime

# --- s6 service definitions ---
COPY docker/s6/services/ /etc/s6-overlay/s6-rc.d/
RUN chmod +x /etc/s6-overlay/s6-rc.d/*/run \
    && touch /etc/s6-overlay/s6-rc.d/user/contents.d/api \
           /etc/s6-overlay/s6-rc.d/user/contents.d/faproxy \
           /etc/s6-overlay/s6-rc.d/user/contents.d/fulltime \
           /etc/s6-overlay/s6-rc.d/user/contents.d/cloudflared

# --- startup init scripts (run as root before services) ---
COPY docker/s6/cont-init.d/ /etc/cont-init.d/
RUN chmod +x /etc/cont-init.d/*

# --- data dirs (bind-mounted at runtime) ---
RUN mkdir -p /data/game /data/ffiom && chown -R ffiom:ffiom /data

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/init"]
