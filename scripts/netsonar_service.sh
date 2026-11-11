#!/usr/bin/env bash
# netsonar_service.sh —— 把 NetSonar 安裝成「開機自動在背景執行」的服務（macOS LaunchAgent）。
#   用法：netsonar_service.sh install | uninstall [--purge] | status
# 為什麼要「複製一份」到 ~/Library/Application Support？
#   macOS 的隱私保護不讓背景程式讀取「桌面／文件」資料夾，直接從桌面執行會被擋；
#   所以安裝時把程式複製到系統允許的位置，歷史資料與設定也放在那裡的 data/。
# 測試用環境變數：NETSONAR_HOME（取代家目錄）、NETSONAR_DRYRUN=1（不呼叫 launchctl、不開瀏覽器）。
set -eu

SRC="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${NETSONAR_HOME:-$HOME}"
BASE="$HOME_DIR/Library/Application Support/NetSonar"
APP="$BASE/app"; DATA="$BASE/data"
LABEL="com.netsonar.dashboard"
PLIST="$HOME_DIR/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME_DIR/Library/Logs/NetSonar.log"
DRY="${NETSONAR_DRYRUN:-0}"
UIDN="$(id -u)"

find_python() {
  for c in "${PYTHON:-}" python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /opt/anaconda3/bin/python3 /usr/bin/python3; do
    [ -n "$c" ] || continue
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      command -v "$c"; return 0
    fi
  done
  return 1
}

stop_service() {
  [ "$DRY" = "1" ] && return 0
  launchctl bootout "gui/$UIDN/$LABEL" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1 || true
}

install() {
  PY="$(find_python)" || { echo "❌ 找不到 Python 3.10 以上。請先安裝（例如到 python.org 下載，或執行 brew install python），再重新雙擊安裝。"; exit 1; }
  echo "🐍 使用 Python：$PY"
  stop_service
  mkdir -p "$APP" "$DATA" "$(dirname "$PLIST")" "$(dirname "$LOG")"

  echo "📁 複製程式到 $APP"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude '.venv' --exclude '*.db' --exclude '*.db-*' --exclude 'settings.json' --exclude '__pycache__' "$SRC/dashboard/" "$APP/"
  else
    find "$APP" -mindepth 1 -maxdepth 1 ! -name '.venv' -exec rm -rf {} +
    (cd "$SRC/dashboard" && tar --exclude='.venv' --exclude='*.db*' --exclude='settings.json' --exclude='__pycache__' -cf - .) | (cd "$APP" && tar -xf -)
  fi
  # 之前用 run_dashboard.sh 存過的設定（監測目標、門檻…）帶過來；已經有的就不覆蓋
  if [ -f "$SRC/dashboard/settings.json" ] && [ ! -f "$DATA/settings.json" ]; then cp "$SRC/dashboard/settings.json" "$DATA/settings.json"; fi

  if [ ! -x "$APP/.venv/bin/python" ]; then echo "🔧 建立專屬虛擬環境（第一次較久）…"; "$PY" -m venv "$APP/.venv"; fi
  HASH="$(shasum "$APP/requirements.txt" | cut -d' ' -f1)"
  if [ ! -f "$APP/.venv/.req_hash" ] || [ "$(cat "$APP/.venv/.req_hash")" != "$HASH" ]; then
    echo "📦 安裝套件…"
    "$APP/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$APP/requirements.txt"
    echo "$HASH" > "$APP/.venv/.req_hash"
  fi

  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/.venv/bin/python</string><string>$APP/serve.py</string></array>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>NETPROBE_DB</key><string>$DATA/netprobe.db</string>
    <key>NETPROBE_SETTINGS</key><string>$DATA/settings.json</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
  PORT="$("$APP/.venv/bin/python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$APP/config.json")"
  URL="http://127.0.0.1:$PORT"
  if [ "$DRY" = "1" ]; then echo "（測試模式）已寫入 $PLIST，網址 $URL"; return 0; fi

  launchctl bootstrap "gui/$UIDN" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
  echo "⏳ 等待儀表板啟動…"
  for _ in $(seq 1 20); do
    curl -fs "$URL/api/health" >/dev/null 2>&1 && break
    sleep 1
  done
  if curl -fs "$URL/api/health" >/dev/null 2>&1; then
    echo "✅ 安裝完成！NetSonar 已在背景執行，之後開機會自動啟動。"
    echo "   網址：$URL （建議加入瀏覽器書籤）"
    open "$URL" 2>/dev/null || true
  else
    echo "⚠️ 服務已安裝但還沒回應。請看記錄檔：$LOG"
    exit 1
  fi
}

uninstall() {
  stop_service
  rm -f "$PLIST"
  rm -rf "$APP"
  if [ "${1:-}" = "--purge" ]; then rm -rf "$BASE" "$LOG"; echo "🗑️ 已移除服務、程式、歷史資料與設定。"
  else echo "🗑️ 已移除服務與程式。歷史資料與設定保留在：$DATA"; fi
}

status() {
  if [ -f "$PLIST" ]; then echo "已安裝：$PLIST"; else echo "未安裝"; fi
  [ "$DRY" = "1" ] || launchctl print "gui/$UIDN/$LABEL" 2>/dev/null | grep -E "state|pid" || true
}

case "${1:-}" in
  install) install ;;
  uninstall) shift; uninstall "$@" ;;
  status) status ;;
  *) echo "用法：$0 install | uninstall [--purge] | status"; exit 2 ;;
esac
