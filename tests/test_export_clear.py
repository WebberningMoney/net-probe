"""清除紀錄與匯出 CSV 的測試。"""
import asyncio
import time

from fastapi.testclient import TestClient

import export
from app import create_app
from storage import Storage
from test_phase4 import CFG, _runner


def test_csv_helpers_escape_and_bom():
    assert export.safe("=1+1") == "'=1+1" and export.safe("@x") == "'@x" and export.safe("正常") == "正常"
    assert export.line(["a,b", 'q"q', 3]) == '"a,b","q""q",3\n'
    out = "".join(export.samples_stream([("A", [(0, 1.5), (1, None)])]))
    assert out.startswith("﻿時間,目標,延遲(ms)\n") and out.count("\n") == 3 and "逾時" in out
    tr = export.trace_table({"hops": [{"hop": 1, "ip": None, "avg": None, "max": None, "loss_pct": 100}]})
    assert "（不回應）" in tr
    rp = export.reports_table([{"label": "-關藍牙", "started": 1, "finished": 2, "context": {"band": "5 GHz", "signal_dbm": -63, "vpn": False},
                                "router": {"avg": 3.5, "p95": 4.6, "jitter": 0.5, "loss_pct": 0}, "external": {"avg": 18}, "spikes": {}}])
    assert "'-關藍牙" in rp and ",-63," in rp and ",關,3.5,4.6,0.5,0,18," in rp      # 文字防呆，數字（含負數）不受影響
    cu = export.curl_table([{"ts": 1, "ok": True, "bytes": 25_000_000, "mbps": 93.1, "partial": True}, {"ts": 2, "ok": False, "error": "HTTP 403"}])
    assert "25.0,93.1" in cu and "時間到" in cu and "失敗" in cu and "HTTP 403" in cu


def _app(tmp_path):
    return create_app({**CFG, "interval_sec": 1}, Storage(str(tmp_path / "c.db")), _runner, autostart=False)


def test_clear_each_kind_and_csv_endpoints(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        eng = app.state.engine

        async def fill():
            await eng.tick()
            eng.start_test(1, "要被清掉的")
            await eng.tick()
            eng.finish_test(int(time.time()) + 1)
        asyncio.run(fill())
        eng.events.append({"ts": 5, "text": "VPN 開啟"})
        eng.alerts.history.appendleft({"ts": 6, "rule": "loss", "target": "A", "severity": "warning", "message": "A 丟包"})
        eng.curl_results.appendleft({"ts": 7, "ok": True, "bytes": 1e6, "mbps": 10.0})
        eng.trace_jobs["j1"] = {"id": "j1", "running": False, "hops": [{"hop": 1, "ip": "192.168.0.1", "avg": 2.0, "max": 3.0, "loss_pct": 0}]}
        eng.trace_jobs["j2"] = {"id": "j2", "running": True, "hops": []}

        # 匯出
        assert ",A," in c.get("/api/export.csv?range=5m").text                        # 預設＝全部目標
        assert c.get("/api/export.csv?target=nope").status_code == 404
        al = c.get("/api/alerts.csv").text
        assert "警示,A,A 丟包" in al and "網路環境變化,,VPN 開啟" in al
        assert "要被清掉的" in c.get("/api/reports.csv").text
        assert "10.0" in c.get("/api/curl.csv").text
        assert "192.168.0.1" in c.get("/api/traceroute.csv?id=j1").text and c.get("/api/traceroute.csv?id=x").status_code == 404

        # 清除：防呆
        assert c.post("/api/clear", json={"what": "all"}).status_code == 400                                   # 沒確認
        assert c.post("/api/clear", json={"what": ["bogus"], "confirm": True}).status_code == 400
        assert c.post("/api/clear", json={"what": "all", "confirm": True}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert len(c.get("/api/reports").json()) == 1                                                          # 上面都沒有真的清掉

        # 一項一項清，確認只影響該項
        assert c.post("/api/clear", json={"what": ["curl"], "confirm": True}).json()["cleared"] == {"curl": 1}
        assert c.get("/api/curl").json()["results"] == [] and len(c.get("/api/reports").json()) == 1
        assert c.post("/api/clear", json={"what": ["trace"], "confirm": True}).json()["cleared"] == {"trace": 1}
        assert list(eng.trace_jobs) == ["j2"]                                                                  # 進行中的分析不動
        c.post("/api/clear", json={"what": ["alerts"], "confirm": True})
        assert c.get("/api/alerts").json() == [] and c.get("/api/events").json() == []
        c.post("/api/clear", json={"what": ["reports"], "confirm": True})
        assert c.get("/api/reports").json() == [] and c.get("/api/test").json()["state"] == "idle"
        assert c.get("/api/summary?range=5m").json()["targets"]["A"]["count"] > 0                              # 量測資料還在
        r = c.post("/api/clear", json={"what": ["samples"], "confirm": True}).json()
        assert r["cleared"]["samples"] > 0
        assert c.get("/api/summary?range=5m").json()["targets"]["A"]["count"] == 0
        assert all(len(w) == 0 for w in eng.windows.values())
        assert c.get("/api/series_all?range=24h").status_code == 200 and c.get("/api/advice").status_code == 200  # 清空後各頁仍正常

        # 清完之後量測會繼續累積
        asyncio.run(eng.tick())
        assert c.get("/api/summary?range=5m").json()["targets"]["A"]["count"] > 0


def test_clear_all_and_blocked_while_test_running(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        eng = app.state.engine
        asyncio.run(eng.tick())
        eng.start_test(5, "進行中")
        r = c.post("/api/clear", json={"what": "all", "confirm": True})
        assert r.status_code == 409 and "定時測試進行中" in r.json()["detail"]
        assert c.post("/api/clear", json={"what": ["alerts", "curl"], "confirm": True}).status_code == 200   # 不影響測試的可以清
        eng.finish_test(int(time.time()) + 1)
        r = c.post("/api/clear", json={"what": "all", "confirm": True}).json()
        assert set(r["cleared"]) == {"samples", "alerts", "reports", "curl", "trace"}
        assert c.get("/api/reports").json() == []


def test_settings_export_roundtrip_and_world_map(tmp_path):
    import json
    app = create_app({**CFG, "interval_sec": 1, "ping_timeout_sec": 1}, Storage(str(tmp_path / "s.db")), _runner, autostart=False, settings_file=tmp_path / "s.json")
    with TestClient(app) as c:
        r = c.get("/api/settings/export")
        assert "attachment; filename=netsonar-settings-" in r.headers["content-disposition"]
        doc = json.loads(r.text)
        assert doc["app"] == "NetSonar" and doc["type"] == "settings"
        s = doc["settings"]
        s["targets"] = s["targets"] + [{"name": "新目標", "host": "9.9.9.9", "p95_ms": 250}]
        assert c.put("/api/settings", json=s).status_code == 200                      # 匯出的內容可以原樣（或修改後）匯入
        got = c.get("/api/settings").json()
        assert got["settings"]["targets"][-1] == {"name": "新目標", "host": "9.9.9.9", "p95_ms": 250}
        assert got["curl_default_url"].startswith("https://speed.cloudflare.com/")
        assert c.put("/api/settings", json={"targets": "壞掉的檔案"}).status_code == 400
        w = c.get("/world.json").json()
        assert w["path"].startswith("M") and len(w["path"]) > 50_000
