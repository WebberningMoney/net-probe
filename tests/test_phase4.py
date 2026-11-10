import asyncio
import netenv
import traceroute as tr
import gateway

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
    assert rising["status"][3] == "high" and "第 3 跳" in rising["title"]
    spike = tr.analyze_hops([mk(1, 2), mk(2, 80), mk(3, 10), mk(4, 12)])
    assert spike["status"][2] == "high" and "不優先" in spike["detail"]
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
        assert csv.text.startswith("ts,target,rtt_ms") and "A,12.0" in csv.text
        assert c.post("/api/traceroute", json={"target": "-w5"}).status_code == 400
        jid = c.post("/api/traceroute", json={"target": "1.1.1.1"}).json()["id"]
        for _ in range(20):
            j = c.get(f"/api/traceroute/{jid}").json()
            if not j["running"]:
                break
            time.sleep(0.05)
        assert len(j["hops"]) == 3 and j["analysis"]["title"] and "VPN" in j["analysis"]["detail"]
        assert c.get("/api/events").json() == []
