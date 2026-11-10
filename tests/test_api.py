import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from app import create_app
from storage import Storage

CFG = {"targets": [{"name": "A", "host": "1.1.1.1"}, {"name": "B", "host": "9.9.9.9"}],
       "interval_sec": 0.05, "ping_timeout_sec": 1,
       "retention": {"raw_hours": 24, "minute_days": 90}}


async def fake_runner(cmd):
    host = cmd[-1]
    if host == "9.9.9.9":
        return 2, "100% packet loss"
    return 0, "64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=15.5 ms"


@pytest.fixture
def client(tmp_path):
    app = create_app(CFG, Storage(str(tmp_path / "api.db")), fake_runner, autostart=False)
    with TestClient(app) as c:
        yield c, app.state.engine


def test_health_and_targets(client):
    c, _ = client
    assert c.get("/api/health").json() == {"ok": True, "targets": 2}
    assert [t["name"] for t in c.get("/api/targets").json()] == ["A", "B"]


def test_tick_feeds_summary(client):
    c, engine = client
    for _ in range(5):
        asyncio.run(engine.tick())
    r = c.get("/api/summary?range=5m").json()["targets"]
    assert r["A"]["count"] == 5 and r["A"]["avg"] == 15.5 and r["A"]["loss_pct"] == 0
    assert r["B"]["loss_pct"] == 100.0 and r["B"]["grade"] == "N/A"
    assert c.get("/api/latest").json()["results"]["A"] == 15.5


def test_bad_range_and_unknown_target(client):
    c, _ = client
    assert c.get("/api/summary?range=9y").status_code == 400
    assert c.get("/api/history?target=Z").status_code == 404
    assert c.get("/api/history?target=A&range=24h").json()["points"] == []


def test_index_page_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "NetSonar" in r.text
