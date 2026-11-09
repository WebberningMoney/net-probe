# 相關資源與擴充參考

整理日期：2026-11-09。以下為網路搜尋所得，**使用前請自行確認授權與維護狀態**。

## A. 同類開源專案（可學習設計）

| 專案 | 類型 | 值得學的點 |
|---|---|---|
| [SmokePing](https://selfhostyourself.com/services/smokeping) | 自架服務（Perl + RRDtool） | 長期保存延遲/抖動/丟包，用「煙霧帶」圖呈現分佈；支援 ping、DNS、HTTP 等多種探測與告警 |
| [PingerPlot](https://github.com/jamesccupps/pingerplot) | Python + tkinter 桌面程式（Windows） | MTR 式逐跳監測、**MOS 分數**、告警、即時圖表；純標準庫，無依賴 |
| [network-quality-monitor](https://github.com/edwinofsakh/network-quality-monitor) | Node.js CLI + 本機網頁 | ping/http 監測，附本機 server 與終端機折線圖 |
| [netprobe-lite](https://github.com/Axsgranted/netprobe-lite) | 家用 ISP 監測 | 量測丟包、延遲、抖動、DNS 效能 |
| [IRTT](https://github.com/sdwalsh/irtt) | 等時 UDP 往返測試 | 可量測單向延遲、上/下行丟包分離；說明 ICMP ping 可能不等於使用者感受延遲 |

## B. 原生 macOS 選單列 App（GUI 設計參考）

| 專案 | 特色 |
|---|---|
| [PingBar](https://github.com/jedisct1/pingbar) | Swift；即時 ping、sparkline、丟包、網卡資訊、DNS 管理 |
| [Pulse](https://altuzar.github.io/pulse-app/) | 持續 ping/jitter/丟包/斷線追蹤，斷線時自動 traceroute，附儀表板 |
| [Online](https://github.com/Jubblin/online) | SwiftUI、MIT 授權、只在斷線時提醒，低存在感 |
| [Yifi](https://github.com/itsnauman/yifi) | 選單列即時網路健康監測 |
| [Ping Status（App Store）](https://apps.apple.com/us/app/ping-status/id1158928913) | 選單列延遲數字、訊號條、sparkline、多目標 |

## C. 可串接的測量 API / 資料源

| 資源 | 用途 |
|---|---|
| [Cloudflare speedtest（JS 引擎）](https://www.github.com/cloudflare/speedtest) | speed.cloudflare.com 背後的量測模組：下載/上傳、閒置與**負載下延遲**、抖動、UDP 丟包（經 TURN） |
| [Cloudflare Speed Test 原理（官方部落格）](https://blog.cloudflare.com/how-does-cloudflares-speed-test-really-work/) | 解釋為何不追求「滿載最大頻寬」，而是量測實際體驗 |
| [Cloudflare AIM 文件](https://developers.cloudflare.com/speed/aim/) | 以延遲、丟包、上下載、負載延遲、抖動等指標產生**情境分數**（如串流、遊戲、視訊） |
| [cloudflare-speed-cli](https://github.com/kavehtehrani/cloudflare-speed-cli) | Rust 單檔 CLI，含 TUI，可參考其輸出設計 |
| macOS 內建 `networkQuality` 指令 | 系統自帶，可量測吞吐與回應性（Responsiveness）；*此項為作者既有知識，未於本次搜尋中驗證，請在你的 macOS 版本上以 `man networkQuality` 確認* |

## D. 長期監測 / 視覺化生態

| 資源 | 用途 |
|---|---|
| Prometheus blackbox_exporter + Grafana | 以 ICMP/HTTP/DNS 探測並存成時序資料 |
| [Grafana：Smokeping 風格儀表板 #17335](https://grafana.com/grafana/dashboards/17335) | 用 blackbox_exporter 資料畫出類 SmokePing 的延遲與丟包圖 |
| [Grafana：Prometheus Blackbox Exporter #14928](https://grafana.com/grafana/dashboards/14928) | 通用探測儀表板（含 DNS、TLS、IP 版本） |
| [Grafana：Internet connection #24364](https://grafana.com/grafana/dashboards/24364) | 結合 Speedtest 與 Blackbox，看速度、延遲、抖動、可用性 |

## E. 延伸概念

- **MOS（Mean Opinion Score）**：把延遲、抖動、丟包整合成 1–5 的通話品質分，適合取代自創公式（參考 PingerPlot）。
- **Bufferbloat / 負載下延遲**：下載時延遲飆高的現象；Cloudflare 的量測方法有針對此點。
- **ICMP 不等於真實流量**：部分設備會優先或限速 ICMP；可搭配 HTTP/TCP/UDP 探測交叉驗證（參考 IRTT、blackbox_exporter）。
