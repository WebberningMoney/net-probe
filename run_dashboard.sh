#!/usr/bin/env bash
# run_dashboard.sh —— 一鍵啟動本機網頁儀表板。
# 做的事：① 確認 Python ≥ 3.10 ② 第一次自動建立 .venv 並安裝套件 ③ 啟動伺服器 ④ 開瀏覽器
# 🔰 venv（虛擬環境）= 這個專案專用的「套件小倉庫」，和你電腦其他 Python 完全隔離。
set -eu
cd "$(dirname "$0")/dashboard"

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "❌ 需要 Python 3.10 以上（可用 PYTHON=/path/to/python3 ./run_dashboard.sh 指定）" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "🔧 第一次執行：建立專屬虛擬環境 .venv ..."
  "$PY" -m venv .venv
fi
# requirements.txt 有變動才重新安裝（用檔案內容的雜湊值判斷）
STAMP=".venv/.req_hash"
HASH=$(shasum requirements.txt | cut -d' ' -f1)
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$HASH" ]; then
  echo "📦 安裝套件（fastapi、uvicorn）..."
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  echo "$HASH" > "$STAMP"
fi

PORT=$(.venv/bin/python -c 'import json;print(json.load(open("config.json"))["port"])')
URL="http://127.0.0.1:$PORT"
echo "🚀 儀表板啟動中：$URL （按 Ctrl+C 結束）"
# 稍等伺服器就緒再開瀏覽器（macOS 的 open）
( sleep 2; command -v open >/dev/null 2>&1 && open "$URL" ) &
exec .venv/bin/python serve.py
