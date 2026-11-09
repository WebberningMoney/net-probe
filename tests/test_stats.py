import pytest
import stats


def test_percentile_basic():
    v = [1, 2, 3, 4, 5]
    assert stats.percentile(v, 50) == 3
    assert stats.percentile(v, 0) == 1
    assert stats.percentile(v, 100) == 5
    assert stats.percentile(v, 95) == pytest.approx(4.8)
    assert stats.percentile([], 50) is None
    assert stats.percentile([7], 99) == 7


def test_jitter_ignores_losses():
    # 成功樣本 10, 20, 15 → 差 10, 5 → 平均 7.5（None 不參與）
    assert stats.jitter([10, None, 20, 15]) == 7.5
    assert stats.jitter([10]) is None
    assert stats.jitter([None, None]) is None


def test_ping_score_matches_bash_formula():
    # 100 − (0×2 + 20/2 + 4×1.5) = 84
    assert stats.ping_score(0, 20, 4) == 84
    # 下限 0
    assert stats.ping_score(100, 500, 100) == 0
    assert stats.ping_score(0, None, None) is None


def test_mos_reference_values():
    # 理想網路：avg 20ms、無抖動無丟包 → 約 4.4
    assert stats.mos(20, 0, 0) == pytest.approx(4.40, abs=0.02)
    # 5% 丟包明顯拉低
    assert stats.mos(20, 0, 5) < stats.mos(20, 0, 0) - 0.3
    # 延遲愈高愈差（單調）
    assert stats.mos(50, 0, 0) > stats.mos(200, 0, 0) > stats.mos(500, 0, 0)
    # 範圍限制
    assert 1.0 <= stats.mos(5000, 500, 100) <= 4.5
    assert stats.mos(None, None, 100) is None


def test_grade_thresholds():
    assert [stats.grade(x) for x in (95, 90, 80, 75, 70, 60, 59.9, None)] == \
        ["Excellent", "Excellent", "Good", "Good", "Moderate", "Moderate", "Poor", "N/A"]


def test_summarize_mixed():
    s = stats.summarize([10, 20, None, 30])
    assert s["count"] == 4 and s["lost"] == 1 and s["loss_pct"] == 25.0
    assert s["avg"] == 20 and s["min"] == 10 and s["max"] == 30
    assert s["p50"] == 20
    assert s["jitter"] == 10


def test_summarize_all_lost_and_empty():
    s = stats.summarize([None, None])
    assert s["loss_pct"] == 100.0 and s["avg"] is None and s["grade"] == "N/A" and s["mos"] is None
    e = stats.summarize([])
    assert e["count"] == 0 and e["loss_pct"] == 0.0 and e["avg"] is None
