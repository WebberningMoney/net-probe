# Changelog

格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]
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
