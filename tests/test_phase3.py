import asyncio
from fastapi.testclient import TestClient
import alerts as alerts_mod
import diagnose as dg
import gateway
from alerts import AlertManager
from app import create_app
from storage import Storage

NETSTAT_OFF = """Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            192.168.0.1        UGScg                 en0
127                127.0.0.1          UCS                   lo0
"""

# 作者 Mac 開 NordVPN 時的實測形狀：VPN 路由在前、實體路由器帶 I（限定介面）
NETSTAT_VPN = """Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            10.5.0.2           UGScg                utun6
default            192.168.0.1        UGScIg                 en0
127                127.0.0.1          UCS                    lo0
"""


def test_parse_default_routes():
    assert gateway.pick_gateways(gateway.parse_default_routes(NETSTAT_OFF))["vpn"] is None
    g = gateway.pick_gateways(gateway.parse_default_routes(NETSTAT_VPN))
    assert g["physical"]["gateway"] == "192.168.0.1" and g["physical"]["iface"] == "en0"
    assert g["vpn"]["gateway"] == "10.5.0.2" and g["vpn"]["iface"] == "utun6"
    assert gateway.pick_gateways(gateway.parse_default_routes("")) == {"physical": None, "vpn": None}


def _s(loss=0.0, p95=10.0, count=60):
    return {"count": count, "loss_pct": loss, "p95": p95}


def test_diagnose_cases():
    R = "路由器"
    assert dg.diagnose({"A": _s()}, None)["code"] == "no_router"
    assert dg.diagnose({R: _s(count=3), "A": _s()}, R)["code"] == "unknown"
    # 路由器自己就不穩 → local
    assert dg.diagnose({R: _s(p95=60), "A": _s(), "B": _s()}, R)["code"] == "local"
    # 路由器正常、多數外部異常 → upstream（使用者實測的情境：四個目標同時尖峰）
    d = dg.diagnose({R: _s(p95=5), "A": _s(p95=100), "B": _s(p95=96), "C": _s(p95=103), "D": _s(p95=105)}, R)
    assert d["code"] == "upstream" and "A" in d["detail"]
    # 只有一個目標異常 → target
    assert dg.diagnose({R: _s(), "A": _s(p95=200), "B": _s(), "C": _s(), "D": _s()}, R)["code"] == "target"
    assert dg.diagnose({R: _s(), "A": _s(), "B": _s()}, R)["code"] == "ok"


def _mgr(**kw):
    sent = []
    cfg = {"cooldown_sec": 300, **kw}
    return AlertManager(cfg, "路由器", lambda t, m: sent.append(m)), sent


def test_timeouts_alert_and_cooldown():
    m, sent = _mgr()
    win = {"A": [10.0] * 10 + [None] * 5}
    a = m.evaluate(win, 1000)
    assert len(a) == 1 and a[0]["rule"] == "timeouts" and len(sent) == 1
    assert m.evaluate(win, 1100) == []            # 冷卻中
    assert len(m.evaluate(win, 1301)) == 1        # 冷卻結束
    assert m.evaluate({"A": [10.0] * 4 + [None] * 4 + [10.0]}, 5000) == []   # 不是「結尾」連續逾時


def test_router_message_is_specific():
    m, sent = _mgr()
    m.evaluate({"路由器": [None] * 5}, 1)
    assert "Wi-Fi" in sent[0]


def test_loss_and_p95_need_enough_samples():
    m, _ = _mgr()
    assert m.evaluate({"A": [None, 10.0] * 5}, 1) == []        # 10 筆 < 20，不判斷
    big = [10.0] * 15 + [200.0] * 10 + [None] * 3 + [10.0]     # 29 筆
    rules = {a["rule"] for a in m.evaluate({"A": big}, 1)}
    assert "p95" in rules and "loss" in rules                  # 3/29 ≈ 10.3% 丟包


def test_simultaneous_alerts_are_grouped():
    m, sent = _mgr()
    down = [10.0] * 5 + [None] * 6
    a = m.evaluate({"路由器": down, "A": down, "B": down, "C": down}, 100)
    assert len(a) == 1 and a[0]["target"] == "全部" and len(sent) == 1
    assert "4 個目標" in sent[0] and "路由器" in sent[0]
    # 組內每個目標都進入冷卻
    assert m.evaluate({"路由器": down, "A": down, "B": down, "C": down}, 200) == []
    # 只有 2 個目標 → 不合併（低於 group_min_targets=3）
    m2, sent2 = _mgr()
    assert len(m2.evaluate({"A": down, "B": down, "C": [10.0] * 11}, 1)) == 2


def test_disabled():
    m, sent = _mgr(enabled=False)
    assert m.evaluate({"A": [None] * 50}, 1) == [] and sent == []


def test_applescript_quote():
    assert alerts_mod._applescript_quote('a"b\\c') == '"a\\"b\\\\c"'


CFG = {"targets": [{"name": "A", "host": "1.1.1.1"}], "interval_sec": 0.05,
       "gateway": {"enabled": True, "name": "路由器"},
       "alerts": {"cooldown_sec": 300, "consecutive_timeouts": 3, "macos_notification": False},
       "retention": {"raw_hours": 24, "minute_days": 90}}


async def runner(cmd):
    if cmd[0] == "netstat":
        return 0, NETSTAT_VPN
    if cmd[-1] == "192.168.0.1":
        return 2, ""                     # 路由器不通
    return 0, "64 bytes from x: icmp_seq=0 ttl=57 time=12.0 ms"


def test_engine_adds_router_and_alerts(tmp_path):
    sent = []
    app = create_app(CFG, Storage(str(tmp_path / "p3.db")), runner, autostart=False,
                     notifier=lambda t, m: sent.append(m))
    with TestClient(app) as c:
        eng = app.state.engine
        for _ in range(3):
            asyncio.run(eng.tick())
        names = [t["name"] for t in c.get("/api/targets").json()]
        assert names == ["A", "路由器"]
        r = c.get("/api/summary?range=5m").json()["targets"]
        assert r["路由器"]["loss_pct"] == 100.0 and r["A"]["loss_pct"] == 0
        al = c.get("/api/alerts").json()
        assert any(a["target"] == "路由器" and a["rule"] == "timeouts" for a in al)
        assert len(sent) >= 1
        d = c.get("/api/diagnosis").json()
        assert d["gateway_ip"] == "192.168.0.1" and d["code"] in ("unknown", "local")
        assert c.get("/api/diagnosis?range=zz").status_code == 400


def test_no_gateway_means_no_router_target(tmp_path):
    async def noroute(cmd):
        return (1, "") if cmd[0] == "netstat" else (0, "time=1.0 ms")
    app = create_app(CFG, Storage(str(tmp_path / "p3b.db")), noroute, autostart=False,
                     notifier=lambda t, m: None)
    with TestClient(app) as c:
        asyncio.run(app.state.engine.tick())
        assert [t["name"] for t in c.get("/api/targets").json()] == ["A"]
        assert c.get("/api/diagnosis").json()["code"] == "no_router"
