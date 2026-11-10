import pytest
from fastapi.testclient import TestClient
import settings as st
from app import create_app
from storage import Storage
from test_phase4 import CFG, _runner

GOOD = {"targets": [{"name": "A", "host": "1.1.1.1"}, {"name": "我的NAS", "host": "nas.local"}],
        "interval_sec": 2, "ping_timeout_sec": 2, "gateway": {"enabled": False, "name": "路由器"},
        "alerts": {"enabled": True, "macos_notification": False, "cooldown_sec": 60, "loss_pct_1m": 5,
                   "p95_ms_1m": 200, "consecutive_timeouts": 3},
        "public_ip_lookup": False, "curl_test": {"url": "https://example.com/d?n={bytes}"}}


def test_validate_ok_and_clean():
    out = st.validate(GOOD)
    assert [t["name"] for t in out["targets"]] == ["A", "我的NAS"] and out["interval_sec"] == 2.0
    assert out["curl_test"]["url"].endswith("{bytes}")


@pytest.mark.parametrize("patch,msg", [
    ({"targets": []}, "1–8"),
    ({"targets": [{"name": "A", "host": "-w5"}]}, "位址"),
    ({"targets": [{"name": "A", "host": "x;ls"}]}, "位址"),
    ({"targets": [{"name": "<b>", "host": "1.1.1.1"}]}, "名稱"),
    ({"targets": [{"name": "A", "host": "1.1.1.1"}, {"name": "A", "host": "8.8.8.8"}]}, "重複"),
    ({"interval_sec": 0}, "測量間隔"),
    ({"interval_sec": "x"}, "數字"),
    ({"alerts": {"loss_pct_1m": 0}}, "丟包"),
    ({"curl_test": {"url": "http://x/{bytes}"}}, "https"),
    ({"curl_test": {"url": "https://x/nobytes"}}, "{bytes}"),
    ({"gateway": {"name": "A"}}, "路由器名稱"),
])
def test_validate_rejects(patch, msg):
    with pytest.raises(st.SettingsError) as e:
        st.validate({**GOOD, **patch})
    assert msg in str(e.value)


def test_settings_api_roundtrip(tmp_path):
    f = tmp_path / "s.json"
    app = create_app(dict(CFG), Storage(str(tmp_path / "s.db")), _runner, autostart=False, settings_file=f)
    with TestClient(app) as c:
        d = c.get("/api/settings").json()
        assert not d["customized"] and d["settings"]["targets"][0]["name"] == "A"
        assert c.put("/api/settings", json={**GOOD, "interval_sec": 99}).status_code == 400
        assert not f.exists()
        r = c.put("/api/settings", json=GOOD).json()
        assert r["customized"] and f.exists()
        assert [t["name"] for t in c.get("/api/targets").json()] == ["A", "我的NAS"]   # 立即生效
        eng = app.state.engine
        assert eng.cfg["interval_sec"] == 2.0 and eng.alerts.cfg["cooldown_sec"] == 60 and not eng.gateway_enabled
        assert st.load_overrides(f)["targets"][1]["host"] == "nas.local"
        r = c.post("/api/settings/reset").json()
        assert not r["customized"] and not f.exists() and eng.cfg["interval_sec"] == CFG["interval_sec"]
        assert [t["name"] for t in c.get("/api/targets").json()] == ["A"]


def test_load_overrides_ignores_junk(tmp_path):
    f = tmp_path / "s.json"
    f.write_text('{"port": 1, "interval_sec": 3}')
    assert st.load_overrides(f) == {"interval_sec": 3}
    f.write_text("not json")
    assert st.load_overrides(f) == {}
    assert st.load_overrides(tmp_path / "none.json") == {}
