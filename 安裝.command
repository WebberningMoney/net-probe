#!/usr/bin/env bash
# 雙擊這個檔案即可安裝 NetSonar（開機自動在背景執行，之後不需要 Terminal）。
cd "$(dirname "$0")"
echo "═══ NetSonar 安裝 ═══"
bash scripts/netsonar_service.sh install
echo
read -n 1 -s -r -p "按任意鍵關閉這個視窗…"
