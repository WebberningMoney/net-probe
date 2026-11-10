# Changelog

格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Phase 4 網頁介面（NetSonar）
- 新增「設定」頁：網頁上就能新增／刪除／修改監測目標、測量間隔、路由器、警示門檻與通知、對外 IP 查詢、下載測試網址；儲存後立即生效，不必重啟。設定存在 `dashboard/settings.json`（不進 git，git pull 不會衝突），可一鍵恢復預設
- 全新介面：五張目標卡、延遲走勢圖（5 分鐘／1 小時／24 小時／7 天，含事件標記）、網路環境面板（SSID／對外 IP 預設遮蔽）、歷史頁與 CSV 匯出、路徑分析頁、VPN 提示
- 改名 NetSonar，新增圖示（聲納弧線）；通知標題改為「NetSonar 網路警示」
- 定時測試頁（5／15／60 分鐘、自訂 1–720、持續監測）與結束報告（含判讀、各目標統計、CSV、列印）
- Curl 下載速度測試：可選 25 MB／50 MB／100 MB／200 MB／500 MB／1 GB（大於 1 億位元組時先試單次下載，被拒絕才自動拆段合併，最久 3 分鐘，超時用已下載部分計算），結果列表含 VPN 標記
- 即時頁新增「MOS 是什麼？」說明面板

### Phase 4 後端（NetSonar）
- 修正：開 VPN 時路由器偵測抓到 VPN 通道的問題；改讀 `netstat -rn -f inet`，挑出實體介面的預設閘道，並偵測 VPN 狀態
- 新增 `netenv.py`：連線類型、本機 IP、DNS、Proxy、MTU、IPv6、VPN、Wi-Fi 頻道/訊號/速率；網路變更事件
- 新增 `traceroute.py`：路徑分析（輸入驗證、逐跳解析、持續升高 vs 單點偏高判斷、VPN 提醒）
- 新增 API：`/api/env`、`/api/events`、`/api/series`、`/api/export.csv`、`POST /api/traceroute`
- 設定 `public_ip_lookup`（預設開）可關閉對外 IP/ISP 查詢


### Added（Phase 3：路由器 ping 與告警，尚未在真實 Mac 驗證）
- 自動偵測預設閘道（`route -n get default`）並加入第 5 個目標「路由器」，每分鐘重新偵測（換 Wi-Fi 會跟著變）
- `diagnose.py`：路由器 vs 外部目標的白話判讀（偏 Wi-Fi／路由器、偏 ISP 或遠端、只有單一目標不穩、正常）
- `alerts.py`：連續逾時、近 1 分鐘丟包率、近 1 分鐘 p95 三種規則；冷卻時間；macOS 通知（osascript）
- API：`/api/diagnosis`、`/api/alerts`；`config.json` 新增 `gateway` / `alerts` / `diagnosis`
- 測試增至 25 個

### Added（Phase 2：儀表板核心，尚未在真實 Mac 驗證）
- `dashboard/`：FastAPI 後端 —— 每秒並行 ping、SQLite 儲存（原始 24 小時、每分鐘彙總 90 天）、REST API（`/api/summary`、`/api/history`、`/api/latest`）、SSE 即時串流（`/api/stream`）
- `stats.py`：p50 / p95 / p99、抖動、丟包、與 Bash 版相同的 Score，以及 MOS（E-model 簡化）
- `run_dashboard.sh`：自動建立 `.venv`、安裝固定版本套件、啟動並開啟瀏覽器；只綁 127.0.0.1:8765
- 極簡網頁（完整介面在 Phase 4）；`tests/` 共 16 個自動化測試
- 決定的技術軸（儀表板）：Python 3.13 + FastAPI + uvicorn（於 venv）、SQLite、SSE、原生 JS + Chart.js；詳見 docs/ARCHITECTURE.md

## [4.9] - 2026-11-09

### Added
- 啟動前可選擇測試時長：互動選單（5 分鐘／15 分鐘／1 小時／自訂／持續），Enter = 5 分鐘；時間或輪數到了自動出報告
- 命令列選項：`-d/--duration <分鐘>`、`-n/--rounds <輪數>`、`--forever`、`--no-curl`、`-h/--help`
- 心跳行附上測試進度（百分比與剩餘時間／輪數）
- 非互動環境（排程、導向檔案）自動使用預設 5 分鐘，不會卡在等待輸入

### Changed
- 測速網址仍可用最後一個非 `-` 開頭的參數指定（相容舊用法）
- 睡眠被排除的秒數不計入「已測時間」，電腦睡著不會讓測試提早結束
- 報表輸出期間再按一次 Ctrl+C 會乾淨中止（清除暫存檔）

> 在 Linux 沙盒以假指令（stub）測試參數、選單（pty）、進度與停止條件；真實 Mac 驗證清單見對話／PR 說明。
- 文件：README 快速開始補充存放位置（桌面）、再次執行方式、log 位置與相關 FAQ
- 規劃中：本機網頁儀表板（穩健統計 + MOS、路由器 ping、告警通知、歷史趨勢圖），見 docs/ARCHITECTURE.md（提案）

## [4.8] - 2026-11-09

### Fixed
- KI-12：預設測速網址 `bytes=104857600` 遭 Cloudflare 回 HTTP 403（對方現規定 bytes 必須 < 100,000,000）。改為 `bytes=90000000`，Mac 實測 100000000 → 403、99999999 → 200、50000000 → 200
- 報表與文件中的「100 MB」改為「約 90 MB」

### Verified on macOS 27.0.1
- 完整跑一次：Curl IPv4 / IPv6 皆 HTTP 200、系統版本顯示 27.0.1、Ping 58 筆樣本與流水號一致

## [4.7] - 2026-11-09

### Fixed（真實 Mac 實測後發現）
- KI-9：下載 HTTP 狀態碼非 200 時不再計分（原本 403 + Total 0.1 秒會被評為 91 分 Excellent）；總結改為明確顯示失敗
- KI-10：無 IPv6、單邊失敗、兩邊同分時，綜合總結不再顯示 `N/A 較佳`（比較行現在一律帶分數；同分顯示並列）
- KI-11：系統版本改用 `sw_vers -productVersion`，不再依賴會過期的 Darwin 對照表

### Verified on macOS
- KI-3 的 `ping -W/-t` 旗標有效；KI-1、KI-8 於 234 筆實測樣本中確認正確

### Docs
- README 新增「問題出在我這邊還是對方那邊」判讀說明與 HTTP 403 FAQ

## [4.6] - 2026-11-09

### Fixed
- KI-1：統計不再把 CSV 表頭計為樣本（Count、丟包率正確）
- KI-2：偵測到睡眠後，真正丟棄醒來後的第一輪樣本
- KI-3：`ping` 加入 `-W`（毫秒）與 `-t`（秒）逾時（需在 macOS 實機驗證）
- KI-4：ISP 查詢加入 `--connect-timeout 3 --max-time 5`，失敗顯示 Unknown
- KI-5：結尾報表改用暫存檔取代 `tee /dev/tty`，可在無終端機環境執行
- KI-6：`PING_TIMEOUT_SEC` 實際生效；移除未使用的 `PROGRESS_BAR_SEC`
- KI-7：Curl 逾時改為 `CURL_MAX_TIME`（預設 60 秒，可環境變數覆寫）；逾時（curl 結束碼 28）時報表加註警告
- KI-8：log 的 `seq` 欄永遠為 1（背景子行程無法修改父行程變數）→ 改由父行程計算並傳參數

### Changed
- 睡眠偵測門檻 3 秒 → 10 秒（`SLEEP_GAP_THRESHOLD`），避免目標斷線時的慢輪次被誤判
- `run_curl_once` 輸出新增第 8 欄（curl 結束碼）；curl 錯誤訊息不再混入解析內容

### Tested
- 以假的 macOS 指令（uname/ping/curl/route 等）在 Linux 做端對端測試：斷線、IPv6 逾時、時鐘跳變
- 尚未在真實 macOS 上實測

## [4.5-documented] - 2026-11-09  （僅加註解，未改邏輯）

### Added
- 完整教學註解（流程圖、`💡` 觀念、`🔰` 初學者小教室、`⚠️` 已知問題標註）
- `README.md`（非工程背景也可讀）、`LICENSE`（MIT）、`.gitignore`、`docs/RESOURCES.md`
- `legacy/` 保留原始未註解版

### Changed
- 檔名 `ping_quad_monitor_mac_color_final_v4.5.sh` → `net_probe.sh`
- 移除已停用的 `curl_with_progress()` 註解區塊（原碼保留於 `legacy/`）
- 原版數行尾端的行內註解改為區塊註解

### 行為不變
- 去除註解與空白後，程式碼與原版 v4.5 逐行一致。

## [4.5] - 2025-10-31
- 原始版本（ChatGPT × Webber Huang）。
