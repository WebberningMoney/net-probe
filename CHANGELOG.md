# Changelog

格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]
- 規劃中：MOS 分數、負載下延遲、告警通知、歷史趨勢圖、GUI

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
