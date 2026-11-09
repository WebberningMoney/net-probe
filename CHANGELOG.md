# Changelog

格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### 待處理（見 README「已知問題」KI-1 ~ KI-7）
- 修正統計時表頭被計入樣本數（KI-1）
- 真正剔除睡眠時段樣本（KI-2）
- Ping / ISP 查詢加入逾時（KI-3 / KI-4）

## [4.5-documented] - 2026-11-09

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
