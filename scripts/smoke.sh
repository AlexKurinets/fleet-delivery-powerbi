#!/usr/bin/env bash
# Brings up the Compose stack and runs every operator command the README documents, in order.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${TMPDIR:-/tmp}/fleetbi-smoke"
mkdir -p "$OUT"
SOURCES_PORT="${SOURCES_PORT:-8230}"

echo "== docker compose up (init, seed, first pipeline run)"
docker compose up -d --build --wait --wait-timeout 1500

run() { docker compose exec -T pipeline fleetbi "$@"; }

echo "== mock source APIs"
curl -sf "http://localhost:${SOURCES_PORT}/health" > "$OUT/health.json"
cat "$OUT/health.json"; echo
curl -sf "http://localhost:${SOURCES_PORT}/tms/v1/stops?limit=1" > "$OUT/stop.json"
grep -q '"window_start"' "$OUT/stop.json"

echo "== fleetbi status"
run status > "$OUT/status.txt"
cat "$OUT/status.txt"
grep -q "succeeded" "$OUT/status.txt"
grep -q "fact_delivery_stop" "$OUT/status.txt"

echo "== fleetbi kpi --month 2026-10"
run kpi --month 2026-10 > "$OUT/kpi.txt"
cat "$OUT/kpi.txt"
grep -q "Redstone Mesa" "$OUT/kpi.txt"

echo "== fleetbi dq"
run dq > "$OUT/dq.txt"
cat "$OUT/dq.txt"
grep -q "GEOFENCE_MISSING" "$OUT/dq.txt"

echo "== fleetbi advance --days 3, then fleetbi run"
run advance --days 3 > "$OUT/advance.txt"
cat "$OUT/advance.txt"
run run > "$OUT/run.txt"
cat "$OUT/run.txt"
grep -q "succeeded" "$OUT/run.txt"
run status > "$OUT/status2.txt"
grep -q "2026-11-02" "$OUT/status2.txt"

echo "smoke OK"
