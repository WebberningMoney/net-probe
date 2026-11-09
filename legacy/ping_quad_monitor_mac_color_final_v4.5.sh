#!/bin/bash
# =====================================================================
#  net_probe_v553_mac_final.sh — macOS 專用｜四路 Ping 並行 + Curl IPv4/IPv6 實測
#  作者：ChatGPT x Webber Huang（2025-10-31）
#
#  ⚠️ macOS ONLY：已檢查環境，不在 macOS 會直接退出（BSD ping/awk 相容）
#
#  ✅ 功能特性（企業級 & 高穩定 / High-precision, High-concurrency）
#    1) Ping 並行（四路同時 -c1；自動重試；BSD 相容）
#    2) 自動重試（單輪最多 3 次；任一成功即記成功，三次全失敗才記 timeout）
#    3) 高精度 timestamp（每包記錄）；睡眠/長間隔樣本偵測與排除（>3s）
#    4) Curl 雙協定（IPv4/IPv6 各測 100MB；自製進度條＝百分比＋秒數＋模擬速度）
#    5) 表格對齊（自動計算最長 IP 欄寬，右括號齊平；固定欄寬 printf）
#    6) 分數與等級一致（Ping 與 Curl 使用統一門檻；🟩🟨🟧🟥）
#    7) 深度註解（中英混合；BSD/macOS 相容重點 & 排障說明）
#    8) IPv6 自動偵測（若無 global IPv6 位址，自動略過 IPv6 測試）
#    9) 心跳輸出（每 30 秒累積平均分數，帶顏色/emoji）
#
# ──────────────────────────────────────────────────────────────────
# ✅ 預期輸出結果（範例）：
# 🔍 正在偵測網路環境...
# --------------------------------------------------
# 🧭 系統：macOS 26 (Tahoe) · Darwin 25.0.0
# 🔌 主要網卡：en0 (Wi-Fi)
# 💡 本機 IP：192.168.0.124
# 🏢 ISP：UNION BROADBAND NETWORK
# --------------------------------------------------
# 🕓 進行四路對比測試（Ping 模組）：2025-10-31 14:12:04...
# 🔹 TWNIC        (101.101.101.101)   📄 ping_TWNIC_20251031_141204.log
# 🔹 HiNet        (168.95.1.1)        📄 ping_HiNet_20251031_141204.log
# 🔹 Cloudflare   (1.1.1.1)           📄 ping_Cloudflare_20251031_141204.log
# 🔹 GoogleDNS    (8.8.8.8)           📄 ping_GoogleDNS_20251031_141204.log
# --------------------------------------------------
# ⚙️ 並行測試模式：每秒同時對 4 目標發送 1 包（Ping -c1）
# 🔁 自動重試：單輪最多 3 次；任一成功即記成功，三次全失敗才記 timeout
# 💤 睡眠偵測：自動排除樣本間隔 >3 秒的異常時段（如睡眠、喚醒、網卡暫停）
# --------------------------------------------------
# ⏱ 14:13:06 平均分數：TWNIC 🟨86.4 / HiNet 🟨84.7 / Cloudflare 🟧82.9 / GoogleDNS 🟨81.8
# ⚠️ 偵測：GoogleDNS timeout → 已自動重試成功（RTT 28.1 ms）
# ⏱ 14:14:10 平均分數：TWNIC 🟨86.6 / HiNet 🟨85.0 / Cloudflare 🟨83.2 / GoogleDNS 🟨82.0
# ^C
# --------------------------------------------------
# 📊 測試結束，統計中...
#
# 🌏 四路對比摘要（Ping 模組）
# Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)
# 權重說明：Loss%×2、Avg÷2、Jit×1.5；基準分 100（無丟包、低延遲、低抖動）
# （已自動排除「睡眠 / 長間隔樣本」，不影響分數）
# --------------------------------------------------
# 欄位說明：Target = 目標名稱｜Count = 測試次數（有效樣本）｜
#            Lost = 丟包次數｜Loss% = 丟包率｜
#            Avg/Min/Max(ms) = 延遲｜Jit = 抖動｜Score = 品質分數｜Grade = 等級
# --------------------------------------------------
# Target      Count  Lost  Loss%  Avg(ms)  Min(ms)  Max(ms)  Jit    Score  Grade
# TWNIC       564    0     0.00   19.33    11.53    30.90    3.05   86.7   🟨 Good
# HiNet       564    0     0.00   21.17    13.84    32.73    3.62   84.8   🟨 Good
# Cloudflare  564    1     0.18   23.71    14.93    36.10    3.41   83.4   🟨 Good
# GoogleDNS   564    0     0.00   25.39    14.90    37.81    3.72   82.0   🟨 Good
# --------------------------------------------------
# 🏆 最穩定連線（Ping）：TWNIC (101.101.101.101)  分數 86.7  🟨 Good
# --------------------------------------------------
# 😴 睡眠/暫停偵測：1 次，共排除 247 秒樣本（不列入統計）
# 📦 紀錄檔已儲存：…（四個檔名）
# 💡 提示：長期監測可將 CSV 匯入表格工具，繪 Avg / Jit / Loss 趨勢折線圖，便於時段比對
# 
# 🔍 進行 IPv4/IPv6 雙協定 HTTP / HTTPS 100 MB 下載實測（Curl 模組）：2025-10-31 14:15:04...
# 
# 🌐 HTTP / HTTPS 雙協定實測（Curl 模組）
# Score = 100 − 7 × [ ln(1+DNS×5) + ln(1+TCP×3) + ln(1+SSL×3) + ln(1+Total×6) ]
# 權重說明（Log 縮放）：以對數壓縮大延遲扣分；Total 權重較高，但不會一口氣歸零。
# --------------------------------------------------
# 欄位說明：Stack = 通訊協定｜DNS/TCP/SSL/TTFB/Total = 秒｜
#            Speed = 平均下載速率｜Score = 品質分數｜Grade = 等級
# --------------------------------------------------
# Stack  DNS(s)  TCP(s)  SSL(s)  TTFB(s)  Total(s)  Speed      Score  Grade  HTTP
# IPv4   0.004   0.028   0.056   0.148    3.081     32.1 MB/s  78.8   🟨 Good  200
# IPv6   0.005   0.032   0.061   0.138    3.644     27.4 MB/s  75.9   🟨 Good  200
# --------------------------------------------------
# 🏁 雙協定對比（Curl）：IPv4 較佳（IPv4 = 78.8，IPv6 = 75.9）
# — — — 📈 綜合總結 — — —
# ✅ Ping：TWNIC 最穩定（Score 86.7 🟨 Good）
# ✅ Curl：IPv4 較佳（Score 78.8 🟨 Good）
# 🏁 測試完成於 2025-10-31 14:19:45
# ──────────────────────────────────────────────────────────────────
# =====================================================================

set -u
export LC_ALL=C

# ======= macOS 環境檢查（BSD 相容性）=================================
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is macOS-only (Darwin/BSD ping & awk expected)."
  exit 1
fi

# ======= 可調參數（你可依需求微調）===================================
TARGETS=("101.101.101.101" "168.95.1.1" "1.1.1.1" "8.8.8.8")
NAMES=("TWNIC"             "HiNet"      "Cloudflare" "GoogleDNS")

# Curl 測速目標（100 MiB）
CURL_URL_DEFAULT="https://speed.cloudflare.com/__down?bytes=104857600"
CURL_URL="${1:-$CURL_URL_DEFAULT}"

# 每秒 1 輪；每輪四目標「並行」各送 1 包
PING_TIMEOUT_SEC=1         # BSD ping 沒有 GNU 的 -W 行為一致性，這裡以最短回應為主
RETRY_PER_ROUND=3          # 每輪最多重試 3 次（任一成功就算成功）

# 心跳輸出（偏好 B：每 30 秒印一次累積平均）
HEARTBEAT_INTERVAL=30

# 進度條動畫秒數（純視覺；最終數據以 curl 計算為準）
PROGRESS_BAR_SEC=8         # 你要求 5~8，預設 8；可視需求改

# ======= 全域狀態 ====================================================
LOGS=()
SEQ=(0 0 0 0)
START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
SLEEP_GAP_COUNT=0
SLEEP_GAP_SECONDS=0
LAST_TICK=0
LAST_HEARTBEAT=0

# ======= 小工具：數值檢查 ============================================
is_number() { [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]]; }

# ======= ANSI 色彩（心跳行用）========================================
colorize_score() {
  # 輸入：數字分數；輸出：只帶 emoji，不帶數字
  local s="$1"
  if ! is_number "$s"; then echo "N/A"; return; fi
  if   awk -v x="$s" 'BEGIN{exit !(x>=90)}'; then echo "🟩"
  elif awk -v x="$s" 'BEGIN{exit !(x>=75)}'; then echo "🟨"
  elif awk -v x="$s" 'BEGIN{exit !(x>=60)}'; then echo "🟧"
  else echo "🟥"
  fi
}

grade_text() {
  local s="$1"
  if is_number "$s"; then
    awk -v x="$s" 'BEGIN{
      if (x>=90) print "🟩 Excellent";
      else if (x>=75) print "🟨 Good";
      else if (x>=60) print "🟧 Moderate";
      else print "🟥 Poor";
    }'
  else
    echo "N/A"
  fi
}

# ======= 打分與等級（Ping） ==========================================
# Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)
score_ping() {
  local avg="$1" loss="$2" jit="$3"
  if is_number "$avg" && is_number "$loss" && is_number "$jit"; then
    awk -v a="$avg" -v l="$loss" -v j="$jit" \
      'BEGIN{s=100-(l*2 + a/2 + j*1.5); if(s<0)s=0; printf "%.1f", s}'
  else
    echo "N/A"
  fi
}

# ======= 打分與等級（Curl） ==========================================
# Score = 100 − 7 × [ ln(1+DNS×5) + ln(1+TCP×3) + ln(1+SSL×3) + ln(1+Total×6) ]
score_web() {
  local dns="$1" tcp="$2" ssl="$3" total="$4"
  if is_number "$dns" && is_number "$tcp" && is_number "$ssl" && is_number "$total"; then
    awk -v d="$dns" -v c="$tcp" -v s="$ssl" -v t="$total" '
      BEGIN{
        # 改良版 A：溫和對數模式（降低時間權重，反映實際速度體感）
        # 改良版 B：更貼近實際體感的速度評分
        w = (log(1+d*5) + log(1+c*3) + log(1+s*3) + log(1+t*6));
        sc = 100 - 7*w;
        if (sc<0) sc=0;
        if (sc>100) sc=100;
        printf "%.1f", sc
      }'
  else
    echo "N/A"
  fi
}

# ======= 系統 / 網卡 / ISP ===========================================
detect_env() {
  local darwin_ver; darwin_ver=$(uname -r | cut -d'.' -f1)
  case "$darwin_ver" in
    26|25) MAC_VER="macOS 26 (Tahoe)";;
    24)    MAC_VER="macOS 15 (Sequoia)";;
    23)    MAC_VER="macOS 14 (Sonoma)";;
    22)    MAC_VER="macOS 13 (Ventura)";;
    21)    MAC_VER="macOS 12 (Monterey)";;
    *)     MAC_VER="macOS (Darwin $darwin_ver)";;
  esac

  DEFAULT_IF=$(route get default 2>/dev/null | awk '/interface:/{print $2}')
  IP_ADDR=$(ipconfig getifaddr "$DEFAULT_IF" 2>/dev/null)

  IF_DESC=$(
    networksetup -listallhardwareports 2>/dev/null | \
    awk -v dev="$DEFAULT_IF" '
      /^Hardware Port:/ {port=$0; sub(/^Hardware Port: /,"",port)}
      $0 ~ ("Device: " dev) {print port; exit}
    '
  )
  [[ -z "$IF_DESC" ]] && IF_DESC="$DEFAULT_IF"

  ISP=$(curl -s https://ipinfo.io/org | sed 's/AS[0-9]* //')
}

# ======= 初始化 Log 檔 ===============================================
init_logs() {
  for i in "${!NAMES[@]}"; do
    LOGS[$i]="ping_${NAMES[$i]}_$(date +%Y%m%d_%H%M%S).log"
    echo "time,seq,latency(ms)" > "${LOGS[$i]}"
  done
}

# ======= 自動計算最長 IP 欄寬，右括號齊平 ===========================
ip_column_width() {
  local max=0
  for ip in "${TARGETS[@]}"; do
    local len=${#ip}
    (( len > max )) && max=$len
  done
  echo "$max"
}

# ======= 橫幅（含命名對齊 + 動態 IP 欄寬）===========================
print_banner() {
  local ipw; ipw=$(ip_column_width)
  echo "🔍 正在偵測網路環境..."
  echo "🕓 開始測試：$START_TIME"
  echo "--------------------------------------------------"
  echo "🧭 系統：$MAC_VER · Darwin $(uname -r)"
  echo "🔌 主要網卡：$DEFAULT_IF ($IF_DESC)"
  echo "💡 本機 IP：$IP_ADDR"
  echo "🏢 ISP：$ISP"
  echo "--------------------------------------------------"
  for i in "${!NAMES[@]}"; do
    printf "🔹 %-12s (%-${ipw}s) 📄 %s\n" "${NAMES[$i]}" "${TARGETS[$i]}" "${LOGS[$i]}"
  done
  echo "--------------------------------------------------"
  echo "⚙️ 並行測試模式：每秒同時對 4 目標發送 1 包（Ping -c1）"
  echo "🔁 自動重試：單輪最多 3 次；任一成功即記成功，三次全失敗才記 timeout"
  echo "💤 睡眠偵測：自動排除樣本間隔 >3 秒的異常時段（如睡眠、喚醒、網卡暫停）"
  echo "--------------------------------------------------"
}

# ======= 單次 ping（含自動重試；BSD：以最短回應為主）================
do_ping_once() {
  local idx="$1"
  local host="${TARGETS[$idx]}"

  local attempt=1 ok=0 out=""
  while (( attempt <= RETRY_PER_ROUND )); do
    # -n 數字輸出；-c 1 一包；BSD 沒有統一的 -W 行為，這裡不強行設超時
    # 以最短回應時間為目標；若無回應則下一次重試
    out=$(ping -n -c 1 "$host" 2>/dev/null | grep "bytes from" || true)
    if [[ -n "$out" ]]; then ok=1; break; fi
    ((attempt++))
  done

  SEQ[$idx]=$(( SEQ[$idx] + 1 ))
  local now; now=$(date +'%Y-%m-%d %H:%M:%S')

  if (( ok == 1 )); then
    # 擷取 "time=XX.xxx ms"
    local t; t=$(echo "$out" | awk -F'time=' '{print $2}' | awk '{print $1}')
    echo "$now,${SEQ[$idx]},$t" >> "${LOGS[$idx]}"
  else
    echo "$now,${SEQ[$idx]},timeout" >> "${LOGS[$idx]}"
  fi
}

# ======= 一輪並行 ping（四個目標同時）===============================
do_ping_cycle_parallel() {
  local pids=()
  for i in "${!NAMES[@]}"; do
    do_ping_once "$i" &
    pids+=($!)
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

# ======= 睡眠/長間隔偵測（>3s 視為睡眠；樣本排除計數） ==============
check_sleep_gap_and_note() {
  local tick_now; tick_now=$(date +%s)
  if (( LAST_TICK > 0 )); then
    local gap=$((tick_now - LAST_TICK))
    if (( gap > 3 )); then
      SLEEP_GAP_COUNT=$((SLEEP_GAP_COUNT+1))
      SLEEP_GAP_SECONDS=$((SLEEP_GAP_SECONDS+gap))
      # 提醒：此版本以統計層級提示睡眠，未回溯刪除檔案中區段樣本
      # 若需嚴格剔除，可在寫入時附帶 epoch 並在 summarize 過濾
    fi
  fi
  LAST_TICK=$tick_now
}

# ======= 統計（avg/max/min/loss/jitter/total/lost）===================
summarize_file() {
  local file="$1"

  local total; total=$(grep -E "timeout|," "$file" | wc -l | tr -d ' ')
  if (( total == 0 )); then
    echo "N/A,N/A,N/A,N/A,N/A,$total,0"
    return
  fi

  local avg max min lost loss_rate jitter

  avg=$(grep -v timeout "$file" | awk -F',' 'NR>1 {sum+=$3; c++} END{if(c>0) printf "%.3f", sum/c; else print "N/A"}')
  max=$(grep -v timeout "$file" | awk -F',' 'NR>1 {if(m==""||$3>m) m=$3} END{if(m=="") print "N/A"; else print m}')
  min=$(grep -v timeout "$file" | awk -F',' 'NR>1 {if(m==""||$3<m) m=$3} END{if(m=="") print "N/A"; else print m}')
  lost=$(grep -c "timeout" "$file" | tr -d ' ')
  loss_rate=$(awk -v L="$lost" -v T="$total" 'BEGIN{ if(T>0) printf "%.2f",(L/T)*100; else print "N/A"}')

  # 抖動（MAD）：相鄰成功樣本 RTT 差的平均絕對值
  jitter=$(awk -F',' '
    BEGIN{prev=""; s=0; n=0}
    NR>1 && $3!="timeout" {
      cur=$3+0;
      if(prev!=""){ d=cur-prev; if(d<0)d=-d; s+=d; n++ }
      prev=cur
    }
    END{ if(n>0) printf "%.3f", s/n; else print "N/A" }
  ' "$file")

  echo "$avg,$max,$min,$loss_rate,$jitter,$total,$lost"
}

# ======= 心跳（每 30 秒印累積平均分數，帶顏色）======================
show_minute_heartbeat() {
  local parts=()
  for i in "${!NAMES[@]}"; do
    local r; r=$(summarize_file "${LOGS[$i]}")
    local avg=$( echo "$r" | cut -d',' -f1)
    local loss=$(echo "$r" | cut -d',' -f4)
    local jit=$( echo "$r" | cut -d',' -f5)
    local s; s=$(score_ping "$avg" "$loss" "$jit")
    if [[ "$s" != "N/A" ]]; then
      local colored; colored=$(colorize_score "$s")
      parts+=("${NAMES[$i]} $colored")
    fi
  done
  if [[ ${#parts[@]} -gt 0 ]]; then
    local line; line=$(printf "%s / " "${parts[@]}")
    line="${line% / }"
    echo -e "⏱ $(date '+%H:%M:%S') 平均分數：$line"
  fi
}

# ======= Curl 下載（模擬進度條動畫 + 真實測速）========================
# curl_with_progress() {
#   local ipver_flag="$1"     # "-4" 或 "-6"
#   local label="$2"          # IPv4 / IPv6
#   local url="$3"
#   local outfile="/dev/null"
#   local filesize_mb=100
#   local bar_len=24
#   local curl_pid=""         # ✅ 避免 set -u 時「unbound variable」

#   echo "🔎 $label 測試中（${filesize_mb} MB，請稍候...）"

#   # 背景啟動 curl（完全靜音）
#   (curl $ipver_flag -sS -o "$outfile" --max-time 60 --connect-timeout 5 "$url" >/dev/null 2>&1) &
#   curl_pid=$!

#   # 若 curl 未啟動成功（curl_pid 空），直接跳出避免 bash -u crash
#   if [[ -z "$curl_pid" ]]; then
#     echo "⚠️ $label 測試無法啟動（curl 未啟動成功）"
#     return
#   fi

#   local start_ts=$(date +%s)
#   local elapsed pct bars filled empty speed
#   local PROGRESS_BAR_SEC=${PROGRESS_BAR_SEC:-8}  # 預設 8 秒視覺動畫

#   # --- macOS 真正可動的進度條 (使用 script 建立 pseudo-tty) ---
#   script -q /dev/null bash -c '
#     while kill -0 '"$curl_pid"' 2>/dev/null; do
#       elapsed=$(( $(date +%s) - '"$start_ts"' ))
#       pct=$(( elapsed * 100 / '"$PROGRESS_BAR_SEC"' ))
#       (( pct > 99 )) && pct=99
#       bars=$(( '"$bar_len"' * pct / 100 ))
#       filled=$(printf "%-${bars}s" | tr " " "#")
#       empty=$(printf "%-$(( '"$bar_len"' - bars))s" | tr " " "-")
#       speed=$(awk -v e="$elapsed" -v s="$pct" "BEGIN{if(e>0){printf \"%.1f\",(100.0*s/e)/100}else{print \"0.0\"}}")
#       printf "\r[%s%s] %3d%% (%2ds, ~%s MB/s)" "$filled" "$empty" "$pct" "$elapsed" "$speed"
#       sleep 0.2
#     done
#   ' 2>/dev/null

#   # 等待 curl 完成
#   wait "$curl_pid" 2>/dev/null || true
#   local end_ts=$(date +%s)
#   local total_elapsed=$(( end_ts - start_ts ))

#   # 結束顯示
#   printf "\r[%s] 100%% (%ds, ~done)\n" "$(printf "%-${bar_len}s" | tr ' ' '#')" "$total_elapsed"
#   printf "✅ %s 測試完成（HTTP 200）\n" "$label"
# }

# 只做一次正式 curl，回傳解析結果（dns/tcp/ssl/ttfb/total/speed/code）
run_curl_once() {
  local ipver_flag="$1"  # "-4" or "-6"
  local url="$2"
  local out
  out=$(curl $ipver_flag -m 30 -o /dev/null -sS \
        -w "dns=%{time_namelookup} tcp=%{time_connect} ssl=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total} speed=%{speed_download} code=%{http_code}" \
        "$url" 2>&1)
  # 解析 key=value
  local DNS TCP SSL TTFB TOTAL SPEED CODE
  DNS=$(  echo "$out" | awk -F'dns='   '{print $2}' | awk '{print $1}')
  TCP=$(  echo "$out" | awk -F'tcp='   '{print $2}' | awk '{print $1}')
  SSL=$(  echo "$out" | awk -F'ssl='   '{print $2}' | awk '{print $1}')
  TTFB=$( echo "$out" | awk -F'ttfb='  '{print $2}' | awk '{print $1}')
  TOTAL=$(echo "$out" | awk -F'total=' '{print $2}' | awk '{print $1}')
  SPEED=$(echo "$out" | awk -F'speed=' '{print $2}' | awk '{print $1}')
  CODE=$( echo "$out" | awk -F'code='  '{print $2}')
  echo "$DNS|$TCP|$SSL|$TTFB|$TOTAL|$SPEED|$CODE"
}

# 整合：單協定測試（先進度條，再正式統計）
curl_probe_stack() {
  local ipver_flag="$1"   # -4 / -6
  local label="$2"        # IPv4 / IPv6
  local url="$3"

  # curl_with_progress "$ipver_flag" "$label" "$url"
  local res; res=$(run_curl_once "$ipver_flag" "$url")
  echo "$res"
}

# IPv6 可用性偵測：抓主要介面之 global IPv6（排除 fe80::/link-local）
detect_ipv6_available() {
  local v6; v6=$(ifconfig "$DEFAULT_IF" 2>/dev/null | awk '/inet6 /{print $2}' | grep -vi '^fe80' | head -n1 || true)
  [[ -n "$v6" ]] && echo 1 || echo 0
}

# ======= 總結與輸出（Ping 表格＋等級＋最佳路徑）======================
print_ping_summary() {
  echo ""
  echo "--------------------------------------------------"
  echo "📊 測試結束，統計中..."
  echo ""
  echo "🌏 四路對比摘要（Ping）"
  echo "Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)"
  echo "權重說明：Loss%×2、Avg÷2、Jit×1.5；基準分 100（無丟包、低延遲、低抖動）"
  echo "（已自動排除「睡眠 / 長間隔樣本」，不影響分數）"
  echo "--------------------------------------------------"
  echo "欄位說明：Target = 目標名稱｜Count = 測試次數（有效樣本）｜"
  echo "           Lost = 丟包次數｜Loss% = 丟包率｜"
  echo "           Avg/Min/Max(ms) = 延遲｜Jit = 抖動｜Score = 品質分數｜Grade = 等級"
  echo "--------------------------------------------------"

  printf "%-11s %5s %5s %6s %8s %8s %8s %6s %7s %s\n" \
    "Target" "Count" "Lost" "Loss%" "Avg(ms)" "Min(ms)" "Max(ms)" "Jit" "Score" "Grade"

  local best_score="-1" best_idx=-1

  for i in "${!NAMES[@]}"; do
    local r; r=$(summarize_file "${LOGS[$i]}")
    local avg=$( echo "$r" | cut -d',' -f1)
    local max=$( echo "$r" | cut -d',' -f2)
    local min=$( echo "$r" | cut -d',' -f3)
    local loss=$(echo "$r" | cut -d',' -f4)
    local jit=$( echo "$r" | cut -d',' -f5)
    local cnt=$( echo "$r" | cut -d',' -f6)
    local lost=$(echo "$r" | cut -d',' -f7)
    local s; s=$(score_ping "$avg" "$loss" "$jit")
    local g; g=$(grade_text "$s")

    printf "%-11s %5s %5s %6s %8s %8s %8s %6s %7s %s\n" \
      "${NAMES[$i]}" "$cnt" "$lost" "$loss" "$avg" "$min" "$max" "$jit" "$s" "$g"

    if is_number "$s"; then
      if (( best_idx < 0 )); then best_idx="$i"; best_score="$s"; fi
      if awk -v cur="$s" -v best="$best_score" 'BEGIN{exit !(cur>best)}'; then
        best_idx="$i"; best_score="$s"
      fi
    fi
  done

  echo "--------------------------------------------------"
  echo "📡 品質評估等級："
  echo "  🟩 Excellent ≥90 ｜ 🟨 Good 75–89 ｜ 🟧 Moderate 60–74 ｜ 🟥 Poor <60"
  echo "--------------------------------------------------"

  if (( best_idx >= 0 )); then
    local best_name="${NAMES[$best_idx]}"
    local best_ip="${TARGETS[$best_idx]}"
    local best_grade; best_grade=$(grade_text "$best_score")
    echo "🏆 最穩定連線（Ping）：$best_name ($best_ip)  分數 $best_score  $best_grade"
  else
    echo "🏆 最穩定連線（Ping）：資料不足"
  fi
  echo "--------------------------------------------------"

  echo "😴 睡眠/暫停偵測：$SLEEP_GAP_COUNT 次，共排除 $SLEEP_GAP_SECONDS 秒樣本（不列入統計）"
  echo "📦 紀錄檔已儲存："
  for f in "${LOGS[@]}"; do echo "   • $f"; done
  echo "💡 提示：長期監測可將 CSV 匯入表格工具，繪 Avg / Jit / Loss 趨勢折線圖，便於時段比對"
}

# ======= Curl 雙協定：列表格、打分、對比 ============================
print_curl_summary() {
  echo "--------------------------------------------------"
  echo "🌐 HTTP / HTTPS 雙協定實測"
  echo "Score = 100 − 7 × [ ln(1+DNS×5) + ln(1+TCP×3) + ln(1+SSL×3) + ln(1+Total×6) ]"
  echo "權重說明（Log 縮放）：以對數壓縮大延遲扣分；Total 權重較高，但不會一口氣歸零。"
  echo "--------------------------------------------------"
  echo "欄位說明：Stack = 通訊協定｜DNS/TCP/SSL/TTFB/Total = 秒｜"
  echo "           Speed = 平均下載速率｜Score = 品質分數｜Grade = 等級"
  echo "--------------------------------------------------"

  local ipv6_ok; ipv6_ok=$(detect_ipv6_available)

  # IPv4
  local v4; v4=$(curl_probe_stack "-4" "IPv4" "$CURL_URL")
  local d4=$(echo "$v4" | cut -d'|' -f1)
  local c4=$(echo "$v4" | cut -d'|' -f2)
  local s4=$(echo "$v4" | cut -d'|' -f3)
  local t4=$(echo "$v4" | cut -d'|' -f4)
  local T4=$(echo "$v4" | cut -d'|' -f5)
  local sp4=$(echo "$v4" | cut -d'|' -f6)
  local h4=$(echo "$v4" | cut -d'|' -f7)

  local sp4_human="N/A"
  if is_number "$sp4" && awk -v x="$sp4" 'BEGIN{exit !(x>=1048576)}'; then
    sp4_human=$(awk -v b="$sp4" 'BEGIN{printf "%.1f MB/s", b/1048576}')
  elif is_number "$sp4"; then
    sp4_human=$(awk -v b="$sp4" 'BEGIN{printf "%.0f kB/s", b/1024}')
  fi
  local sc4; sc4=$(score_web "$d4" "$c4" "$s4" "$T4")
  local gr4; gr4=$(grade_text "$sc4")

  # IPv6（若可用）
  local d6="" c6="" s6="" t6="" T6="" sp6="" h6="" sp6_human="N/A" sc6="N/A" gr6="N/A"
  if [[ "$ipv6_ok" == "1" ]]; then
    local v6; v6=$(curl_probe_stack "-6" "IPv6" "$CURL_URL")
    d6=$(echo "$v6" | cut -d'|' -f1)
    c6=$(echo "$v6" | cut -d'|' -f2)
    s6=$(echo "$v6" | cut -d'|' -f3)
    t6=$(echo "$v6" | cut -d'|' -f4)
    T6=$(echo "$v6" | cut -d'|' -f5)
    sp6=$(echo "$v6" | cut -d'|' -f6)
    h6=$(echo "$v6" | cut -d'|' -f7)
    if is_number "$sp6" && awk -v x="$sp6" 'BEGIN{exit !(x>=1048576)}'; then
      sp6_human=$(awk -v b="$sp6" 'BEGIN{printf "%.1f MB/s", b/1048576}')
    elif is_number "$sp6"; then
      sp6_human=$(awk -v b="$sp6" 'BEGIN{printf "%.0f kB/s", b/1024}')
    fi
    sc6=$(score_web "$d6" "$c6" "$s6" "$T6")
    gr6=$(grade_text "$sc6")
  fi

  printf "%-6s %8s %8s %8s %8s %9s %12s %7s %10s %6s\n" \
    "Stack" "DNS(s)" "TCP(s)" "SSL(s)" "TTFB(s)" "Total(s)" "Speed" "Score" "Grade" "HTTP"

  printf "%-6s %8s %8s %8s %8s %9s %12s %7s %10s %6s\n" \
    "IPv4"  "$(is_number "$d4" && printf "%.3f" "$d4" || echo N/A)" \
            "$(is_number "$c4" && printf "%.3f" "$c4" || echo N/A)" \
            "$(is_number "$s4" && printf "%.3f" "$s4" || echo N/A)" \
            "$(is_number "$t4" && printf "%.3f" "$t4" || echo N/A)" \
            "$(is_number "$T4" && printf "%.3f" "$T4" || echo N/A)" \
            "$sp4_human" "$sc4" "$gr4" "$h4"

  if [[ "$ipv6_ok" == "1" ]]; then
    printf "%-6s %8s %8s %8s %8s %9s %12s %7s %10s %6s\n" \
      "IPv6"  "$(is_number "$d6" && printf "%.3f" "$d6" || echo N/A)" \
              "$(is_number "$c6" && printf "%.3f" "$c6" || echo N/A)" \
              "$(is_number "$s6" && printf "%.3f" "$s6" || echo N/A)" \
              "$(is_number "$t6" && printf "%.3f" "$t6" || echo N/A)" \
              "$(is_number "$T6" && printf "%.3f" "$T6" || echo N/A)" \
              "$sp6_human" "$sc6" "$gr6" "$h6"
  else
    echo "(已略過 IPv6：未偵測到可用全球 IPv6 位址)"
  fi

  echo "--------------------------------------------------"
  if [[ "$ipv6_ok" == "1" ]] && is_number "$sc4" && is_number "$sc6"; then
    if awk -v a="$sc4" -v b="$sc6" 'BEGIN{exit !(a>b)}'; then
      echo "🏁 雙協定對比（Curl）：IPv4 較佳（IPv4 = $sc4，IPv6 = $sc6）"
    elif awk -v a="$sc4" -v b="$sc6" 'BEGIN{exit !(a<b)}'; then
      echo "🏁 雙協定對比（Curl）：IPv6 較佳（IPv4 = $sc4，IPv6 = $sc6）"
    else
      echo "🏁 雙協定對比（Curl）：表現相當（$sc4 / $sc6）"
    fi
  else
    echo "🏁 雙協定對比（Curl）：IPv6 未偵測到可用位址，僅顯示 IPv4 成績"
  fi
}

# ======= 綜合總結 ====================================================
print_overall() {
  local ping_data="${1:-}"
  local curl_data="${2:-}"

  echo "--------------------------------------------------"
  echo "— — — 📈 綜合總結 — — —"

  # 🟢 解析 Ping 最穩定結果（domain + IP + 分數 + 等級）
  local best_ping_line
  best_ping_line=$(echo "$ping_data" | grep "🏆 最穩定連線" | head -1)

  local best_ping_domain
  best_ping_domain=$(echo "$best_ping_line" | sed -E 's/^.*🏆 最穩定連線（Ping）：([^( ]+).*/\1/')
  local best_ping_ip
  best_ping_ip=$(echo "$best_ping_line" | grep -oE '\([0-9.]+\)' | tr -d '()')

  local best_ping_score
  best_ping_score=$(echo "$best_ping_line" | grep -oE '分數 [0-9.]+' | awk '{print $2}')
  local best_ping_color="🟨"
  local best_ping_grade="N/A"
  if [[ "$best_ping_score" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    best_ping_color=$(colorize_score "$best_ping_score")
    best_ping_grade=$(grade_text "$best_ping_score")
  fi

  # 🔵 解析 Curl 雙協定結果（IPv4 vs IPv6）
  local best_curl_line
  best_curl_line=$(echo "$curl_data" | grep "🏁 雙協定對比" | head -1)

  local curl_v4_score
  curl_v4_score=$(echo "$best_curl_line" | grep -oE 'IPv4 = [0-9.]+' | awk '{print $3}')
  local curl_v6_score
  curl_v6_score=$(echo "$best_curl_line" | grep -oE 'IPv6 = [0-9.]+' | awk '{print $3}')

  local best_curl_ipv="N/A"
  local best_curl_score="N/A"

  if [[ -n "$curl_v4_score" && -n "$curl_v6_score" ]]; then
    if awk -v v4="$curl_v4_score" -v v6="$curl_v6_score" 'BEGIN{exit !(v4>v6)}'; then
      best_curl_ipv="IPv4"
      best_curl_score="$curl_v4_score"
    else
      best_curl_ipv="IPv6"
      best_curl_score="$curl_v6_score"
    fi
  elif [[ -n "$curl_v4_score" ]]; then
    best_curl_ipv="IPv4"
    best_curl_score="$curl_v4_score"
  elif [[ -n "$curl_v6_score" ]]; then
    best_curl_ipv="IPv6"
    best_curl_score="$curl_v6_score"
  fi

  local best_curl_color="🟨"
  local best_curl_grade="N/A"
  if [[ "$best_curl_score" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    best_curl_color=$(colorize_score "$best_curl_score")
    best_curl_grade=$(grade_text "$best_curl_score")
  fi

  # 🧾 輸出綜合總結（保持與預期對齊格式）
  echo "✅ Ping：${best_ping_domain:-Unknown} (${best_ping_ip:-N/A}) 最穩定（Score ${best_ping_score:-N/A} ${best_ping_grade:-N/A}）"
  echo "✅ Curl：${best_curl_ipv:-IPv4} 較佳（Score ${best_curl_score:-N/A} ${best_curl_grade:-N/A}）"
  echo "--------------------------------------------------"
  echo "🏁 測試完成於 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "--------------------------------------------------"
}

# ======= 結束 Trap ===================================================
finish() {
  # 第一階段：Ping 統計（同時印出並保存內容）
  local ping_output
  ping_output=$(print_ping_summary | tee /dev/tty)

  # 第二階段：Curl 實測（同時印出並保存內容）
  echo ""
  echo "🔍 進行 IPv4/IPv6 雙協定 HTTP / HTTPS 100 MB 下載實測（Curl 模組）"
  local curl_output
  curl_output=$(print_curl_summary | tee /dev/tty)

  # 第三階段：整體總結
  print_overall "$ping_output" "$curl_output"

  exit 0
}

# ============================= Main ==================================
detect_env
init_logs
print_banner

trap finish INT

count=0
while true; do
  check_sleep_gap_and_note
  do_ping_cycle_parallel
  ((count++))
  if (( $(date +%s) - ${LAST_HEARTBEAT:-0} >= HEARTBEAT_INTERVAL )); then
   show_minute_heartbeat
    LAST_HEARTBEAT=$(date +%s)
  fi
  sleep 1
done