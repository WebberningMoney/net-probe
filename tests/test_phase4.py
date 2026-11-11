import asyncio
import netenv
import traceroute as tr

HW = """Hardware Port: Wi-Fi
Device: en0
Ethernet Address: aa:bb

Hardware Port: USB 10/100/1000 LAN
Device: en7
Ethernet Address: cc:dd
"""

NWI = """Network information

IPv4 network interface information
   utun6 : flags      : 0x5 (IPv4,DNS)
           address    : 10.5.0.2
   en0 : flags      : 0x5 (IPv4,IPv6,DNS)
           address    : 192.168.0.23
 
IPv6 network interface information
   en0 : flags      : 0x5 (IPv4,IPv6,DNS)
           address    : 240e:1::5
"""

DNS = """resolver #1
  nameserver[0] : 103.86.96.100
  nameserver[1] : 103.86.99.100
resolver #2
  nameserver[0] : 103.86.96.100
"""

PROXY = """<dictionary> {
  HTTPEnable : 0
  SOCKSEnable : 1
}"""

WIFI = """Wi-Fi:
      Current Network Information:
        <redacted>:
          PHY Mode: 802.11ac
          Channel: 36 (5GHz, 80MHz)
          Security: WPA2 Personal
          Signal / Noise: -68 dBm / -95 dBm
          Transmit Rate: 585
          MCS Index: 7
      Other Local Wi-Fi Networks:
        foo:
          PHY Mode: 802.11n
"""

TRACE = """traceroute to 1.1.1.1 (1.1.1.1), 20 hops max, 40 byte packets
 1  192.168.0.1  2.8 ms  2.1 ms  3.0 ms
 2  *  *  *
 3  10.0.0.1  9.0 ms  120.0 ms  10.0 ms
"""


def test_parsers():
    assert netenv.parse_hardware_ports(HW) == {"en0": "Wi-Fi", "en7": "USB 10/100/1000 LAN"}
    n = netenv.parse_nwi(NWI)
    assert n["ipv4"] == {"utun6": "10.5.0.2", "en0": "192.168.0.23"} and n["ipv6"]["en0"] == "240e:1::5"
    assert netenv.parse_dns(DNS) == ["103.86.96.100", "103.86.99.100"]
    assert netenv.parse_proxy(PROXY) == ["SOCKS"]
    assert netenv.parse_mtu("en0: flags=8863 mtu 1500") == 1500


def test_wifi():
    w = netenv.parse_wifi(WIFI)
    assert w["ssid"] is None and w["ssid_hidden_by_os"]
    assert (w["channel"], w["band"], w["width"]) == (36, "5 GHz", "80 MHz")
    assert (w["signal_dbm"], w["noise_dbm"], w["snr_db"], w["tx_rate_mbps"]) == (-68, -95, 27, 585)
    assert w["signal_label"] == "偏弱" and w["phy"] == "802.11ac"
    assert netenv.parse_wifi("nothing") is None


def test_collect_env_under_vpn():
    from test_phase3 import NETSTAT_VPN

    async def run(cmd):
        return 0, {"netstat": NETSTAT_VPN, "scutil": {"--nwi": NWI, "--dns": DNS, "--proxy": PROXY}.get(cmd[1], ""),
                   "networksetup": HW, "ifconfig": "mtu 1500"}[cmd[0]]
    e = asyncio.run(netenv.collect_env(run))
    assert e["gateway"] == "192.168.0.1" and e["interface_type"] == "Wi-Fi" and e["local_ip"] == "192.168.0.23"
    assert e["vpn"]["active"] and e["vpn"]["interface"] == "utun6" and e["mtu"] == 1500


def test_changes():
    base = {"interface": "en0", "type": "Wi-Fi", "ip": "1", "gateway": "g", "vpn": False, "channel": 36}
    assert netenv.describe_changes(None, base) == []
    assert netenv.describe_changes(base, dict(base, vpn=True)) == ["VPN 已連線"]
    assert netenv.describe_changes(base, dict(base, channel=1)) == ["Wi-Fi 頻道 36 → 1"]


def test_traceroute_parse_and_validate():
    hops = [h for h in map(tr.parse_hop_line, TRACE.splitlines()) if h]
    assert [h["hop"] for h in hops] == [1, 2, 3]
    assert hops[1]["loss_pct"] == 100.0 and hops[1]["avg"] is None
    assert hops[2]["max"] == 120.0 and hops[2]["ip"] == "10.0.0.1"
    assert tr.valid_target("1.1.1.1") and tr.valid_target("example.com")
    assert not tr.valid_target("-w5") and not tr.valid_target("a b") and not tr.valid_target("x;ls")


def test_analyze():
    mk = lambda i, a: {"hop": i, "rtts": [a] if a else [], "avg": a}
    rising = tr.analyze_hops([mk(1, 2), mk(2, 10), mk(3, 90), mk(4, 95), mk(5, 100)])
    assert rising["status"][3] == "high" and "第 3 站" in rising["title"]
    spike = tr.analyze_hops([mk(1, 2), mk(2, 80), mk(3, 10), mk(4, 12)])
    assert spike["status"][2] == "high" and "不急著回應" in spike["detail"]
    assert "VPN" in tr.analyze_hops([mk(1, 2)], vpn_active=True)["detail"]


# ---------------------------------------------------------------- API 整合
import time
from fastapi.testclient import TestClient
from app import create_app
from storage import Storage
from test_phase3 import NETSTAT_VPN

CFG = {"targets": [{"name": "A", "host": "1.1.1.1"}], "interval_sec": 0.05, "public_ip_lookup": False,
       "gateway": {"enabled": True, "name": "路由器"},
       "alerts": {"macos_notification": False}, "retention": {"raw_hours": 24, "minute_days": 90}}


async def _runner(cmd):
    if cmd[0] == "netstat":
        return 0, NETSTAT_VPN
    if cmd[0] == "scutil":
        return 0, {"--nwi": NWI, "--dns": DNS, "--proxy": PROXY}.get(cmd[1], "")
    if cmd[0] == "networksetup":
        return 0, HW
    if cmd[0] == "ifconfig":
        return 0, "mtu 1500"
    if cmd[0] == "system_profiler":
        return 0, WIFI
    return 0, "64 bytes from x: icmp_seq=0 ttl=57 time=12.0 ms"


def test_api_env_series_export_trace(tmp_path):
    app = create_app(CFG, Storage(str(tmp_path / "p4.db")), _runner, autostart=False)

    async def fake_lines(cmd):
        for l in TRACE.splitlines():
            yield l
    app.state.engine.trace_lines = fake_lines
    with TestClient(app) as c:
        async def go():
            await app.state.engine.tick()
            await asyncio.sleep(0.1)          # 讓背景 Wi-Fi 查詢完成
        asyncio.run(go())
        d = c.get("/api/env").json()
        assert d["env"]["vpn"]["active"] and d["env"]["gateway"] == "192.168.0.1"
        assert d["wifi"] is None or d["wifi"]["channel"] == 36
        s = c.get("/api/series?target=A&range=5m").json()
        assert s["bucket_sec"] == 1 and s["points"] and s["points"][0]["loss_pct"] == 0
        assert c.get("/api/series?target=A&range=24h").status_code == 200
        assert c.get("/api/series?target=zz").status_code == 404
        csv = c.get("/api/export.csv?target=A&range=5m")
        assert csv.text.startswith("\ufeff時間,目標,延遲(ms)") and ",A,12.0" in csv.text
        assert "attachment; filename=netsonar-measurements-" in csv.headers["content-disposition"]
        assert c.post("/api/traceroute", json={"target": "-w5"}).status_code == 400
        jid = c.post("/api/traceroute", json={"target": "1.1.1.1"}).json()["id"]
        for _ in range(20):
            j = c.get(f"/api/traceroute/{jid}").json()
            if not j["running"]:
                break
            time.sleep(0.05)
        assert len(j["hops"]) == 3 and j["analysis"]["title"] and "VPN" in j["analysis"]["detail"]
        assert [e for e in c.get("/api/events").json() if not e.get("minor")] == []


def test_speedtest_parse():
    import speedtest as sp
    r = sp.parse_result("200 3125000.0 0.03 0.12 8.0 25000000")
    assert r["ok"] and r["mbps"] == 25.0 and r["connect_ms"] == 30 and r["ttfb_ms"] == 120
    assert sp.parse_result("garbage") is None
    assert "bytes=90000000" in sp.build_cmd(999_999_999)[-1] and "bytes=1000000" in sp.build_cmd(5)[-1]
    assert sp.plan_chunks(25_000_000) == [25_000_000] and sp.plan_chunks(100_000_000) == [50_000_000] * 2
    assert len(sp.plan_chunks(1_000_000_000)) == 12 and all(c < 100_000_000 for c in sp.plan_chunks(1_000_000_000))


def test_run_curl_chunks_and_deadline():
    import speedtest as sp
    calls = []

    async def run(cmd):
        calls.append(cmd[-1])
        n = int(cmd[-1].split("bytes=")[1])
        if n >= 100_000_000:                                    # 模擬 Cloudflare 拒絕大檔
            return 0, "403 0 0.03 0.12 0.2 0"
        return 0, f"200 12500000.0 0.03 0.12 {n / 12.5e6} {n}"          # 速度 100 Mbps，大小照要求回傳
    r = asyncio.run(sp.run_curl(run, 200_000_000))
    assert len(calls) == 4 and r["ok"] and r["chunks"] == 3 and abs(r["mbps"] - 100) < 1.5 and not r["partial"]
    t = [0.0]

    def clock():
        t[0] += 100.0                                         # 每次呼叫前進 100 秒 → 時間很快用完
        return t[0]
    # 伺服器若接受單次大檔，就只發一個請求
    async def lenient(cmd):
        n = int(cmd[-1].split("bytes=")[1])
        return 0, f"200 12500000.0 0.03 0.12 {n / 12.5e6} {n}"
    one = asyncio.run(sp.run_curl(lenient, 500_000_000))
    assert one["ok"] and one["chunks"] == 1 and one["bytes"] == 500_000_000
    calls.clear()
    r = asyncio.run(sp.run_curl(run, 500_000_000, max_total_sec=180, clock=clock))
    assert r["ok"] and r["partial"] and len(calls) < 6

    async def bad(cmd):
        return 28, ""
    assert not asyncio.run(sp.run_curl(bad, 50_000_000))["ok"]


def test_timed_test_and_curl(tmp_path):
    async def run(cmd):
        if cmd[0] == "curl":
            return 0, "200 3125000.0 0.03 0.12 8.0 25000000"
        return await _runner(cmd)
    app = create_app(CFG, Storage(str(tmp_path / "p5.db")), run, autostart=False)
    with TestClient(app) as c:
        assert c.post("/api/test/start", json={"minutes": 0}).status_code == 400
        assert c.post("/api/test/stop").status_code == 409
        assert c.post("/api/test/start", json={"minutes": 5}).json()["state"] == "running"
        assert c.post("/api/test/start", json={"minutes": 5}).status_code == 409
        eng = app.state.engine

        async def go():
            for _ in range(3):
                await eng.tick()
        asyncio.run(go())
        assert c.post("/api/curl", json={"mb": 7}).status_code == 400
        cr = c.post("/api/curl").json()
        assert cr["ok"] and cr["mbps"] == 25.0 and cr["mb"] == 25
        assert c.post("/api/curl", json={"mb": 100}).json()["ok"]
        done = c.post("/api/test/stop").json()
        assert done["state"] == "done" and done["report"]["targets"]["A"]["count"] >= 3
        assert done["report"]["curl"] and done["report"]["diagnosis"]["title"]
        assert c.get("/api/test").json()["state"] == "done"
        assert c.post("/api/test/start", json={"minutes": None}).json()["ends_at"] is None


# ---------------------------------------------------------------- 各目標獨立量測 / 引擎健康度
def test_independent_loops_dead_target_does_not_block_others(tmp_path):
    from app import Engine
    cfg = {**CFG, "targets": [{"name": "OK1", "host": "1.1.1.1"}, {"name": "DEAD", "host": "9.9.9.9"},
                              {"name": "OK2", "host": "8.8.8.8"}], "interval_sec": 0.1, "gateway": {"enabled": False}}
    counts = {}

    async def run(cmd):
        h = cmd[-1]
        counts[h] = counts.get(h, 0) + 1
        if h == "9.9.9.9":
            await asyncio.sleep(0.5)                     # 一直逾時、而且很慢
            return 1, ""
        return 0, "64 bytes from x: icmp_seq=0 ttl=57 time=12.0 ms"

    async def go():
        eng = Engine(cfg, Storage(str(tmp_path / "i.db")), run)
        task = asyncio.create_task(eng.run_forever())
        await asyncio.sleep(1.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return eng
    eng = asyncio.run(go())
    assert counts["1.1.1.1"] >= 7 and counts["8.8.8.8"] >= 7 and counts["9.9.9.9"] <= 3   # 正常目標不被拖慢
    assert not eng._tasks                                   # 結束時所有量測迴圈都收掉了
    assert eng.storage.recent_rtts("OK1", 0) and eng.latest["results"]["DEAD"] is None
    h = eng.engine_health()
    assert h["pings"] > 10 and h["overhead_ms"]["p50"] is not None and h["ok"]


def test_staggered_start_and_target_removal(tmp_path):
    from app import Engine
    starts = []

    async def run(cmd):
        starts.append((cmd[-1], asyncio.get_running_loop().time()))
        return 0, "64 bytes from x: icmp_seq=0 ttl=57 time=1.0 ms"
    cfg = {**CFG, "targets": [{"name": f"T{i}", "host": f"10.0.0.{i}"} for i in range(4)],
           "interval_sec": 1.0, "gateway": {"enabled": False}}

    async def go():
        eng = Engine(cfg, Storage(str(tmp_path / "s.db")), run)
        t = asyncio.create_task(eng.run_forever())
        await asyncio.sleep(0.9)
        first = dict(starts)
        eng.apply_config({**cfg, "targets": cfg["targets"][:2]})
        await asyncio.sleep(1.3)
        t.cancel()
        return eng, first
    eng, first = asyncio.run(go())
    t0 = min(first.values())
    offs = sorted(round(v - t0, 1) for v in first.values())
    assert offs == [0.0, 0.2, 0.5, 0.8] or (offs[-1] - offs[0]) >= 0.6      # 錯開起跑
    assert set(eng._tasks) <= {"T0", "T1"} or not eng._tasks


def test_unreachable_target_is_marked_and_excluded(tmp_path):
    from app import Engine
    cfg = {**CFG, "targets": [{"name": "OK", "host": "1.1.1.1"}, {"name": "DEADY", "host": "9.9.9.9"}],
           "gateway": {"enabled": False}, "alerts": {"macos_notification": False, "enabled": True}}
    state = {"dead_ok": False}

    async def run(cmd):
        if cmd[-1] == "9.9.9.9" and not state["dead_ok"]:
            return 2, ""
        return 0, "64 bytes from x: icmp_seq=0 ttl=57 time=10.0 ms"

    async def go():
        eng = Engine(cfg, Storage(str(tmp_path / "d.db")), run)
        for _ in range(31):
            await eng.tick()
        assert eng.dead == {"DEADY"}
        s = eng.summary("5m")
        assert s["DEADY"]["unreachable"] and not s["OK"]["unreachable"]
        assert any("一直沒有回應" in e["text"] for e in eng.events)
        assert "DEADY" not in " ".join(a["message"] for a in eng.alerts.history)   # 不對它發警示
        state["dead_ok"] = True
        await eng.tick()
        assert not eng.dead and any("恢復回應" in e["text"] for e in eng.events)
    asyncio.run(go())


def test_total_outage_is_not_marked_unreachable(tmp_path):
    from app import Engine
    cfg = {**CFG, "targets": [{"name": "A", "host": "1.1.1.1"}, {"name": "B", "host": "9.9.9.9"}], "gateway": {"enabled": False}}

    async def run(cmd):
        return 2, ""

    async def go():
        eng = Engine(cfg, Storage(str(tmp_path / "o.db")), run)
        for _ in range(35):
            await eng.tick()
        assert eng.dead == set()
    asyncio.run(go())


def test_wifi_refresh_interval_and_manual(tmp_path):
    from app import Engine
    calls = {"sp": 0}

    async def run(cmd):
        if cmd[0] == "system_profiler":
            calls["sp"] += 1
            return 0, WIFI
        return await _runner(cmd)

    async def go(cfg_extra, manual=False):
        calls["sp"] = 0
        eng = Engine({**CFG, **cfg_extra}, Storage(str(tmp_path / f"w{len(cfg_extra)}{manual}.db")), run)
        for k in range(4):
            await eng.refresh_env(1000.0 + k * 20)        # 模擬 60 秒內（0/20/40/60 秒）
            await asyncio.sleep(0.05)
        if manual:
            assert eng.request_wifi_refresh() and not eng.request_wifi_refresh()   # 進行中不重複
            await asyncio.sleep(0.05)
        return eng
    eng = asyncio.run(go({"wifi_refresh_sec": 300}))
    assert calls["sp"] == 1                                # 5 分鐘內只查第一次
    asyncio.run(go({"wifi_refresh_sec": 0}))
    assert calls["sp"] == 0                                # 關閉＝完全不自動查
    asyncio.run(go({"wifi_refresh_sec": 0}, manual=True))
    assert calls["sp"] == 1                                # 手動才查一次
    assert any(e.get("minor") for e in eng.events)


def test_reports_saved_listed_renamed_deleted_and_jitter(tmp_path):
    import random
    rnd = random.Random(3)
    t = {"n": 0}

    async def run(cmd):
        if cmd[0] == "ping":
            t["n"] += 1
            spike = (t["n"] // 3) % 5 == 0
            return 0, f"64 bytes from x: icmp_seq=0 ttl=57 time={90.0 if spike else 5.0 + rnd.random()} ms"
        return await _runner(cmd)
    app = create_app({**CFG, "interval_sec": 1}, Storage(str(tmp_path / "r.db")), run, autostart=False)
    with TestClient(app) as c:
        eng = app.state.engine

        async def go():
            await eng.tick()
            now = int(time.time())
            eng.start_test(5, "有線")
            for i in range(70):                                # 偽造 70 秒資料
                eng.storage.add_rows([(now + i, "A", 5.0 if i % 4 else 90.0), (now + i, "路由器", 5.0 if i % 4 else 90.0)])
            await eng.tick()
            eng.finish_test(now + 71)
        asyncio.run(go())
        lst = c.get("/api/reports").json()
        assert len(lst) == 1 and lst[0]["label"] == "有線" and lst[0]["context"]["vpn"] is True
        rid = lst[0]["id"]
        full = c.get(f"/api/reports/{rid}").json()
        assert full["data"]["jitter"]["ok"] and full["data"]["jitter"]["per_min"] > 5
        assert c.patch(f"/api/reports/{rid}", json={"label": "<x>"}).status_code == 400
        assert c.patch(f"/api/reports/{rid}", json={"label": "2.4GHz"}).status_code == 200
        assert c.get("/api/reports").json()[0]["label"] == "2.4GHz"
        assert c.get("/api/jitter?range=5m").status_code == 200
        assert c.delete(f"/api/reports/{rid}").status_code == 200 and c.get("/api/reports").json() == []
        assert c.get("/api/reports/999").status_code == 404


def test_per_target_alert_threshold_and_mute():
    from alerts import AlertManager
    import settings as S
    body = {"targets": [{"name": "A", "host": "1.1.1.1", "p95_ms": 300}, {"name": "B", "host": "8.8.8.8", "mute": True},
                        {"name": "C", "host": "9.9.9.9"}]}
    ts = S.validate(body)["targets"]
    assert ts[0]["p95_ms"] == 300 and ts[1]["mute"] is True and "p95_ms" not in ts[2]
    for bad in (5, 99999, "abc"):
        try:
            S.validate({"targets": [{"name": "A", "host": "1.1.1.1", "p95_ms": bad}]})
            assert False
        except S.SettingsError:
            pass
    am = AlertManager({"macos_notification": False}, None, lambda *a: None, {"A": {"p95_ms": 300}, "B": {"mute": True}})
    slow = [10.0] * 30 + [200.0] * 30
    fired = am.evaluate({"A": slow, "B": slow, "C": slow}, 1000)
    text = " ".join(str(x) for x in fired)
    assert "C" in text and "B 近" not in text and "A 近" not in text


def test_wifi_refresh_from_threadpool_does_not_crash(tmp_path):
    """回歸：網頁請求在執行緒池裡呼叫「更新 Wi-Fi」，不能因為沒有 event loop 而炸掉。"""
    app = create_app({**CFG, "interval_sec": 1}, Storage(str(tmp_path / "w.db")), _runner, autostart=False)
    with TestClient(app) as c:
        r = c.post("/api/wifi/refresh")
        assert r.status_code == 200 and r.json()["started"] is True
        assert c.get("/api/advice").status_code == 200
        assert "dns_names" in c.get("/api/env").json()


def test_about_and_quit_guarded(tmp_path):
    app = create_app({**CFG}, Storage(str(tmp_path / "q.db")), _runner, autostart=False, settings_file=tmp_path / "s.json")
    called = []
    app.state.quit = lambda: called.append(1)
    with TestClient(app) as c:
        ab = c.get("/api/about").json()
        assert ab["mode"] == "terminal" and ab["db_path"].endswith("q.db") and ab["settings_path"].endswith("s.json")
        assert c.post("/api/quit", json={}).status_code == 400                       # 沒有 confirm
        assert c.post("/api/quit", json={"confirm": True}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert not called
        assert c.post("/api/quit", json={"confirm": True}, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
        time.sleep(0.8)
        assert called == [1]
