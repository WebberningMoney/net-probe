#!/bin/bash
# =====================================================================
#  net_probe.sh — macOS 專用｜四路 Ping 並行 + Curl IPv4/IPv6 實測
#  (原檔名 ping_quad_monitor_mac_color_final_v4.5.sh / 內部版號 v5.53)
#
#  作者：ChatGPT x Webber Huang（2025-10-31）
#  授權：MIT License（見 LICENSE）
#
#  ⚠️ macOS ONLY：偵測到不是 macOS 會直接結束（需要 BSD 版 ping / awk）
# =====================================================================
#
# 📖 這份註解版的閱讀方式
# ---------------------------------------------------------------------
#  本檔為 v4.7：在原版 v4.5 加上完整註解，並修正 KI-1 ~ KI-11（見 CHANGELOG）。
#  原版 v4.5 保留在 legacy/，可與本檔對照學習「bug 是怎麼修的」。
#  讀的順序建議：
#     ① 先看「整體流程」  → 知道程式在幹嘛
#     ② 再看「第 0~2 區」 → 設定與基本工具
#     ③ 然後「第 3~6 區」 → 核心：ping 怎麼並行、怎麼統計
#     ④ 最後「第 7~9 區」 → curl 測速、報表、收尾
#
#  註解符號：
#     💡 觀念說明（為什麼這樣寫）
#     🔰 初學者小教室（Bash / awk 語法解釋）
#     🛠 FIXED（已修正的問題；註解保留「原本哪裡有問題」方便對照學習）
#        對應 README.md 的「已知問題」表格編號 KI-1 ~ KI-11
#
# 🗺️ 整體流程（Big Picture）
# ---------------------------------------------------------------------
#   啟動
#    │
#    ├─ detect_env      偵測系統版本、網卡、本機 IP、ISP
#    ├─ init_logs       替每個目標建立一個 CSV 紀錄檔
#    ├─ print_banner    印出開頭資訊
#    ├─ trap finish INT 設定：按下 Ctrl+C 時，不要直接死掉，去執行 finish()
#    │
#    └─ 無限迴圈（每秒一輪）
#         ├─ check_sleep_gap_and_note   檢查電腦是否剛睡醒
#         ├─ do_ping_cycle_parallel     4 個目標「同時」各 ping 1 次
#         ├─ （每 30 秒）show_minute_heartbeat  印出目前累積平均分數
#         └─ sleep 1
#
#   使用者按 Ctrl+C
#    └─ finish()
#         ├─ 1. print_ping_summary   Ping 統計表 + 評分
#         ├─ 2. print_curl_summary   Curl 下載實測（IPv4 / IPv6）
#         └─ 3. print_overall        綜合總結
#
# 📐 評分公式（Ping）
# ---------------------------------------------------------------------
#   Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)    ，最低 0 分
#     Loss% = 丟包率（%）    Avg = 平均延遲（ms）    Jit = 抖動（ms）
#   例：Loss 0%、Avg 20ms、Jit 3ms → 100 − (0 + 10 + 4.5) = 85.5 分
#
# 📐 評分公式（Curl）
# ---------------------------------------------------------------------
#   Score = 100 − 7 × [ ln(1+DNS×5) + ln(1+TCP×3) + ln(1+SSL×3) + ln(1+Total×6) ]
#   💡 用自然對數 ln 的原因：時間越長，「每多一秒」的扣分越少，
#      避免一次很慢就直接歸零（對數會把大數字「壓扁」）。
#
# 🚦 等級門檻（Ping 與 Curl 共用）
# ---------------------------------------------------------------------
#   🟩 Excellent ≥ 90   🟨 Good 75–89   🟧 Moderate 60–74   🟥 Poor < 60
#
# ▶ 使用方式
# ---------------------------------------------------------------------
#   chmod +x net_probe.sh
#   ./net_probe.sh                         # 使用預設 Cloudflare 100MB 測速檔
#   ./net_probe.sh "https://example.com/big.bin"   # 自訂 Curl 測速網址（第 1 個參數）
#   按 Ctrl+C 結束測試並顯示完整報表
# =====================================================================


# =====================================================================
# 第 0 區：Shell 安全設定
# =====================================================================

# 🔰 `set -u`：使用「沒設定過的變數」時直接報錯，而不是默默當成空字串。
#    💡 好處：打錯變數名稱時能立刻發現。
#    ⚠️ 副作用：之後所有變數都必須先給初始值（所以下面會看到一堆 xxx=0）。
set -u

# 🔰 `export LC_ALL=C`：強制使用最基本的 "C" 語系。
#    💡 為什麼重要？不同語系下，小數點可能是「.」或「,」，
#       awk / printf 的排序與數字解析也可能不同。
#       固定成 C 語系，才能保證 3.14 永遠是 3.14，而不是 3,14。
export LC_ALL=C


# =====================================================================
# 第 1 區：環境檢查與可調參數
# =====================================================================

# ---- 1-1 只允許在 macOS 執行 -----------------------------------------
# 🔰 `uname -s` 會印出系統名稱：macOS 是 "Darwin"，Linux 是 "Linux"。
#    `[[ ... ]]` 是 Bash 的條件判斷；`$(...)` 把指令輸出當成字串使用。
# 💡 本程式用到 macOS 專屬的 ping 參數、route、ipconfig、networksetup，
#    在 Linux 會出錯，所以一開始就擋掉，比跑到一半壞掉更友善。
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is macOS-only (Darwin/BSD ping & awk expected)."
  exit 1
fi

# ---- 1-2 測試目標（可自行修改）---------------------------------------
# 🔰 這是 Bash「陣列」：TARGETS[0]="101.101.101.101"、TARGETS[1]="168.95.1.1"…
#    ⚠️ 兩個陣列「順序必須一一對應」：TARGETS[i] 的名字就是 NAMES[i]。
#    想換目標？兩個陣列同步改即可（可增減，程式會自動適應數量，
#    但畫面文字「4 目標」是寫死的字串，數量變了請一併修改）。
TARGETS=("101.101.101.101" "168.95.1.1" "1.1.1.1" "8.8.8.8")
NAMES=("TWNIC"             "HiNet"      "Cloudflare" "GoogleDNS")

# ---- 1-3 Curl 測速檔案網址 -------------------------------------------
# 🔰 `${1:-預設值}`：若執行時有給第 1 個參數就用它，否則用預設值。
#    bytes=104857600 = 100 × 1024 × 1024 = 100 MiB。
CURL_URL_DEFAULT="https://speed.cloudflare.com/__down?bytes=104857600"
CURL_URL="${1:-$CURL_URL_DEFAULT}"

# ---- 1-4 Ping 行為參數 -----------------------------------------------
# 🛠 FIXED KI-3 / KI-6：原版這個變數沒被使用（死參數），ping 等於沒有逾時。
#    現在它會真的傳給 ping（-W 毫秒、-t 秒），每個封包最多等這麼久，
#    斷線的目標不會再把整輪拖慢。
PING_TIMEOUT_SEC=1

# 每輪最多嘗試幾次；只要其中一次成功就算成功。
RETRY_PER_ROUND=3

# ---- 1-5 心跳輸出間隔（秒）-------------------------------------------
# 💡 「心跳」= 測試進行中，定期印一行目前累積的平均分數，
#    讓你知道程式還活著，不用等到 Ctrl+C 才看到結果。
HEARTBEAT_INTERVAL=30

# ---- 1-6 睡眠偵測門檻（秒）-------------------------------------------
# 兩輪之間隔超過這麼久，就視為電腦睡眠 / 網卡暫停，該輪樣本會被丟棄。
# 💡 為什麼是 10？最壞情況一輪要 ping 3 次 × 1 秒逾時，再加 sleep 1 秒 ≈ 4 秒。
#    原版門檻是 3 秒，目標斷線時正常的慢輪次會被誤判成睡眠。
SLEEP_GAP_THRESHOLD=10

# ---- 1-7 Curl 下載最長秒數 -------------------------------------------
# 可用環境變數覆寫，例如：CURL_MAX_TIME=120 ./net_probe.sh
# 🛠 FIXED KI-7：原版寫死 30 秒，網速慢時 100MiB 下載不完會被截斷、分數失真。
# 🔰 `${VAR:-預設}`：環境變數有設就用它，否則用預設值 60。
CURL_MAX_TIME="${CURL_MAX_TIME:-60}"


# =====================================================================
# 第 2 區：全域狀態 與 小工具函式
# =====================================================================

# ---- 2-1 全域變數（整支程式共用的「記憶體」）------------------------
# LOGS：存 4 個 log 檔名。
LOGS=()
# SEQ：每個目標已經 ping 了幾次（流水號），4 個 0 對應 4 個目標。
SEQ=(0 0 0 0)
# START_TIME：程式啟動時間（顯示用）。
START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
# 睡眠偵測：累計偵測到幾次、總共幾秒。
SLEEP_GAP_COUNT=0
SLEEP_GAP_SECONDS=0
# LAST_TICK：上一輪迴圈的 Unix 時間（秒），用來算兩輪之間隔了多久。
LAST_TICK=0
# LAST_HEARTBEAT：上一次印心跳的時間。
LAST_HEARTBEAT=0
# SLEEP_DETECTED：這一輪開始前是否偵測到睡眠（1 = 是）。主迴圈用它決定要不要丟棄本輪。
SLEEP_DETECTED=0

# ---- 2-2 is_number：判斷字串是不是數字 --------------------------------
# 🔰 `[[ "$1" =~ 正規表示式 ]]` 是 Bash 的「正規表示式比對」。
#    ^[0-9]+(\.[0-9]+)?$ 的意思：
#       ^        開頭
#       [0-9]+   一個以上的數字
#       (\.[0-9]+)?  可有可無的「小數點 + 數字」
#       $        結尾
#    ✅ 12、3.5 → 是數字     ❌ N/A、-1、1e3、空字串 → 不是
# 💡 為什麼需要？後面會把字串丟進 awk 算數。若內容是 "N/A" 或 "timeout"
#    會算出怪結果，所以先檢查。
is_number() { [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]]; }

# ---- 2-3 colorize_score：分數 → 色塊 emoji ----------------------------
# 輸入：分數；輸出：🟩 / 🟨 / 🟧 / 🟥（不是數字則輸出 N/A）。
# 🔰 為什麼用 awk 比大小？Bash 內建的 (( )) 只能比「整數」，
#    而分數有小數（例 86.4），所以交給 awk。
#    `awk -v x="$s" 'BEGIN{exit !(x>=90)}'`
#       -v x="$s"     把 Bash 變數 s 傳進 awk，在 awk 裡叫 x
#       BEGIN{...}    不讀任何檔案，直接執行這段
#       exit !(x>=90) 條件成立 → !(1)=0 → exit 0（= 成功）
#    💡 Shell 慣例：指令 exit 0 代表「真」，所以可以直接放進 if 判斷。
colorize_score() {
  local s="$1"
  if ! is_number "$s"; then echo "N/A"; return; fi
  if   awk -v x="$s" 'BEGIN{exit !(x>=90)}'; then echo "🟩"
  elif awk -v x="$s" 'BEGIN{exit !(x>=75)}'; then echo "🟨"
  elif awk -v x="$s" 'BEGIN{exit !(x>=60)}'; then echo "🟧"
  else echo "🟥"
  fi
}

# ---- 2-4 grade_text：分數 → 「色塊 + 等級文字」-----------------------
# 與上面不同：這個會附上英文等級名稱（例如「🟨 Good」）。
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

# ---- 2-5 score_ping：Ping 品質分數 ------------------------------------
# 公式：Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)
# 🔰 `local` 讓變數只在函式內有效，避免污染全域。
#    `printf "%.1f"` 輸出到小數 1 位。
#    `if(s<0)s=0` 分數不會低於 0。
# 💡 三個輸入都必須是數字，否則回傳 N/A（例如整段都 timeout，就沒有 Avg）。
score_ping() {
  local avg="$1" loss="$2" jit="$3"
  if is_number "$avg" && is_number "$loss" && is_number "$jit"; then
    awk -v a="$avg" -v l="$loss" -v j="$jit" \
      'BEGIN{s=100-(l*2 + a/2 + j*1.5); if(s<0)s=0; printf "%.1f", s}'
  else
    echo "N/A"
  fi
}

# ---- 2-6 score_web：Curl 品質分數 -------------------------------------
# 公式：Score = 100 − 7 × [ ln(1+DNS×5) + ln(1+TCP×3) + ln(1+SSL×3) + ln(1+Total×6) ]
# 🔰 awk 的 log() 就是自然對數 ln。結果夾在 0~100 之間（clamp）。
# 💡 DNS/TCP/SSL/Total 的單位都是「秒」。係數 5/3/3/6 是作者依體感調整的權重，
#    Total（總下載時間）權重最高。
#    ⚠️ 此公式不看「下載速度」，只看時間；Total 又會受 curl 的 30 秒上限影響，見 KI-7。
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


# =====================================================================
# 第 3 區：偵測環境（系統 / 網卡 / ISP）與初始化
# =====================================================================

# detect_env：把偵測結果存進全域變數
#   MAC_VER / DEFAULT_IF / IP_ADDR / IF_DESC / ISP
detect_env() {
  # --- 3-1 取得 macOS 版本 ---
  # 🛠 FIXED KI-11：原版用「Darwin 核心版號 → macOS 名稱」的對照表（case），
  #    但新版 macOS 一出來表就過期，會顯示 "macOS (Darwin 27)" 這種不友善的字。
  #    現在直接問系統：`sw_vers -productVersion` 是 macOS 內建指令，
  #    會回傳真正的版本號（例如 15.1），永遠不需要維護對照表。
  # 💡 設計原則：能「向系統查詢」的資訊，就不要自己「硬編碼對照表」。
  # 🔰 `uname -r | cut -d'.' -f1` 取 Darwin 主版號，只在 sw_vers 失敗時當備援。
  local mac_ver_num; mac_ver_num=$(sw_vers -productVersion 2>/dev/null)
  if [[ -n "$mac_ver_num" ]]; then
    MAC_VER="macOS $mac_ver_num"
  else
    MAC_VER="macOS (Darwin $(uname -r | cut -d'.' -f1))"
  fi

  # --- 3-2 找出「預設路由」走的網卡（例如 en0）---
  # 🔰 `route get default` 會輸出一堆欄位，其中含 "interface: en0"。
  #    awk '/interface:/{print $2}'：找到含 interface: 的那行，印第 2 欄（en0）。
  #    `2>/dev/null` 丟掉錯誤訊息；`/dev/null` 是 Unix 的「黑洞」。
  DEFAULT_IF=$(route get default 2>/dev/null | awk '/interface:/{print $2}')

  # 取得該網卡的 IPv4 位址。ipconfig getifaddr 是 macOS 專屬指令。
  IP_ADDR=$(ipconfig getifaddr "$DEFAULT_IF" 2>/dev/null)

  # --- 3-3 把 en0 翻成人看得懂的名稱（Wi-Fi / Ethernet）---
  # `networksetup -listallhardwareports` 會列出：
  #     Hardware Port: Wi-Fi
  #     Device: en0
  # awk 的做法：每遇到 "Hardware Port:" 行就先記住名稱，
  # 遇到 "Device: en0" 就印出剛才記住的名稱並結束。
  # 🔰 `sub(/^Hardware Port: /,"",port)` 把前綴字串刪掉，只留名稱。
  IF_DESC=$(
    networksetup -listallhardwareports 2>/dev/null | \
    awk -v dev="$DEFAULT_IF" '
      /^Hardware Port:/ {port=$0; sub(/^Hardware Port: /,"",port)}
      $0 ~ ("Device: " dev) {print port; exit}
    '
  )
  # 🔰 `-z` 判斷字串是否為空。若查不到名稱，就直接顯示網卡代號。
  [[ -z "$IF_DESC" ]] && IF_DESC="$DEFAULT_IF"

  # --- 3-4 查詢 ISP（網路供應商）---
  # ipinfo.io/org 回傳形如 "AS12345 Some ISP Name"，sed 把前面的 AS 編號刪掉。
  # 🔰 `curl -s` = silent，不顯示進度。
  # 🛠 FIXED KI-4：加上 --connect-timeout 3 / --max-time 5，網路不通最多等 5 秒；
  #    查不到時顯示 Unknown，而不是空白。
  ISP=$(curl -s --connect-timeout 3 --max-time 5 https://ipinfo.io/org 2>/dev/null | sed 's/AS[0-9]* //')
  [[ -z "$ISP" ]] && ISP="Unknown（無法查詢）"
}

# init_logs：替每個目標建立 CSV 檔並寫入表頭
# 檔名範例：ping_TWNIC_20251031_141204.log
# 🔰 `"${!NAMES[@]}"` 會展開成陣列的「索引」：0 1 2 3。
#    所以 for i in ... 的 i 是索引，不是名字。
# CSV 格式：time,seq,latency(ms)
#    時間, 流水號, 延遲（毫秒；失敗則寫 timeout）
init_logs() {
  for i in "${!NAMES[@]}"; do
    LOGS[$i]="ping_${NAMES[$i]}_$(date +%Y%m%d_%H%M%S).log"
    echo "time,seq,latency(ms)" > "${LOGS[$i]}"
  done
}

# ip_column_width：算出「最長的 IP 字串」有幾個字元
# 💡 用途：讓橫幅裡每個 IP 欄位寬度一致，右括號才會對齊。
#    例：168.95.1.1(11字) 與 101.101.101.101(15字) → 回傳 15。
# 🔰 `${#ip}` 取得字串長度；`(( len > max ))` 是整數比較。
ip_column_width() {
  local max=0
  for ip in "${TARGETS[@]}"; do
    local len=${#ip}
    (( len > max )) && max=$len
  done
  echo "$max"
}

# print_banner：啟動時的資訊橫幅
# 🔰 printf 格式字串：
#      %-12s  左對齊、至少 12 字元寬的字串
#      %-${ipw}s  寬度由變數決定（上面算出來的最長 IP 長度）
#      \n  換行
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
  echo "💤 睡眠偵測：兩輪間隔 >${SLEEP_GAP_THRESHOLD} 秒視為睡眠，該輪樣本直接丟棄（不寫入紀錄、不列入統計）"
  echo "--------------------------------------------------"
}


# =====================================================================
# 第 4 區：Ping 核心（單次 ping → 並行一輪）
# =====================================================================

# do_ping_once <索引> <流水號>：對第 N 個目標 ping 一次（含重試），結果寫入 log
#
# 流程：
#   最多嘗試 RETRY_PER_ROUND 次 → 任一次有回應就停止 → 記錄延遲
#   三次都沒回應 → 記錄 "timeout"
#
# 🛠 FIXED KI-8：流水號改由「父行程」算好再傳進來（第 2 個參數）。
#    💡 原因：這個函式是用 `&` 丟到背景執行的，背景行程是父行程的「複本」，
#       它修改全域變數 SEQ，父行程完全看不到，結果 log 裡的 seq 永遠是 1。
#       這是 Bash 並行時最常見的陷阱：子行程不能用「改全域變數」回報結果，
#       只能靠「參數傳進去」或「寫檔案 / 印出來」傳出來。
do_ping_once() {
  local idx="$1"
  local seq="$2"
  local host="${TARGETS[$idx]}"

  local attempt=1 ok=0 out=""
  while (( attempt <= RETRY_PER_ROUND )); do
    # 🔰 指令拆解：
    #    ping -n -c 1 "$host"    -n 不做 DNS 反查（更快）；-c 1 只送 1 包
    #    2>/dev/null             丟掉錯誤訊息
    #    | grep "bytes from"     只留下「有回應」的那一行
    #                            例：64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=12.3 ms
    #    || true                 grep 找不到時會回傳失敗碼；加上 true 避免被視為錯誤
    # 🛠 FIXED KI-3：加上逾時。
    #    -W <毫秒>  等待單一回應的最長時間（macOS ping 的單位是毫秒）
    #    -t <秒>    ping 整體最多存活幾秒，到了就結束（保險用）
    #    原版沒有這兩個參數，據了解 macOS ping 在無回應時會等待相當久，
    #    目標斷線時一輪可能卡 3 次 × 等待時間，拖慢「每秒一輪」的節奏。
    #    ⚠️ 這兩個旗標依 macOS 的 man page 撰寫，請在你的 Mac 上驗證：
    #       ping -n -c 1 -W 1000 -t 2 10.255.255.1   （應在約 1~2 秒內結束）
    out=$(ping -n -c 1 -W $(( PING_TIMEOUT_SEC * 1000 )) -t $(( PING_TIMEOUT_SEC + 1 )) "$host" 2>/dev/null | grep "bytes from" || true)
    if [[ -n "$out" ]]; then ok=1; break; fi
    ((attempt++))
  done

  # （流水號 seq 已由呼叫端算好，見 do_ping_cycle_parallel）
  local now; now=$(date +'%Y-%m-%d %H:%M:%S')

  if (( ok == 1 )); then
    # 從 "...time=12.3 ms" 取出 12.3：
    #   第 1 個 awk 以 "time=" 切開，取後半段 "12.3 ms"
    #   第 2 個 awk 預設以空白切開，取第 1 欄 "12.3"
    local t; t=$(echo "$out" | awk -F'time=' '{print $2}' | awk '{print $1}')
    echo "$now,$seq,$t" >> "${LOGS[$idx]}"
  else
    echo "$now,$seq,timeout" >> "${LOGS[$idx]}"
  fi
}

# do_ping_cycle_parallel：一輪「並行」ping（4 個目標同時出發）
#
# 🔰 重點語法：
#    do_ping_once "$i" &     尾巴的 & 代表「丟到背景執行」，不用等它做完
#    $!                      最近一個背景工作的 PID（行程編號）
#    wait "$pid"             等某個背景工作結束
# 💡 為什麼要並行？若 4 個依序 ping，各自耗時會累加，
#    不同目標的測量時間點就不一致；並行能讓四路在「同一秒」比較，更公平。
do_ping_cycle_parallel() {
  local pids=()
  for i in "${!NAMES[@]}"; do
    # 🛠 KI-8：流水號 +1 必須在「父行程」做（這裡），再把數字傳給背景子行程。
    #    🔰 `$(( ))` 是 Bash 的整數運算。
    SEQ[$i]=$(( SEQ[$i] + 1 ))
    do_ping_once "$i" "${SEQ[$i]}" &
    pids+=($!)
  done
  # 等全部做完才進下一步。`|| true` 避免單一失敗讓整體中斷。
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}


# =====================================================================
# 第 5 區：睡眠 / 長間隔偵測
# =====================================================================

# check_sleep_gap_and_note：偵測「兩輪之間隔太久」，並設定 SLEEP_DETECTED
# 💡 原理：正常情況每輪約 1~2 秒。若 MacBook 闔上蓋子睡眠，醒來時距離上一輪
#    可能已過了幾分鐘，這種資料不是網路問題，不應算進品質分數。
#    作法：記錄每輪開始的 Unix 時間，與上一輪比較，超過 SLEEP_GAP_THRESHOLD
#    秒就視為睡眠。
# 🔰 `date +%s` 回傳 Unix 時間戳（1970-01-01 起算的秒數）。
#
# 🛠 FIXED KI-2：原版只「計數與提示」，並沒有真正排除樣本，但報表卻寫
#    「已自動排除…不影響分數」。現在偵測到睡眠時會設 SLEEP_DETECTED=1，
#    主迴圈就會「略過」醒來後的第一輪（不 ping、不寫 log），
#    因為網卡剛喚醒時的 timeout 不代表網路品質。
check_sleep_gap_and_note() {
  local tick_now; tick_now=$(date +%s)
  SLEEP_DETECTED=0
  if (( LAST_TICK > 0 )); then
    local gap=$((tick_now - LAST_TICK))
    if (( gap > SLEEP_GAP_THRESHOLD )); then
      SLEEP_GAP_COUNT=$((SLEEP_GAP_COUNT+1))
      SLEEP_GAP_SECONDS=$((SLEEP_GAP_SECONDS+gap))
      SLEEP_DETECTED=1
    fi
  fi
  LAST_TICK=$tick_now
}


# =====================================================================
# 第 6 區：統計與心跳
# =====================================================================

# summarize_file <log 檔>：統計一個 log
# 輸出一行以逗號分隔：avg,max,min,loss_rate,jitter,total,lost
#
# 名詞解釋：
#   avg    平均延遲 (ms)          max/min  最大/最小延遲
#   loss   丟包率 (%) = 丟包數 ÷ 總數 × 100
#   jitter 抖動 (ms) = 「相鄰兩次成功樣本的延遲差」的平均絕對值
#          💡 抖動大 = 網速忽快忽慢，影響視訊會議、遊戲比平均延遲更明顯。
#
# 🔰 awk 小抄：
#    -F','        以逗號分欄；$3 就是第 3 欄（延遲）
#    NR           目前處理第幾行；NR>1 代表跳過第 1 行（表頭）
#    END{...}     全部行處理完後執行
summarize_file() {
  local file="$1"

  # 總筆數：跳過第 1 行（表頭）後的行數。
  # 🛠 FIXED KI-1：原版用 grep -E "timeout|," 計數，但表頭 "time,seq,latency(ms)"
  #    也含逗號，被多算 1 筆，導致 Count 多 1、丟包率偏低
  #    （例：4 筆含 1 次 timeout，應為 25%，原版算出 20%）。
  # 🔰 awk 'NR>1' = 只輸出第 2 行以後的內容。
  local total; total=$(awk 'NR>1' "$file" | wc -l | tr -d ' ')
  if (( total == 0 )); then
    echo "N/A,N/A,N/A,N/A,N/A,$total,0"
    return
  fi

  local avg max min lost loss_rate jitter

  # 平均：排除 timeout 行後，把第 3 欄加總 ÷ 筆數。
  # (grep -v timeout 之後表頭仍在第 1 行，所以 NR>1 剛好跳過表頭)
  avg=$(grep -v timeout "$file" | awk -F',' 'NR>1 {sum+=$3; c++} END{if(c>0) printf "%.3f", sum/c; else print "N/A"}')
  # 最大 / 最小：逐行比較，保留目前的最大（小）值。
  max=$(grep -v timeout "$file" | awk -F',' 'NR>1 {if(m==""||$3>m) m=$3} END{if(m=="") print "N/A"; else print m}')
  min=$(grep -v timeout "$file" | awk -F',' 'NR>1 {if(m==""||$3<m) m=$3} END{if(m=="") print "N/A"; else print m}')
  # 丟包數：含 "timeout" 的行數。`grep -c` = 只輸出符合行數。
  lost=$(grep -c "timeout" "$file" | tr -d ' ')
  loss_rate=$(awk -v L="$lost" -v T="$total" 'BEGIN{ if(T>0) printf "%.2f",(L/T)*100; else print "N/A"}')

  # 抖動（MAD 風格）：
  #   prev = 上一個成功樣本的延遲；cur = 目前這個
  #   d = |cur − prev|；累加後除以次數 n。
  #   timeout 的行會被跳過（$3!="timeout"），所以兩個相鄰「成功」樣本
  #   即使中間隔了 timeout 也會被拿來比較。
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

# show_minute_heartbeat：印出一行「目前累積平均分數」
# 💡 函式名稱沿用舊版的 "minute"，現在實際是每 HEARTBEAT_INTERVAL(30) 秒一次。
# 🔰 `cut -d',' -f1` 以逗號切開取第 1 欄。因此 summarize_file 的輸出順序
#    （avg,max,min,loss,jitter,total,lost）決定了這裡的欄位編號。
# 🔰 `parts+=("...")` 在陣列尾端新增元素。
#    `printf "%s / " "${parts[@]}"` 把每個元素後面接上 " / "，
#    最後 `${line% / }` 刪掉結尾多出來的那個 " / "。
#    `echo -e` 允許解析跳脫字元。
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


# =====================================================================
# 第 7 區：Curl 下載實測（IPv4 / IPv6）
# =====================================================================

# 📝 歷史說明：
#    原版這裡有一個 curl_with_progress()（自製進度條動畫，用 `script` 建立
#    偽終端機來刷新畫面），後來被整段註解停用，因為它只是視覺效果，
#    且在不同終端機行為不穩定。為了讓學習版保持乾淨，已移出此檔；
#    完整原始碼保留在 legacy/ 資料夾。

# run_curl_once <-4|-6> <網址>：正式執行一次 curl，回傳解析後的數據
# 回傳格式（用 | 分隔）：DNS|TCP|SSL|TTFB|TOTAL|SPEED|CODE|RC
#   RC = curl 本身的結束碼（0 = 正常；28 = 逾時，代表下載沒完成）
#
# 🔰 curl 參數：
#    -4 / -6      強制走 IPv4 / IPv6
#    -m N         最長 N 秒（max-time；N 來自 CURL_MAX_TIME，預設 60）
#    -o /dev/null 下載內容直接丟掉（只要量測）
#    -sS          靜默，但出錯時仍顯示錯誤
#    -w "..."     下載結束後，依格式輸出計時變數：
#       time_namelookup   DNS 解析完成的時間（秒）
#       time_connect      TCP 連線完成
#       time_appconnect   TLS(SSL) 握手完成
#       time_starttransfer 收到第一個位元組（TTFB）
#       time_total        全部完成
#       speed_download    平均下載速度（Bytes/秒）
#       http_code         HTTP 狀態碼（200 = 成功）
#    ⚠️ 這些時間是「從開始起算的累計值」，不是各階段耗時。
# 🛠 FIXED KI-7：原版寫死 -m 30，網速低於約 3.4 MB/s 時 100MiB 下載不完，
#    Total 被截在 30 秒，分數失真且使用者不知道。現在逾時改為 CURL_MAX_TIME
#    （可覆寫），並回報 curl 結束碼；結束碼 28 時報表會加註警告。
#    另外 curl 的錯誤訊息不再混進輸出（2>/dev/null），避免干擾解析。
# 🔰 `$ipver_flag` 刻意不加引號，讓空值/旗標被 Bash 正常拆詞。
run_curl_once() {
  local ipver_flag="$1"
  local url="$2"
  local out rc
  out=$(curl $ipver_flag -m "$CURL_MAX_TIME" -o /dev/null -s \
        -w "dns=%{time_namelookup} tcp=%{time_connect} ssl=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total} speed=%{speed_download} code=%{http_code}" \
        "$url" 2>/dev/null)
  rc=$?
  # 解析 "key=value key=value ..." ：
  # 以 "dns=" 切開取後半，再取第一個空白前的內容，其餘欄位同理。
  local DNS TCP SSL TTFB TOTAL SPEED CODE
  DNS=$(  echo "$out" | awk -F'dns='   '{print $2}' | awk '{print $1}')
  TCP=$(  echo "$out" | awk -F'tcp='   '{print $2}' | awk '{print $1}')
  SSL=$(  echo "$out" | awk -F'ssl='   '{print $2}' | awk '{print $1}')
  TTFB=$( echo "$out" | awk -F'ttfb='  '{print $2}' | awk '{print $1}')
  TOTAL=$(echo "$out" | awk -F'total=' '{print $2}' | awk '{print $1}')
  SPEED=$(echo "$out" | awk -F'speed=' '{print $2}' | awk '{print $1}')
  CODE=$( echo "$out" | awk -F'code='  '{print $2}')
  echo "$DNS|$TCP|$SSL|$TTFB|$TOTAL|$SPEED|$CODE|$rc"
}

# curl_probe_stack：run_curl_once 的薄包裝
# 💡 保留這一層是為了日後想加進度條、重試或多次取平均時，不必改呼叫端。
curl_probe_stack() {
  local ipver_flag="$1"
  local label="$2"
  local url="$3"

  local res; res=$(run_curl_once "$ipver_flag" "$url")
  echo "$res"
}

# detect_ipv6_available：有沒有「全球 IPv6 位址」？有輸出 1，沒有輸出 0
# 🔰 ifconfig 會列出 "inet6 fe80::..."（fe80 開頭是 link-local，只能區網用，
#    不能上網），所以用 grep -v 排除；剩下的才是可上網的 global IPv6。
#    `head -n1` 只取第 1 行。
# ⚠️ 只檢查「網卡有位址」，沒驗證 IPv6 真的連得出去，所以仍可能顯示 N/A。
detect_ipv6_available() {
  local v6; v6=$(ifconfig "$DEFAULT_IF" 2>/dev/null | awk '/inet6 /{print $2}' | grep -vi '^fe80' | head -n1 || true)
  [[ -n "$v6" ]] && echo 1 || echo 0
}


# =====================================================================
# 第 8 區：報表輸出
# =====================================================================

# print_ping_summary：Ping 統計總表 + 最佳連線
# 🔰 printf 欄寬：%-11s 左對齊 11 格；%5s 右對齊 5 格… 表頭與資料列用同一組
#    格式字串，欄位才會對齊。
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

  # 追蹤「分數最高」的目標。best_idx=-1 表示還沒有任何候選。
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

    # 「擂台賽」找最高分：第一個有效分數直接上台，之後比現任高才取代。
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
    # 💡 這行文字之後會被 print_overall 用 grep/sed「反向解析」出名稱與分數，
    #    所以修改此行格式時，必須同步修改 print_overall 的解析規則。
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

# print_curl_summary：Curl 雙協定表格與對比
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

  # ---- IPv4 ----
  # 把 "a|b|c|..." 依序用 cut 拆成 7 個變數。
  local v4; v4=$(curl_probe_stack "-4" "IPv4" "$CURL_URL")
  local d4=$(echo "$v4" | cut -d'|' -f1)
  local c4=$(echo "$v4" | cut -d'|' -f2)
  local s4=$(echo "$v4" | cut -d'|' -f3)
  local t4=$(echo "$v4" | cut -d'|' -f4)
  local T4=$(echo "$v4" | cut -d'|' -f5)
  local sp4=$(echo "$v4" | cut -d'|' -f6)
  local h4=$(echo "$v4" | cut -d'|' -f7)
  local rc4=$(echo "$v4" | cut -d'|' -f8)

  # 速度人性化：curl 給的是 Bytes/秒。
  #   ≥ 1048576 (1 MiB) → 轉成 MB/s；否則轉成 kB/s。
  # 💡 1 MiB = 1024×1024 = 1,048,576 Bytes。
  local sp4_human="N/A"
  if is_number "$sp4" && awk -v x="$sp4" 'BEGIN{exit !(x>=1048576)}'; then
    sp4_human=$(awk -v b="$sp4" 'BEGIN{printf "%.1f MB/s", b/1048576}')
  elif is_number "$sp4"; then
    sp4_human=$(awk -v b="$sp4" 'BEGIN{printf "%.0f kB/s", b/1024}')
  fi
  local sc4; sc4=$(score_web "$d4" "$c4" "$s4" "$T4")
  local gr4; gr4=$(grade_text "$sc4")
  # 🛠 FIXED KI-9：HTTP 狀態碼不是 200 就「不計分」。
  #    原版只看 DNS/TCP/SSL/Total 的時間來打分，完全不看下載是否成功。
  #    若伺服器回 403（拒絕），下載瞬間結束，Total 只有 0.1 秒，
  #    公式就給出 91 分「Excellent」——一個完全失敗的測試被評為優等。
  #    💡 觀念：評分前先確認「資料有效」，否則寧可顯示 N/A，也不要給誤導的好分數。
  if [[ "$h4" != "200" ]]; then sc4="N/A"; gr4="❌ HTTP ${h4:-N/A}"; fi

  # ---- IPv6（只有偵測到可用位址才測）----
  local d6="" c6="" s6="" t6="" T6="" sp6="" h6="" rc6="" sp6_human="N/A" sc6="N/A" gr6="N/A"
  if [[ "$ipv6_ok" == "1" ]]; then
    local v6; v6=$(curl_probe_stack "-6" "IPv6" "$CURL_URL")
    d6=$(echo "$v6" | cut -d'|' -f1)
    c6=$(echo "$v6" | cut -d'|' -f2)
    s6=$(echo "$v6" | cut -d'|' -f3)
    t6=$(echo "$v6" | cut -d'|' -f4)
    T6=$(echo "$v6" | cut -d'|' -f5)
    sp6=$(echo "$v6" | cut -d'|' -f6)
    h6=$(echo "$v6" | cut -d'|' -f7)
    rc6=$(echo "$v6" | cut -d'|' -f8)
    if is_number "$sp6" && awk -v x="$sp6" 'BEGIN{exit !(x>=1048576)}'; then
      sp6_human=$(awk -v b="$sp6" 'BEGIN{printf "%.1f MB/s", b/1048576}')
    elif is_number "$sp6"; then
      sp6_human=$(awk -v b="$sp6" 'BEGIN{printf "%.0f kB/s", b/1024}')
    fi
    sc6=$(score_web "$d6" "$c6" "$s6" "$T6")
    gr6=$(grade_text "$sc6")
    # 🛠 KI-9：同上，IPv6 的 HTTP 狀態碼不是 200 也不計分。
    if [[ "$h6" != "200" ]]; then sc6="N/A"; gr6="❌ HTTP ${h6:-N/A}"; fi
  fi

  # ---- 輸出表格 ----
  # 🔰 `$(is_number "$d4" && printf "%.3f" "$d4" || echo N/A)`
  #    「是數字就格式化成 3 位小數，否則顯示 N/A」的一行寫法（A && B || C）。
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

  # 🛠 KI-7：curl 結束碼 28 = 逾時。下載沒跑完，Total 被截斷，分數只能參考。
  if [[ "${rc4:-}" == "28" ]]; then
    echo "⚠️ IPv4 下載在 ${CURL_MAX_TIME} 秒內未完成（逾時），Total 被截斷，分數僅供參考"
  fi
  if [[ "${rc6:-}" == "28" ]]; then
    echo "⚠️ IPv6 下載在 ${CURL_MAX_TIME} 秒內未完成（逾時），Total 被截斷，分數僅供參考"
  fi

  # ---- 對比：誰較佳 ----
  # 💡 這行的格式同樣會被 print_overall 反向解析（IPv4 = 分數 / IPv6 = 分數）。
  echo "--------------------------------------------------"
  # 🛠 KI-9/KI-10：比較只在「兩邊都有有效分數」時進行（沒有 IPv6 或失敗時 sc6 = N/A）。
  if is_number "$sc4" && is_number "$sc6"; then
    if awk -v a="$sc4" -v b="$sc6" 'BEGIN{exit !(a>b)}'; then
      echo "🏁 雙協定對比（Curl）：IPv4 較佳（IPv4 = $sc4，IPv6 = $sc6）"
    elif awk -v a="$sc4" -v b="$sc6" 'BEGIN{exit !(a<b)}'; then
      echo "🏁 雙協定對比（Curl）：IPv6 較佳（IPv4 = $sc4，IPv6 = $sc6）"
    else
      echo "🏁 雙協定對比（Curl）：表現相當（IPv4 = $sc4，IPv6 = $sc6）"
    fi
  elif is_number "$sc4"; then
    # 🛠 FIXED KI-10：這幾行現在都「帶著分數」（IPv4 = xx）。
    #    原版的這句沒有分數，print_overall 用 grep 解析不到，
    #    沒有 IPv6 的使用者綜合總結會變成「Curl：N/A 較佳（Score N/A N/A）」。
    if [[ "$ipv6_ok" == "1" ]]; then
      echo "🏁 雙協定對比（Curl）：IPv6 測試失敗（HTTP ${h6:-N/A}），僅 IPv4 有成績（IPv4 = $sc4）"
    else
      echo "🏁 雙協定對比（Curl）：IPv6 未偵測到可用位址，僅 IPv4 有成績（IPv4 = $sc4）"
    fi
  elif is_number "$sc6"; then
    echo "🏁 雙協定對比（Curl）：IPv4 測試失敗（HTTP ${h4:-N/A}），僅 IPv6 有成績（IPv6 = $sc6）"
  else
    echo "🏁 雙協定對比（Curl）：IPv4 / IPv6 皆未取得有效成績（HTTP ${h4:-N/A} / ${h6:-N/A}），請檢查下載網址或網路"
  fi
}

# print_overall <ping 報表文字> <curl 報表文字>：綜合總結
# 💡 設計特色（也是脆弱點）：它不是直接拿到數值，而是把前兩份「已印出的文字」
#    再用 grep / sed 解析一次。優點是改動小；缺點是報表文字一改（例如 emoji
#    或空白），解析就會失敗。更穩健的作法是讓函式直接回傳變數（見 README Roadmap）。
# 🔰 `${var:-預設}`：var 為空或未設定時使用預設值。
#    `grep -oE '分數 [0-9.]+'`：-o 只印符合的片段、-E 啟用延伸正規表示式。
print_overall() {
  local ping_data="${1:-}"
  local curl_data="${2:-}"

  echo "--------------------------------------------------"
  echo "— — — 📈 綜合總結 — — —"

  # ---- 解析 Ping 最穩定結果 ----
  local best_ping_line
  best_ping_line=$(echo "$ping_data" | grep "🏆 最穩定連線" | head -1)

  # sed 的 s/.../\1/ 是「取括號內擷取的內容」：
  # 抓「：」後面、到空白或「(」之前的字（也就是目標名稱）。
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

  # ---- 解析 Curl 雙協定結果 ----
  local best_curl_line
  best_curl_line=$(echo "$curl_data" | grep "🏁 雙協定對比" | head -1)

  local curl_v4_score
  curl_v4_score=$(echo "$best_curl_line" | grep -oE 'IPv4 = [0-9.]+' | awk '{print $3}')
  local curl_v6_score
  curl_v6_score=$(echo "$best_curl_line" | grep -oE 'IPv6 = [0-9.]+' | awk '{print $3}')

  local best_curl_ipv="N/A"
  local best_curl_score="N/A"

  # 兩個分數都有 → 比大小；只有一個 → 用那一個。
  if [[ -n "$curl_v4_score" && -n "$curl_v6_score" ]]; then
    if awk -v v4="$curl_v4_score" -v v6="$curl_v6_score" 'BEGIN{exit !(v4>v6)}'; then
      best_curl_ipv="IPv4"
      best_curl_score="$curl_v4_score"
    elif awk -v v4="$curl_v4_score" -v v6="$curl_v6_score" 'BEGIN{exit !(v4<v6)}'; then
      best_curl_ipv="IPv6"
      best_curl_score="$curl_v6_score"
    else
      # 🛠 KI-10：分數完全相同（一位小數下並不罕見）。原版會直接當成 IPv6 較佳，
      #    且「表現相當」那行沒帶分數，總結會解析失敗。現在如實顯示並列。
      best_curl_ipv="IPv4（與 IPv6 並列）"
      best_curl_score="$curl_v4_score"
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

  # ---- 輸出綜合總結 ----
  echo "✅ Ping：${best_ping_domain:-Unknown} (${best_ping_ip:-N/A}) 最穩定（Score ${best_ping_score:-N/A} ${best_ping_grade:-N/A}）"
  # 🛠 KI-9：沒有任何有效 Curl 成績時，明說「失敗」，不要印「N/A 較佳」。
  if [[ "$best_curl_score" == "N/A" ]]; then
    echo "⚠️ Curl：沒有有效成績（下載失敗，請看上方 HTTP 狀態碼）"
  else
    echo "✅ Curl：${best_curl_ipv:-IPv4} 較佳（Score ${best_curl_score:-N/A} ${best_curl_grade:-N/A}）"
  fi
  echo "--------------------------------------------------"
  echo "🏁 測試完成於 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "--------------------------------------------------"
}


# =====================================================================
# 第 9 區：結束流程（Ctrl+C 之後做的事）
# =====================================================================

# finish：被 `trap finish INT` 觸發。依序輸出三份報表後結束。
#
# 🛠 FIXED KI-5：原版用 `$(... | tee /dev/tty)` 同時「顯示 + 存進變數」，
#    但 /dev/tty 只有在「有終端機」時才存在，用排程（cron/launchd）或把輸出
#    導向檔案時會出錯。
#    現在改成：先把報表寫進暫存檔 → cat 顯示 → 再讀進變數。
#    🔰 mktemp 建立一個唯一名稱的暫存檔；`rm -f` 用完就刪。
#    變數 ping_output / curl_output 會被交給 print_overall 去解析。
finish() {
  local tmp; tmp=$(mktemp "${TMPDIR:-/tmp}/net_probe.XXXXXX")

  local ping_output
  print_ping_summary > "$tmp"
  cat "$tmp"
  ping_output=$(cat "$tmp")

  echo ""
  echo "🔍 進行 IPv4/IPv6 雙協定 HTTP / HTTPS 100 MB 下載實測（Curl 模組）"
  local curl_output
  print_curl_summary > "$tmp"
  cat "$tmp"
  curl_output=$(cat "$tmp")
  rm -f "$tmp"

  print_overall "$ping_output" "$curl_output"

  exit 0
}


# =====================================================================
# 主程式 Main：真正「開始跑」的地方
# =====================================================================

# 1. 偵測環境 → 2. 建立 log → 3. 印橫幅
detect_env
init_logs
print_banner

# 🔰 `trap 指令 訊號`：註冊「收到某訊號時要執行的函式」。
#    INT = Interrupt，也就是你按下 Ctrl+C。
#    沒有 trap 的話，Ctrl+C 會讓程式立刻死掉，來不及出報表。
trap finish INT

# 無限迴圈：每秒做一輪，直到使用者按 Ctrl+C。
count=0
while true; do
  # (a) 檢查是否剛從睡眠醒來
  check_sleep_gap_and_note
  # (a2) 剛從睡眠醒來 → 丟棄這一輪（不 ping、不寫 log），休息後重新開始。
  #      🔰 `continue` 會跳過迴圈剩下的部分，直接進入下一圈。
  if (( SLEEP_DETECTED == 1 )); then
    sleep 1
    continue
  fi
  # (b) 四路並行 ping 一次
  do_ping_cycle_parallel
  ((count++))
  # (c) 距離上次心跳是否已 ≥ 30 秒？是的話印一行並更新時間。
  #     第一次 LAST_HEARTBEAT=0，所以第一輪結束就會印一次。
  if (( $(date +%s) - ${LAST_HEARTBEAT:-0} >= HEARTBEAT_INTERVAL )); then
   show_minute_heartbeat
    LAST_HEARTBEAT=$(date +%s)
  fi
  # (d) 休息 1 秒，形成「每秒一輪」的節奏
  #     （實際週期 = ping 耗時 + 1 秒，所以會略大於 1 秒）
  sleep 1
done
