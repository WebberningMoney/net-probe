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
from fastapi.responses import FileResponse, StreamingResponse

import gateway
import probe
import stats
from alerts import AlertManager
from diagnose import diagnose
from storage import Storage

BASE = Path(__file__).resolve().parent
RANGES = {"5m": 300, "1h": 3600, "24h": 86400, "7d": 7 * 86400}


def load_config() -> dict:
    # NETPROBE_CONFIG：測試或進階使用者可指定另一份設定檔
    path = Path(os.environ.get("NETPROBE_CONFIG", BASE / "config.json"))
    return json.loads(path.read_text(encoding="utf-8"))


class Engine:
    """監測引擎：持有設定、資料庫，以及「最新一筆」結果。"""

    def __init__(self, cfg: dict, storage: Storage, runner=None, notifier=None):
        self.cfg, self.storage = cfg, storage
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

    @property
    def targets(self) -> list:
        base = list(self.cfg["targets"])
        if self.gateway_enabled and self.gateway_ip:
            base.append({"name": self.router_name, "host": self.gateway_ip})
        return base

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

    async def tick(self) -> dict:
        """做一輪：所有目標同時 ping 一次並儲存。"""
        timeout = self.cfg.get("ping_timeout_sec", 1)
        await self.refresh_gateway(time.monotonic())
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

    def diagnosis(self, range_key: str = "5m") -> dict:
        return diagnose(self.summary(range_key), self.router_name, self.cfg.get("diagnosis"))

    def summary(self, range_key: str) -> dict:
        since = int(time.time()) - RANGES[range_key]
        return {t["name"]: stats.summarize(self.storage.recent_rtts(t["name"], since))
                for t in self.targets}


def create_app(cfg: dict | None = None, storage: Storage | None = None,
               runner=None, autostart: bool = True, notifier=None) -> FastAPI:
    cfg = cfg or load_config()
    storage = storage or Storage(os.environ.get("NETPROBE_DB", str(BASE / "netprobe.db")))
    engine = Engine(cfg, storage, runner, notifier)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.loop = asyncio.get_running_loop()
        task = asyncio.create_task(engine.run_forever()) if autostart else None
        yield
        if task:
            task.cancel()
        storage.close()

    app = FastAPI(title="net-probe dashboard", lifespan=lifespan)
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

    @app.get("/")
    def index():
        return FileResponse(BASE / "web" / "index.html")

    return app


# uvicorn 啟動時會找這個名稱：`uvicorn app:app`
app = create_app() if os.environ.get("NETPROBE_NO_AUTOAPP") != "1" else None
