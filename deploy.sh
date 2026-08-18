#!/usr/bin/env bash
# Deploy ffiom image to the prod VM (ffiom-prod, 192.168.1.23).
# Usage: bash deploy.sh          (build + transfer + restart)
#        bash deploy.sh --skip-build  (transfer the existing local image)
set -euo pipefail

export PATH="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin:$PATH"
VM="root@192.168.1.23"
cd "$(dirname "$0")"

if [[ "${1:-}" != "--skip-build" ]]; then
  echo "==> Building ffiom:latest ..."
  docker build -t ffiom:latest .
fi

echo "==> Transferring image to $VM ..."
docker save ffiom:latest | gzip -1 | ssh -o ConnectTimeout=10 "$VM" 'gunzip | docker load'

echo "==> Restarting container ..."
ssh "$VM" 'docker restart ffiom && sleep 3 && curl -sf http://localhost:8000/api/health && echo'

echo "==> Done. Live check:"
curl -sf https://ffiom.com/api/health && echo " <- ffiom.com OK"
