# NetSonar 儀表板是怎麼組成的

> 給想了解、修改這個程式的人。不寫程式的使用者看 [README](../README.md) 就夠了。

---

## 1. 一張圖看懂

```text
┌──────────────────────────── 你的 Mac ────────────────────────────┐
│                                                                  │
│  背景服務（開機自動啟動）或 run_dashboard.sh（終端機啟動）       │
│     │                                                            │
│     └─ serve.py 啟動網頁伺服器 → app.py（大腦）                  │
│           ├─ 每個目標各自每秒 ping 一次（probe.py）              │
│           ├─ 結果存進資料檔（storage.py，SQLite）                │
│           ├─ 算統計、判斷要不要通知（stats.py、alerts.py）       │
│           ├─ 把數字翻成白話建議（diagnose / jitter / advice.py） │
│           └─ 在 http://127.0.0.1:8765 提供網頁與資料             │
│                              ▲                                   │
│  瀏覽器（Safari / Chrome）───┘  打開網址就看到儀表板             │
└──────────────────────────────────────────────────────────────────┘
```

- **只在你的電腦上執行**：沒有雲端、沒有帳號。網頁只開放給這台電腦（`127.0.0.1`）。
- **對外連線**：只有 ping 目標、查對外 IP（ipinfo.io）、查 DNS 服務商（rdap.org），以及你按按鈕時的下載測速與路徑分析。詳見 README 的「隱私」一節。

---

## 2. 用了哪些技術？為什麼？

| 部分 | 用什麼 | 為什麼選它 |
|---|---|---|
| 程式語言 | **Python 3.10 以上** | 語法好讀，適合當教材 |
| 網頁伺服器 | **FastAPI + uvicorn** | 寫法簡潔，支援「即時推送」；版本固定在 `requirements.txt` |
| 量測 | 呼叫 Mac 內建的 `ping` 指令 | 不需要管理員權限 |
| 即時更新 | **SSE**（伺服器主動推送） | 比 WebSocket 簡單，瀏覽器內建支援 |
| 資料庫 | **SQLite** | 就是一個檔案，不用另外安裝，Python 內建 |
| 網頁 | **一個 HTML 檔 + 原生 JavaScript** | 不需要任何建置工具，打開就能改 |
| 圖表 | **自己畫的 SVG** | 不依賴外部套件，離線也能用 |
| 通知 | macOS 內建的 `osascript` | 不用安裝任何東西 |
| 開機自動啟動 | macOS 的 **LaunchAgent** | 系統內建的背景服務機制 |

**為什麼另外寫一個 Python 版，不繼續用 Bash？** Bash 很適合「量一次、印報告」，但要做即時網頁、資料庫、圖表、通知會變得很難讀也很難測試。Bash 版 `net_probe.sh` 仍然保留。

**套件裝在哪裡？** 裝在專案專用的「虛擬環境」（`.venv` 資料夾）裡，跟電腦上其他 Python 程式完全分開，不會互相干擾。

---

## 3. 量測是怎麼進行的

1. 每個目標都有**自己的量測迴圈**，每隔設定的秒數 ping 一次。各目標的起跑時間錯開，不會在同一瞬間一起送出。
   這樣做的好處：某個目標一直沒回應時，不會拖慢其他目標。
2. 結果先放進一個暫存區，**每秒統一處理一次**：寫進資料庫、檢查警示、推送給網頁。
3. 每分鐘把原始資料平均成一筆，並刪掉過期的資料。
4. **家裡的路由器**會被自動找出來一起量（每分鐘重新找一次，換 Wi-Fi 也會跟著變）。開 VPN 時也能找到真正的路由器，而不是 VPN 通道（見 `gateway.py`）。
5. 一直完全沒回應、但其他目標正常的目標，會被標為「無回應」，暫停對它的警示和判斷。
6. **程式健康度**：記錄每次 ping 額外花了多少時間、程式有沒有延遲，用來分辨「網路不穩」和「電腦太忙」。

---

## 4. 把數字翻成白話

| 檔案 | 做什麼 |
|---|---|
| `stats.py` | 算平均、中位數、「慢的時候」(p95)、抖動、丟包、分數、MOS |
| `diagnose.py` | 比較「路由器」和「外部目標」，判斷問題在你家裡、家以外，還是單一目標 |
| `jitter.py` | 分析延遲尖峰：多久來一次、有沒有規律、是不是和路由器同時發生，並提出可以試試的對照實驗 |
| `advice.py` | 把上面所有結果整理成即時頁最上方的「整體網路建議」（分段、燈號、建議） |
| `dns_info.py` | 把 DNS 伺服器的位址翻成「是哪家公司的」 |
| `netenv.py` | 讀取網路環境：連線方式、IP、DNS、VPN、Wi-Fi 訊號等 |

這些判斷都只是**提示**，用的是業界常見的粗略標準，不能當作鑑定。

---

## 5. 資料存在哪裡、存多久

| 內容 | 保存多久 |
|---|---|
| 每秒的原始量測 | 24 小時 |
| 每分鐘平均 | 90 天 |
| 定時測試報告 | 直到你在網頁上刪除 |

| 啟動方式 | 資料檔與設定的位置 |
|---|---|
| 雙擊「安裝.command」（背景服務） | `~/Library/Application Support/NetSonar/data/` |
| `run_dashboard.sh`（終端機） | `dashboard/` 資料夾 |

設定分兩層：`config.json` 是程式附帶的預設值；你在網頁「設定」頁改的部分存在 `settings.json`，啟動時蓋在預設值上面。所以更新程式不會蓋掉你的設定。

---

## 6. 背景服務（安裝.command）怎麼運作

`安裝.command` 會呼叫 `scripts/netsonar_service.sh install`，做這幾件事：

1. 找到 3.10 以上的 Python。
2. 把 `dashboard/` 複製到 `~/Library/Application Support/NetSonar/app/`。
   為什麼要複製？macOS 的隱私保護不讓背景程式讀取「桌面」「文件」等資料夾。
3. 在那裡建立虛擬環境並安裝套件。
4. 寫一個 LaunchAgent 設定檔到 `~/Library/LaunchAgents/com.netsonar.dashboard.plist`，告訴 macOS：「登入時啟動它，當掉了就自動重開」。
5. 啟動服務、確認網頁有回應，然後打開瀏覽器。

執行紀錄寫在 `~/Library/Logs/NetSonar.log`。

---

## 7. 網頁拿資料的網址（API）

網頁透過這些網址向程式拿資料。你也可以直接在瀏覽器打開來看（回傳的是 JSON 格式的資料）。

| 網址 | 內容 |
|---|---|
| `/api/advice` | 整體網路建議 |
| `/api/summary?range=5m` | 各目標的統計（範圍可選 5m、1h、24h、7d） |
| `/api/diagnosis` | 問題出在哪一段 |
| `/api/jitter` | 延遲尖峰分析 |
| `/api/env` | 網路環境、Wi-Fi、DNS 服務商 |
| `/api/series_all?range=5m` | 走勢圖資料 |
| `/api/alerts`、`/api/events` | 最近的警示、網路環境變化 |
| `/api/test`、`/api/test/start`、`/api/test/stop` | 定時測試 |
| `/api/reports` | 已保存的測試報告（可改名、刪除） |
| `/api/curl` | 下載測速 |
| `/api/traceroute` | 路徑分析 |
| `/api/settings` | 讀取／儲存設定 |
| `/api/health` | 程式健康度 |
| `/api/export.csv` | 下載原始資料 |
| `/api/stream` | 每秒推送最新結果（SSE） |

---

## 8. 測試

`tests/` 裡的自動化測試用「假的 ping 結果」驗證計算和判斷邏輯，所以在任何電腦上都能跑，不需要真的連網：

```bash
cd tests
../dashboard/.venv/bin/python -m pip install pytest httpx   # 第一次
../dashboard/.venv/bin/python -m pytest -q
```

真正的 ping、Wi-Fi 資訊、系統通知、背景服務，只能在 Mac 上實際操作驗證。

---

## 9. 檔案一覽

```text
dashboard/
├── serve.py        啟動網頁伺服器
├── app.py          大腦：量測迴圈、資料整理、所有 /api 網址
├── probe.py        呼叫 ping
├── gateway.py      找出家裡的路由器（開 VPN 也不會找錯）
├── netenv.py       讀取網路環境
├── dns_info.py     DNS 服務商查詢
├── stats.py        統計與分數
├── diagnose.py     問題在哪一段
├── jitter.py       延遲尖峰分析
├── advice.py       整體網路建議
├── alerts.py       警示與 macOS 通知
├── storage.py      資料庫
├── settings.py     設定頁的檢查與儲存
├── speedtest.py    下載測速
├── traceroute.py   路徑分析
├── config.json     預設設定
├── requirements.txt 需要的套件與版本
└── web/            網頁（index.html、icon.svg）
scripts/netsonar_service.sh   安裝／移除背景服務
```
