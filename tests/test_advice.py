import advice
import dns_info


def S(avg, p95, jit, loss=0, n=60):
    return {"count": n, "avg": avg, "p95": p95, "jitter": jit, "loss_pct": loss}


def build(**kw):
    base = dict(summaries={"路由器": S(3, 4, 0.5), "A": S(18, 20, 2), "Far": S(70, 73, 3)},
                diagnosis={"code": "ok", "title": "目前正常", "detail": "x"},
                env={"interface_type": "Wi-Fi", "dns": ["192.168.0.1", "8.8.8.8"], "vpn": {}},
                wifi={"signal_dbm": -63, "signal_label": "尚可", "snr_db": 33, "band": "5 GHz", "width": "40 MHz", "tx_rate_mbps": 229},
                jitter={"ok": True, "per_min": 0, "period_s": None, "findings": []},
                dns_names={"192.168.0.1": {"name": "路由器"}, "8.8.8.8": {"name": "Google Public DNS"}},
                router_name="路由器", dead=set())
    base.update(kw)
    return advice.build(**base)


def test_all_good_and_far_target_explained():
    r = build()
    assert r["overall"]["level"] == "ok" and r["overall"]["title"] == "整體狀況良好"
    ext = next(s for s in r["sections"] if s["key"] == "external")
    assert "Far" in " ".join(ext["tips"]) and ext["level"] == "ok"


def test_weak_wifi_and_bad_router_and_jitter():
    r = build(wifi={"signal_dbm": -75, "signal_label": "很弱", "snr_db": 12, "band": "2.4 GHz", "width": "20 MHz", "tx_rate_mbps": 50},
              summaries={"路由器": S(10, 70, 15, 2), "A": S(30, 100, 20)},
              diagnosis={"code": "local", "title": "問題偏向你這一端", "detail": "d"},
              jitter={"ok": True, "per_min": 8, "period_s": 11, "findings": ["f1"]})
    lv = {s["key"]: s["level"] for s in r["sections"]}
    assert lv["wifi"] == "bad" and lv["router"] == "bad" and lv["jitter"] == "bad" and r["overall"]["level"] == "bad"
    assert next(s for s in r["sections"] if s["key"] == "jitter")["tips"] == ["f1"]


def test_wired_vpn_and_missing_data():
    r = build(env={"interface_type": "有線網路", "dns": [], "vpn": {"active": True, "interface": "utun4"}}, wifi=None, jitter=None)
    keys = [s["key"] for s in r["sections"]]
    assert "vpn" in keys and "dns" not in keys
    assert next(s for s in r["sections"] if s["key"] == "wifi")["level"] == "ok"
    assert next(s for s in r["sections"] if s["key"] == "jitter")["level"] == "info"


def test_labels_and_dns_classify():
    assert advice.snr_label(33) == "良好" and advice.snr_label(10) == "很差" and advice.noise_label(-96) == "很乾淨"
    assert dns_info.classify("8.8.8.8")["name"].startswith("Google")
    assert dns_info.classify("192.168.0.1")["source"] == "private"
    assert dns_info.classify("211.75.1.9") is None
    assert dns_info.lookup("211.75.1.9", online=False)["source"] == "none"


def test_dns_provider_is_company_not_contact_person(monkeypatch):
    """回歸：DNS 服務商要顯示公司名稱；舊版用註冊資料的聯絡人，結果顯示成人名。"""
    monkeypatch.setattr(dns_info, "_ipinfo", lambda ip, t: ("Union Broadband Network", "dns.example.net"))
    r = dns_info.lookup("211.75.1.9")
    assert r == {"name": "Union Broadband Network（dns.example.net）", "source": "ipinfo"}
    assert dns_info._clean_org("AS9924 Taiwan Fixed Network, Telco") == "Taiwan Fixed Network, Telco"
    assert dns_info.classify("61.31.233.1")["name"] == "台灣固網 DNS"
    monkeypatch.setattr(dns_info, "_ipinfo", lambda ip, t: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(dns_info, "_ptr", lambda ip: None)
    assert dns_info.lookup("211.75.1.9")["name"] == "未知"


def test_dns_advice_summary_lists_providers_once():
    r = build(env={"interface_type": "Wi-Fi", "dns": ["192.168.0.1", "61.31.233.1", "61.31.1.1"], "vpn": {}},
              dns_names={"192.168.0.1": {"name": "路由器（轉送給上游 DNS）"}, "61.31.233.1": {"name": "台灣固網 DNS"}, "61.31.1.1": {"name": "台灣固網 DNS"}})
    d = next(s for s in r["sections"] if s["key"] == "dns")
    assert d["summary"] == "共 3 個，由 你的路由器、台灣固網 DNS 提供。"
