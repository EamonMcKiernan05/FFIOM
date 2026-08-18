#!/usr/bin/env bash
export PATH="$LOCALAPPDATA/Programs/DockerDesktop/resources/bin:$PATH"
cd "$HOME/Desktop/FFIOM"
docker compose -f compose.override.yaml up -d
sleep 12
docker ps --format '{{.Names}} {{.Status}}' | grep ffiom
echo "=== API health ==="
curl -sf http://localhost:8000/api/health && echo
echo "=== frontend ==="
curl -s -o /dev/null -w "/ -> %{http_code}\n" http://localhost:8000/
echo "=== FullTimeAPI :5000 (in container) ==="
docker exec ffiom curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/
echo "=== fa_proxy :5001 (in container) ==="
docker exec ffiom curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/
echo "DONE"
