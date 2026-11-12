"""路徑分析每一站的「大約位置＋服務商」。"""
import asyncio

from fastapi.testclient import TestClient

import export
import geo
from app import create_app
from storage import Storage
from test_phase4 import CFG, _runner


def test_parse_and_local_kinds():
    g = geo.parse({"org": "AS15169 Google LLC", "city": "Taipei", "country": "TW", "loc": "25.0478,121.5319", "hostname": "dns.google"})
    assert g == {"kind": "public", "org": "Google LLC", "hostname": "dns.google", "city": "Taipei", "country": "TW",
                 "place": "Taipei，台灣", "lat": 25.048, "lon": 121.532}
    bad = geo.parse({"loc": "abc", "country": "zz"})
    assert bad["lat"] is None and bad["place"] == "ZZ" and bad["org"] is None
    assert geo.parse({"loc": "999,999"})["lat"] is None
    assert geo.local_kind("192.168.0.1") == "private" and geo.local_kind("10.1.2.3") == "private"
    assert geo.local_kind("100.72.0.1") == "cgnat" and geo.local_kind("8.8.8.8") is None and geo.local_kind("x") is None
    assert "內部網路" in geo.describe_local("private")["place"]


def _trace_app(tmp_path, lookup_on, fake):
    async def lines(cmd):
        for ln in [" 1  192.168.0.1  2.0 ms  2.1 ms  2.2 ms", " 2  100.72.0.1  5.0 ms  5.1 ms  5.2 ms",
                   " 3  * * *", " 4  8.8.8.8  20.0 ms  21.0 ms  22.0 ms"]:
            yield ln
    app = create_app({**CFG, "public_ip_lookup": lookup_on}, Storage(str(tmp_path / "g.db")), _runner, autostart=False)
    app.state.engine.trace_lines = lines
    app.state.engine.geo_lookup = fake
    return app


def _run(c):
    jid = c.post("/api/traceroute", json={"target": "8.8.8.8"}).json()["id"]
    for _ in range(50):
        j = c.get(f"/api/traceroute/{jid}").json()
        if not j["running"]:
            return j
        asyncio.run(asyncio.sleep(0.05))
    raise AssertionError("路徑分析沒有結束")


def test_hops_get_location_only_public_ips_are_looked_up(tmp_path):
    asked = []

    def fake(ip):
        asked.append(ip)
        return geo.parse({"org": "AS15169 Google LLC", "city": "Mountain View", "country": "US", "loc": "37.4,-122.1"})
    with TestClient(_trace_app(tmp_path, True, fake)) as c:
        j = _run(c)
        assert asked == ["8.8.8.8"]                                    # 內部位址不會送出去查
        h = {x["hop"]: x for x in j["hops"]}
        assert h[1]["geo"]["kind"] == "private" and h[2]["geo"]["kind"] == "cgnat" and "geo" not in h[3]
        assert h[4]["geo"]["place"] == "Mountain View，美國" and h[4]["geo"]["org"] == "Google LLC" and j["geo_enabled"] is True
        csv = c.get(f"/api/traceroute.csv?id={j['id']}").text
        assert "大約位置,服務商" in csv and "Mountain View，美國,Google LLC" in csv
        _run(c)
        assert asked == ["8.8.8.8"]                                    # 第二次用記住的結果，不重複查


def test_no_lookup_when_disabled_and_failure_is_harmless(tmp_path):
    asked = []
    with TestClient(_trace_app(tmp_path, False, lambda ip: asked.append(ip))) as c:
        j = _run(c)
        assert asked == [] and j["geo_enabled"] is False and "geo" not in j["hops"][3]
        assert j["hops"][0]["geo"]["kind"] == "private"                # 內部位址的標示不需要上網

    def boom(ip):
        raise OSError("沒有網路")
    with TestClient(_trace_app(tmp_path, True, boom)) as c:
        j = _run(c)
        assert j["analysis"] and "geo" not in j["hops"][3]             # 查不到位置，路徑分析照樣完成
    assert "（不回應）" in export.trace_table({"hops": [{"hop": 3, "ip": None}]})
