#!/usr/bin/env bash
# Sandbox walkthrough: a fake TV, no real device, no real network.
# Usage: bash scripts/try-in-sandbox.sh
#        KEEP=1 bash scripts/try-in-sandbox.sh   # keep the temp state dir
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
KEEP="${KEEP:-0}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tv-ads-close-sandbox.XXXXXX")"

cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "临时目录保留在：$WORK"
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

mkdir -p "$WORK/bin" "$WORK/state" "$WORK/home"
cat > "$WORK/bin/adb" <<ADB
#!/bin/sh
exec "$PYTHON" "$ROOT/tests/fake_adb.py" "\$@"
ADB
chmod +x "$WORK/bin/adb"

export ADB="$WORK/bin/adb"
export TV_FAKE_STATE="$WORK/state"
export TV_ADS_CLOSE_HOME="$WORK/home"
export PYTHONDONTWRITEBYTECODE=1

cd "$ROOT"
run() {
  echo
  echo "▶ $*"
  "$@"
}

echo "== tv-ads-close 沙盒体验（假电视，不连接任何真实设备）=="
echo "工作目录：$WORK"

run "$PYTHON" -B scripts/tv_ads_close.py demo
run "$PYTHON" -B scripts/tv_ads_close.py setup --timeout 5 --non-interactive

PLAN="$WORK/plan.json"
run "$PYTHON" -B scripts/tv_ads_close.py plan \
  --host 127.0.0.1 \
  --include-observed \
  --attest-owner \
  --save "$PLAN"

CONFIRM="$("$PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["confirm_code"])' "$PLAN")"
run "$PYTHON" -B scripts/tv_ads_close.py apply \
  --plan "$PLAN" \
  --confirm "$CONFIRM" \
  --attest-owner

run "$PYTHON" -B scripts/tv_ads_close.py verify --plan "$PLAN"

BACKUP="$(ls -t "$WORK/home/backups"/*.json | grep -v journal | head -n1)"
run "$PYTHON" -B scripts/tv_ads_close.py restore \
  --host 127.0.0.1 \
  --backup "$BACKUP" \
  --attest-owner

echo
echo "▶ 还原后再 verify（预期失败：计划已回滚）"
set +e
"$PYTHON" -B scripts/tv_ads_close.py verify --plan "$PLAN" >/dev/null 2>&1
STATUS=$?
set -e
if [ "$STATUS" -eq 0 ]; then
  echo "❌ 预期 verify 失败，但实际成功；请检查。"
  exit 1
fi
echo "✅ verify 按预期返回失败（${STATUS}）：计划已不在生效状态。"

echo
echo "沙盒体验完成。真实设备请按 README/quickstart 操作；本脚本没有连接任何真实电视。"
