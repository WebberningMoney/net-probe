from storage import Storage


def test_rollup_and_purge(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    base = 1_700_000_040  # 60 的倍數
    assert base % 60 == 0
    # 第 1 分鐘：10 筆（2 筆丟包）；第 2 分鐘：5 筆
    for i in range(10):
        st.add_samples(base + i, {"A": None if i < 2 else 10.0 + i})
    for i in range(5):
        st.add_samples(base + 60 + i, {"A": 20.0})
    # 現在時間在第 2 分鐘內 → 只彙總第 1 分鐘
    assert st.rollup(base + 62) == 1
    assert st.rollup(base + 62) == 0          # 重複呼叫不會重複寫入
    series = st.minute_series("A", base)
    assert len(series) == 1
    assert series[0]["count"] == 10 and series[0]["lost"] == 2
    # 時間走到第 3 分鐘 → 第 2 分鐘也被彙總
    assert st.rollup(base + 130) == 1
    assert len(st.minute_series("A", base)) == 2
    # purge：原始資料超過 24h 刪除，彙總保留
    st.purge(base + 25 * 3600, raw_hours=24, minute_days=90)
    assert st.recent_rtts("A", 0) == []
    assert len(st.minute_series("A", 0)) == 2
    # 超過 90 天連彙總也刪
    st.purge(base + 91 * 86400)
    assert st.minute_series("A", 0) == []
    st.close()


def test_recent_rtts_filters_by_time(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    st.add_samples(100, {"A": 1.0, "B": 2.0})
    st.add_samples(200, {"A": None, "B": 3.0})
    assert st.recent_rtts("A", 150) == [None]
    assert st.recent_rtts("B", 0) == [2.0, 3.0]
    st.close()
