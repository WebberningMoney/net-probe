#!/usr/bin/env bash
# netsonar_service.sh —— 把 NetSonar 安裝成「開機自動在背景執行」的服務（macOS LaunchAgent）。
#   用法：netsonar_service.sh install | uninstall [--purge] | start | stop | status
# 安裝時也會在「應用程式」放一個 NetSonar 圖示：點它＝確定背景服務在跑，然後打開儀表板。
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
APP_ID="com.netsonar.launcher"
# 「應用程式」圖示放哪：一般放 /Applications；沒有權限（或測試模式）就放自己家目錄的 Applications
if [ -z "${NETSONAR_HOME:-}" ] && [ -w /Applications ]; then APPS_DIR="/Applications"; else APPS_DIR="$HOME_DIR/Applications"; fi
LAUNCHER="$APPS_DIR/NetSonar.app"

# 建立「應用程式」裡的 NetSonar 圖示（一個很小的啟動器，不是完整的程式本體）
build_launcher() {   # $1 = 儀表板網址
  rm -rf "$LAUNCHER"
  mkdir -p "$LAUNCHER/Contents/MacOS" "$LAUNCHER/Contents/Resources"
  cp "$SRC/assets/NetSonar.icns" "$LAUNCHER/Contents/Resources/NetSonar.icns"
  cat > "$LAUNCHER/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>NetSonar</string>
  <key>CFBundleDisplayName</key><string>NetSonar</string>
  <key>CFBundleIdentifier</key><string>$APP_ID</string>
  <key>CFBundleExecutable</key><string>NetSonar</string>
  <key>CFBundleIconFile</key><string>NetSonar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
</dict></plist>
PL
  cat > "$LAUNCHER/Contents/MacOS/NetSonar" <<'LA'
#!/bin/bash
# NetSonar 啟動器：確定背景服務在執行，然後用瀏覽器打開儀表板。
LABEL="com.netsonar.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
URL="__URL__"
alive() { /usr/bin/curl -fs --max-time 2 "$URL/api/health" >/dev/null 2>&1; }
say() { /usr/bin/osascript -e "display dialog \"$1\" with title \"NetSonar\" buttons {\"好\"} default button 1" >/dev/null 2>&1; }
if ! alive; then
  if [ ! -f "$PLIST" ]; then
    say "找不到 NetSonar 的背景服務。請打開 net-sonar 資料夾，重新雙擊「安裝.command」。"; exit 1
  fi
  U="$(/usr/bin/id -u)"
  /bin/launchctl bootstrap "gui/$U" "$PLIST" 2>/dev/null || /bin/launchctl kickstart "gui/$U/$LABEL" 2>/dev/null
  for _ in $(/usr/bin/seq 1 30); do alive && break; /bin/sleep 0.5; done
fi
if alive; then /usr/bin/open "$URL"
else say "NetSonar 沒有成功啟動。請重新雙擊「安裝.command」；若仍失敗，執行紀錄在「家目錄/Library/Logs/NetSonar.log」。"; exit 1
fi
LA
  sed -i.bak "s|__URL__|$1|" "$LAUNCHER/Contents/MacOS/NetSonar" && rm -f "$LAUNCHER/Contents/MacOS/NetSonar.bak"
  chmod +x "$LAUNCHER/Contents/MacOS/NetSonar"
  # 用 ZIP 下載的檔案會被 macOS 貼上「來自網路」的標籤，複製過來的圖示也會帶著；拿掉才不會被擋
  xattr -dr com.apple.quarantine "$LAUNCHER" 2>/dev/null || true
  touch "$LAUNCHER"
}

remove_launcher() {
  for d in "/Applications/NetSonar.app" "$HOME_DIR/Applications/NetSonar.app"; do
    # 只刪我們自己建立的那一個（用識別名稱確認），避免誤刪同名的其他 App
    if [ -f "$d/Contents/Info.plist" ] && grep -q "$APP_ID" "$d/Contents/Info.plist" 2>/dev/null; then rm -rf "$d"; fi
  done
}

start_service() {
  [ -f "$PLIST" ] || { echo "尚未安裝，請先雙擊「安裝.command」。"; exit 1; }
  [ "$DRY" = "1" ] && return 0
  launchctl bootstrap "gui/$UIDN" "$PLIST" 2>/dev/null || launchctl kickstart "gui/$UIDN/$LABEL" 2>/dev/null || launchctl load "$PLIST"
}

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
    <key>NETSONAR_SERVICE</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
  PORT="$("$APP/.venv/bin/python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$APP/config.json")"
  URL="http://127.0.0.1:$PORT"
  remove_launcher
  build_launcher "$URL"
  echo "🧭 已在「應用程式」建立 NetSonar 圖示：$LAUNCHER"
  if [ "$DRY" = "1" ]; then echo "（測試模式）已寫入 $PLIST，網址 $URL"; return 0; fi

  launchctl bootstrap "gui/$UIDN" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
  echo "⏳ 等待儀表板啟動…"
  for _ in $(seq 1 20); do
    curl -fs "$URL/api/health" >/dev/null 2>&1 && break
    sleep 1
  done
  if curl -fs "$URL/api/health" >/dev/null 2>&1; then
    echo "✅ 安裝完成！NetSonar 已在背景執行，之後開機會自動啟動。"
    echo "   打開方式：點「應用程式」（或 Launchpad）裡的 NetSonar，也可以把它拖到 Dock。"
    echo "   網址：$URL （也可以加入瀏覽器書籤）"
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
  remove_launcher
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
  start) start_service; echo "▶️ 已啟動 NetSonar 背景服務。" ;;
  stop) stop_service; echo "⏹ 已停止 NetSonar 背景服務（下次登入或打開 NetSonar App 會再啟動）。" ;;
  status) status ;;
  *) echo "用法：$0 install | uninstall [--purge] | start | stop | status"; exit 2 ;;
esac
