"""app.py —— 儀表板後端入口（FastAPI）。

做三件事：
  1. 背景迴圈：每秒同時 ping 所有目標 → 存進 SQLite → 推送給網頁
  2. REST API：查詢統計摘要、歷史彙總
  3. SSE（Server-Sent Events）：把每秒的最新結果「推」給瀏覽器
只綁 127.0.0.1（本機），不對外開放。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

import gateway
import netenv
import traceroute as trace_mod
import settings as settings_mod
import speedtest
import probe
import stats
from alerts import AlertManager
from diagnose import diagnose
from storage import Storage

BASE = Path(__file__).resolve().parent
RANGES = {"5m": 300, "1h": 3600, "24h": 86400, "7d": 7 * 86400}


def settings_path() -> Path:
    return Path(os.environ.get("NETPROBE_SETTINGS", BASE / "settings.json"))


def load_base_config() -> dict:
    # NETPROBE_CONFIG：測試或進階使用者可指定另一份設定檔
    path = Path(os.environ.get("NETPROBE_CONFIG", BASE / "config.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    """預設值（config.json）＋ 使用者在網頁上改的設定（settings.json）。"""
    return settings_mod.merge(load_base_config(), settings_mod.load_overrides(settings_path()))


class Engine:
    """監測引擎：持有設定、資料庫，以及「最新一筆」結果。"""

    def __init__(self, cfg: dict, storage: Storage, runner=None, notifier=None):
        self.cfg, self.storage = cfg, storage
        self.base_cfg = dict(cfg)         # 「恢復預設」用
        self._notifier = notifier
        self.runner = runner or probe._real_runner
        self.latest: dict = {"ts": 0, "results": {}}
        self.subscribers: set = set()      # 每個 SSE 連線一個 queue
        self._last_maint = 0
        # 路由器（預設閘道）：每分鐘重新偵測一次，換 Wi-Fi 時會自動跟著變
        gw = cfg.get("gateway", {})
        self.gateway_enabled = gw.get("enabled", False)
        self.router_name = gw.get("name", "路由器") if self.gateway_enabled else None
        self.gateway_ip = None
        self._last_gw_check = -10**9
        self.windows: dict = {}            # 每個目標最近 60 筆結果（給告警用，免查資料庫）
        self.alerts = AlertManager(cfg.get("alerts"), self.router_name, notifier)
        self.loop = None                   # 伺服器的 event loop（關閉時要用）
        # 網路環境（連線類型、VPN、Wi-Fi…）與「環境變更事件」
        self.env: dict = {}
        self.wifi: dict | None = None
        self.public: dict | None = None    # 對外 IP/ISP（預設遮蔽顯示，由網頁決定）
        self.events: deque = deque(maxlen=200)
        self._fp = None
        self._last_env_check = -10**9
        self._last_wifi_check = -10**9
        self._wifi_busy = False
        self.public_lookup = cfg.get("public_ip_lookup", True)
        self.test: dict = {"state": "idle"}     # 定時測試狀態
        self.curl_results: deque = deque(maxlen=20)
        self.curl_busy = False
        self.trace_lines = None            # 測試時可注入假的 traceroute 輸出
        self.trace_jobs: dict = {}         # job_id → 路徑分析進度

    @property
    def targets(self) -> list:
        base = list(self.cfg["targets"])
        if self.gateway_enabled and self.gateway_ip:
            base.append({"name": self.router_name, "host": self.gateway_ip})
        return base

    def apply_config(self, cfg: dict) -> None:
        """設定改了就立即生效（不必重啟）：目標、間隔、路由器、警示、對外 IP 查詢。"""
        self.cfg = cfg
        gw = cfg.get("gateway", {})
        self.gateway_enabled = gw.get("enabled", False)
        self.router_name = gw.get("name", "路由器") if self.gateway_enabled else None
        if not self.gateway_enabled:
            self.gateway_ip = None
        self._last_gw_check = -10**9
        self.public_lookup = cfg.get("public_ip_lookup", True)
        history = self.alerts.history
        self.alerts = AlertManager(cfg.get("alerts"), self.router_name, self._notifier)
        self.alerts.history = history
        keep = {t["name"] for t in self.targets} | {t["name"] for t in cfg["targets"]}
        for n in list(self.windows):
            if n not in keep:
                del self.windows[n]

    def stop_streams(self) -> None:
        """通知所有 SSE 連線「該結束了」。

        💡 為什麼需要？瀏覽器開著儀表板 = 一條永遠不會自己結束的串流連線；
           uvicorn 收到 Ctrl+C 會等所有連線關閉才退出 → 看起來像「按了沒反應」。
           所以關閉前先主動把串流收掉（放入 None 當作結束訊號）。
        """
        def _push():
            for q in list(self.subscribers):
                q.put_nowait(None)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(_push)   # 🔰 從別的執行緒/信號處理器安全地排進 event loop

    async def refresh_gateway(self, now: float) -> None:
        if not self.gateway_enabled or now - self._last_gw_check < 60:
            return
        self._last_gw_check = now
        self.gateway_ip = await gateway.get_gateway(self.runner)

    async def refresh_env(self, now: float) -> None:
        """每 15 秒更新一次網路環境；Wi-Fi 資訊較慢（約 7 秒），丟到背景每 60 秒更新。"""
        if now - self._last_env_check >= 15:
            self._last_env_check = now
            try:
                self.env = await netenv.collect_env(self.runner)
            except Exception as e:
                print("env error:", e)
                return
            if self.env.get("gateway") and self.gateway_enabled:
                self.gateway_ip = self.env["gateway"]      # 與路由器目標保持一致
            self._check_change()
        if now - self._last_wifi_check >= 60 and not self._wifi_busy:
            self._last_wifi_check = now
            self._wifi_busy = True
            asyncio.create_task(self._refresh_wifi())

    async def _refresh_wifi(self) -> None:
        try:
            self.wifi = await asyncio.wait_for(netenv.collect_wifi(self.runner), 15)
        except Exception:
            self.wifi = None
        finally:
            self._wifi_busy = False
        self._check_change()

    def _check_change(self) -> None:
        if not self.env:
            return
        fp = netenv.fingerprint(self.env, self.wifi)
        for text in netenv.describe_changes(self._fp, fp):
            self.events.append({"ts": int(time.time()), "text": text})
        if self._fp is not None and (self._fp["gateway"], self._fp["vpn"]) != (fp["gateway"], fp["vpn"]):
            self.public = None                             # 網路換了，舊的對外 IP 作廢
        self._fp = fp
        if self.public is None and self.public_lookup and self.env.get("interface"):
            self.public = {}                               # 佔位，避免重複查詢
            if self.loop:
                asyncio.create_task(self._lookup_public())

    async def _lookup_public(self) -> None:
        self.public = await asyncio.to_thread(netenv.lookup_public) or {}

    async def tick(self) -> dict:
        """做一輪：所有目標同時 ping 一次並儲存。"""
        timeout = self.cfg.get("ping_timeout_sec", 1)
        await self.refresh_gateway(time.monotonic())
        await self.refresh_env(time.monotonic())
        names = [t["name"] for t in self.targets]
        rtts = await asyncio.gather(*[
            probe.ping_once(t["host"], timeout, self.runner) for t in self.targets])
        ts = int(time.time())
        results = dict(zip(names, rtts))
        self.storage.add_samples(ts, results)
        for n, v in results.items():
            self.windows.setdefault(n, deque(maxlen=60)).append(v)
        new_alerts = self.alerts.evaluate({n: list(w) for n, w in self.windows.items()}, ts)
        self.latest = {"ts": ts, "results": results, "alerts": new_alerts}
        t = self.test
        if t["state"] == "running" and t["ends_at"] and ts >= t["ends_at"]:
            self.finish_test(ts)
        for q in list(self.subscribers):
            if q.qsize() < 5:              # 瀏覽器太慢就丟棄舊訊息，避免記憶體堆積
                q.put_nowait(self.latest)
        if ts - self._last_maint >= 60:    # 每分鐘：彙總 → 再清理
            self._last_maint = ts
            ret = self.cfg.get("retention", {})
            await asyncio.to_thread(self.storage.rollup, ts)
            await asyncio.to_thread(self.storage.purge, ts, ret.get("raw_hours", 24),
                                    ret.get("minute_days", 90))
        return self.latest

    async def run_forever(self) -> None:
        interval = self.cfg.get("interval_sec", 1.0)
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except Exception as e:         # 單輪失敗不要讓整個監測停掉
                print("tick error:", e)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))

    # ---- 定時測試：記下起訖時間，結束時用這段期間的原始資料產生報告 ----
    def start_test(self, minutes: int | None) -> dict:
        now = int(time.time())
        self.test = {"state": "running", "started": now, "minutes": minutes,
                     "ends_at": now + minutes * 60 if minutes else None,
                     "vpn": bool(self.env.get("vpn", {}).get("active")), "report": None}
        return self.test

    def finish_test(self, now: int | None = None) -> dict:
        t, now = self.test, now or int(time.time())
        if t["state"] != "running":
            return t
        t.update(state="done", finished=now)
        t["report"] = self.report(t["started"], now)
        return t

    def report(self, since: int, until: int) -> dict:
        targets = {t["name"]: stats.summarize([r for ts, r in self.storage.raw_rows(t["name"], since) if ts <= until])
                   for t in self.targets}
        d = diagnose(targets, self.router_name, self.cfg.get("diagnosis"))
        return {"since": since, "until": until, "seconds": until - since, "targets": targets,
                "diagnosis": d, "alerts": [a for a in self.alerts.history if since <= a["ts"] <= until],
                "events": [e for e in self.events if since <= e["ts"] <= until],
                "curl": [c for c in self.curl_results if since <= c.get("ts", 0) <= until]}

    async def run_curl_test(self, mb: int = 25) -> dict:
        cc = self.cfg.get("curl_test", {})
        self.curl_busy = True
        try:
            res = await speedtest.run_curl(self.runner, mb * 1_000_000,
                                           cc.get("url", speedtest.DEFAULT_URL))
        finally:
            self.curl_busy = False
        res["ts"] = int(time.time())
        res["vpn"] = bool(self.env.get("vpn", {}).get("active"))
        self.curl_results.appendleft(res)
        return res

    def diagnosis(self, range_key: str = "5m") -> dict:
        return diagnose(self.summary(range_key), self.router_name, self.cfg.get("diagnosis"))

    def summary(self, range_key: str) -> dict:
        since = int(time.time()) - RANGES[range_key]
        return {t["name"]: stats.summarize(self.storage.recent_rtts(t["name"], since))
                for t in self.targets}


async def _run_trace(engine: Engine, jid: str, host: str) -> None:
    """背景執行 traceroute，邊跑邊把每一跳放進 job（網頁輪詢即可看到進度）。"""
    job = engine.trace_jobs[jid]
    lines = engine.trace_lines or trace_mod.iter_lines
    try:
        async for line in lines(trace_mod.build_cmd(host)):
            hop = trace_mod.parse_hop_line(line)
            if hop:
                job["hops"].append(hop)
    except Exception as e:
        job["error"] = str(e)
    job["analysis"] = trace_mod.analyze_hops(job["hops"], bool(engine.env.get("vpn", {}).get("active")))
    job["running"] = False


def create_app(cfg: dict | None = None, storage: Storage | None = None,
               runner=None, autostart: bool = True, notifier=None, settings_file: Path | None = None) -> FastAPI:
    from_disk = cfg is None
    cfg = cfg or load_config()
    sfile = Path(settings_file) if settings_file else settings_path()
    storage = storage or Storage(os.environ.get("NETPROBE_DB", str(BASE / "netprobe.db")))
    engine = Engine(cfg, storage, runner, notifier)
    if from_disk:
        engine.base_cfg = load_base_config()      # 「恢復預設」要回到 config.json，而不是目前（含自訂）的設定

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.loop = asyncio.get_running_loop()
        task = asyncio.create_task(engine.run_forever()) if autostart else None
        yield
        if task:
            task.cancel()
        storage.close()

    app = FastAPI(title="NetSonar", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/health")
    def health():
        return {"ok": True, "targets": len(engine.targets)}

    @app.get("/api/targets")
    def targets():
        return engine.targets

    @app.get("/api/latest")
    def latest():
        return engine.latest

    @app.get("/api/summary")
    def summary(range: str = "5m"):
        if range not in RANGES:
            raise HTTPException(400, f"range 必須是 {list(RANGES)} 其中之一")
        return {"range": range, "targets": engine.summary(range)}

    @app.get("/api/diagnosis")
    def diagnosis(range: str = "5m"):
        if range not in RANGES:
            raise HTTPException(400, f"range 必須是 {list(RANGES)} 其中之一")
        return {"range": range, "router": engine.router_name,
                "gateway_ip": engine.gateway_ip, **engine.diagnosis(range)}

    @app.get("/api/alerts")
    def alerts():
        return list(engine.alerts.history)

    @app.get("/api/history")
    def history(target: str, range: str = "24h"):
        if range not in RANGES:
            raise HTTPException(400, f"range 必須是 {list(RANGES)} 其中之一")
        if target not in [t["name"] for t in engine.targets]:
            raise HTTPException(404, "找不到這個目標")
        since = int(time.time()) - RANGES[range]
        return {"target": target, "range": range,
                "points": engine.storage.minute_series(target, since)}

    def _settings_view():
        return {"settings": {k: engine.cfg.get(k) for k in settings_mod.EDITABLE if k in engine.cfg},
                "defaults": {k: engine.base_cfg.get(k) for k in settings_mod.EDITABLE if k in engine.base_cfg},
                "customized": sfile.exists()}

    @app.get("/api/settings")
    def settings_get():
        return _settings_view()

    @app.put("/api/settings")
    def settings_put(body: dict):
        try:
            clean = settings_mod.validate(body)
        except settings_mod.SettingsError as e:
            raise HTTPException(400, str(e))
        settings_mod.save_overrides(sfile, clean)
        engine.apply_config({**engine.base_cfg, **clean})
        return _settings_view()

    @app.post("/api/settings/reset")
    def settings_reset():
        settings_mod.reset(sfile)
        engine.apply_config(dict(engine.base_cfg))
        return _settings_view()

    @app.get("/api/env")
    def env():
        """網路環境。SSID／對外 IP 預設由網頁遮蔽，這裡回傳原值（只綁本機）。"""
        return {"env": engine.env, "wifi": engine.wifi, "public": engine.public or None}

    @app.get("/api/events")
    def events():
        return list(engine.events)

    @app.get("/api/series")
    def series(target: str, range: str = "1h"):
        """圖表資料：≤1h 用原始資料（分桶），24h/7d 用每分鐘彙總（loss/avg/p95）。"""
        if range not in RANGES:
            raise HTTPException(400, f"range 必須是 {list(RANGES)} 其中之一")
        if target not in [t["name"] for t in engine.targets]:
            raise HTTPException(404, "找不到這個目標")
        since = int(time.time()) - RANGES[range]
        if range in ("5m", "1h"):
            bucket = 1 if range == "5m" else 10
            return {"target": target, "range": range, "bucket_sec": bucket,
                    "points": engine.storage.raw_series(target, since, bucket)}
        return {"target": target, "range": range, "bucket_sec": 60 if range == "24h" else 300,
                "points": engine.storage.minute_series(target, since)}

    @app.get("/api/export.csv")
    def export_csv(target: str, range: str = "24h", since: int | None = None, until: int | None = None):
        if range not in RANGES:
            raise HTTPException(400, f"range 必須是 {list(RANGES)} 其中之一")
        if since is None:
            since = int(time.time()) - RANGES[range]
        until = until or 10**12
        rows = ["ts,target,rtt_ms"] + [f"{t},{target.replace(',', ' ')},{'' if r is None else r}"
                                       for t, r in engine.storage.raw_rows(target, since) if t <= until]
        return Response("\n".join(rows) + "\n", media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=netsonar.csv"})

    @app.get("/api/test")
    def test_get():
        t = dict(engine.test)
        t["now"] = int(time.time())
        return t

    @app.post("/api/test/start")
    def test_start(body: dict):
        m = body.get("minutes")                 # None = 持續監測（手動停止）
        if m is not None:
            if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= 720:
                raise HTTPException(400, "minutes 必須是 1–720 的整數")
        if engine.test["state"] == "running":
            raise HTTPException(409, "已有測試正在進行")
        return engine.start_test(m)

    @app.post("/api/test/stop")
    def test_stop():
        if engine.test["state"] != "running":
            raise HTTPException(409, "目前沒有進行中的測試")
        return engine.finish_test()

    @app.post("/api/curl")
    async def curl_start(body: dict | None = None):
        mb = (body or {}).get("mb", 25)
        if mb not in speedtest.SIZES_MB:
            raise HTTPException(400, f"mb 必須是 {list(speedtest.SIZES_MB)} 其中之一")
        if engine.curl_busy:
            raise HTTPException(409, "下載測試進行中")
        res = await engine.run_curl_test(mb)
        res["mb"] = mb
        return res

    @app.get("/api/curl")
    def curl_list():
        return {"busy": engine.curl_busy, "results": list(engine.curl_results)}

    @app.post("/api/traceroute")
    async def traceroute_start(body: dict):
        host = str(body.get("target", "")).strip()
        if not trace_mod.valid_target(host):
            raise HTTPException(400, "目標格式不正確（只接受網址或 IP）")
        if any(j["running"] for j in engine.trace_jobs.values()):
            raise HTTPException(409, "已有路徑分析正在進行")
        jid = str(int(time.time() * 1000))
        engine.trace_jobs[jid] = {"id": jid, "target": host, "running": True, "hops": [], "analysis": None}
        if len(engine.trace_jobs) > 5:
            engine.trace_jobs.pop(next(iter(engine.trace_jobs)))
        asyncio.create_task(_run_trace(engine, jid, host))
        return {"id": jid}

    @app.get("/api/traceroute/{jid}")
    def traceroute_get(jid: str):
        if jid not in engine.trace_jobs:
            raise HTTPException(404, "找不到這個分析")
        return engine.trace_jobs[jid]

    @app.get("/api/stream")
    async def stream():
        """SSE：保持連線，每秒收到一筆最新結果。格式：'data: {json}\\n\\n'。"""
        q: asyncio.Queue = asyncio.Queue()
        engine.subscribers.add(q)

        async def gen():
            try:
                yield f"data: {json.dumps(engine.latest)}\n\n"
                while True:
                    item = await q.get()
                    if item is None:       # 伺服器要關閉了
                        return
                    yield f"data: {json.dumps(item)}\n\n"
            finally:
                engine.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/icon.svg")
    def icon():
        return FileResponse(BASE / "web" / "icon.svg", media_type="image/svg+xml")

    @app.get("/")
    def index():
        return FileResponse(BASE / "web" / "index.html")

    return app


# uvicorn 啟動時會找這個名稱：`uvicorn app:app`
app = create_app() if os.environ.get("NETPROBE_NO_AUTOAPP") != "1" else None
