import random
import jitter as j


def series(n, spike_every=None, jitter_prob=0.0, base=5.0, seed=1, start=1000):
    rnd = random.Random(seed)
    out = {}
    for i in range(n):
        v = base + rnd.random() * 2
        if spike_every and i % spike_every == 0 and i:
            v = 90.0
        elif rnd.random() < jitter_prob:
            v = 80.0
        out[start + i] = v
    return out


def test_regular_spikes_found():
    s = series(300, spike_every=4)
    r = j.analyze(s, {}, True)
    assert r["ok"] and r["period_s"] == 4 and r["regularity"] >= 0.5 and r["per_min"] > 10
    assert any("每 4 秒" in x for x in r["findings"]) and any("區網" in x for x in r["findings"])


def test_minute_period_hint():
    s = series(480, spike_every=60)
    r = j.analyze(s, {}, True)
    assert r["period_s"] == 60 and any("掃描" in x for x in r["findings"])


def test_random_spikes_have_no_period():
    r = j.analyze(series(400, jitter_prob=0.15, seed=7), {}, True)
    assert r["ok"] and (r["period_s"] is None or r["regularity"] < 0.4)
    assert any("隨機" in x for x in r["findings"])


def test_clean_router_and_sync():
    clean = j.analyze(series(200, base=3.0), {}, True)
    assert clean["per_min"] < 1 and "穩" in clean["findings"][0]
    s = series(300, spike_every=5)
    ext = {"A": {t: (v + 30 if v > 50 else v + 30) for t, v in s.items()},
           "B": {t: (v + 40) for t, v in s.items()}}
    r = j.analyze(s, ext, True)
    assert r["sync_with_external"] >= 0.9 and any("同時發生" in x for x in r["findings"])


def test_not_enough_data_and_losses_count_as_spikes():
    assert not j.analyze({1000 + i: 5.0 for i in range(20)}, {}, True)["ok"]
    s = series(200, base=4.0)
    for t in range(1050, 1056):
        s[t] = None
    assert j.spike_starts(s, 20.0) == [1050]
