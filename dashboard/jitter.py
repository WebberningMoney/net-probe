"""jitter.py —— 抖動（延遲尖峰）分析：找出尖峰「多久來一次」「是不是在你到路由器這一段就發生」。

💡 為什麼看這兩件事？
   • 規律的尖峰（每隔固定秒數一次）通常來自「某個週期性的東西」：掃描、頻道切換、排程工作…
   • 不規律的尖峰（隨機一陣一陣）通常是「共用電波被搶」：鄰居 Wi-Fi 干擾、訊號邊緣、路由器忙碌…
   • 路由器本身（家裡區網）就有尖峰 → 問題在 你的裝置⇄路由器 這一段（Wi-Fi／路由器）；
     只有外部目標有尖峰、路由器正常 → 問題在路由器之後（ISP／遠端）。
⚠️ 這裡只能「縮小範圍」，不能直接點名元凶；要確認請做對照實驗（有線 vs 無線、換頻道…）。
"""
from __future__ import annotations

import statistics
from typing import Optional

MIN_SAMPLES = 60


def _series(rows: list) -> dict:
    return {ts: rtt for ts, rtt in rows}


def spike_threshold(rtts: list) -> Optional[tuple]:
    """回傳 (基準 ms, 尖峰門檻 ms)。門檻＝max(基準×3, 基準+20)。"""
    ok = [r for r in rtts if r is not None]
    if len(ok) < MIN_SAMPLES // 2:
        return None
    base = statistics.median(ok)
    return base, max(base * 3, base + 20)


def spike_starts(series: dict, thr: float) -> list:
    """連續超過門檻（或逾時）的秒數合併成一次尖峰，回傳每次的起始秒。"""
    if not series:
        return []
    t0, t1 = min(series), max(series)
    starts, prev = [], False
    for t in range(t0, t1 + 1):
        v = series.get(t, 0)
        hot = v is None or v > thr
        if hot and not prev:
            starts.append(t)
        prev = hot
    return starts


def dominant_period(starts: list, t0: int, t1: int, max_lag: int = 120) -> Optional[tuple]:
    """用自相關找尖峰的週期：回傳 (週期秒, 規律程度 0–1)；不夠規律回傳 None。"""
    n = t1 - t0 + 1
    if len(starts) < 6 or n < 40:
        return None
    x = [0.0] * n
    for s in starts:
        x[s - t0] = 1.0
    m = sum(x) / n
    den = sum((v - m) ** 2 for v in x)
    if den == 0:
        return None
    cs = {}
    for lag in range(2, min(max_lag, n // 3) + 1):
        cs[lag] = sum((x[i] - m) * (x[i + lag] - m) for i in range(n - lag)) / den
    best = max(cs.values())
    if best < 0.25:
        return None
    lag = next(l for l in sorted(cs) if cs[l] >= 0.8 * best)      # 取第一個夠強的（避開倍數）
    return lag, round(min(1.0, best), 2)


def _sync(a_starts: list, others: list, need: float = 0.6) -> float:
    """a 的尖峰中，有多少比例「同時」（±1 秒）有至少 need 比例的其他目標也在尖峰。"""
    if not a_starts or not others:
        return 0.0
    hit = 0
    for s in a_starts:
        n = sum(1 for o in others if any(abs(s - t) <= 1 for t in o))
        if n >= need * len(others):
            hit += 1
    return hit / len(a_starts)


def analyze(subject: dict, others: dict, subject_is_router: bool) -> dict:
    """subject = {ts: rtt}（通常是路由器）；others = {名稱: {ts: rtt}}（外部目標）。"""
    th = spike_threshold(list(subject.values()))
    if th is None or len(subject) < MIN_SAMPLES:
        return {"ok": False, "reason": "資料還不夠（至少需要約 1 分鐘）"}
    base, thr = th
    starts = spike_starts(subject, thr)
    t0, t1 = min(subject), max(subject)
    minutes = max(1e-9, (t1 - t0 + 1) / 60)
    hot_share = sum(1 for v in subject.values() if v is None or v > thr) / len(subject)
    per = dominant_period(starts, t0, t1)
    ex_starts = []
    for s in others.values():
        t = spike_threshold(list(s.values()))
        ex_starts.append(spike_starts(s, t[1]) if t else [])
    sync = round(_sync(starts, [e for e in ex_starts if e]), 2) if starts else 0.0
    out = {"ok": True, "baseline_ms": round(base, 1), "threshold_ms": round(thr, 1), "spikes": len(starts),
           "per_min": round(len(starts) / minutes, 1), "hot_share": round(hot_share * 100, 1),
           "period_s": per[0] if per else None, "regularity": per[1] if per else None,
           "sync_with_external": sync, "subject_is_router": subject_is_router}
    out["findings"] = findings(out)
    return out


def findings(r: dict) -> list:
    """把數字翻成白話。原因一律用「可能」，並附上可做的對照實驗。"""
    f = []
    who = "路由器（區網）" if r["subject_is_router"] else "第一個目標"
    if r["per_min"] < 1 and not r["period_s"]:
        return [f"{who}幾乎沒有延遲尖峰（每分鐘不到 1 次），區網這一段是穩的。"]
    f.append(f"{who}平常約 {r['baseline_ms']} ms，超過 {r['threshold_ms']} ms 就算尖峰；"
             f"每分鐘約 {r['per_min']} 次，約 {r['hot_share']}% 的時間處於尖峰。")
    if r["subject_is_router"]:
        if r["baseline_ms"] > 15 or r["per_min"] >= 3:
            f.append("區網（你的裝置到路由器）本身就在跳動——這是「你這一端」的問題，不是 ISP。")
        if r["sync_with_external"] >= 0.6:
            f.append(f"外部目標的尖峰有約 {int(r['sync_with_external'] * 100)}% 與路由器同時發生，"
                     "代表外部的跳動多半是從區網這一段帶出去的。")
    p = r["period_s"]
    if p and r["regularity"] and r["regularity"] >= 0.25:
        f.append(f"尖峰有規律：約每 {p} 秒一次（規律程度 {r['regularity']}）。")
        if p >= 45:
            f.append("每分鐘左右一次，可能是 Wi-Fi 背景掃描或排程工作（例如工具／系統定時掃描網路、雲端同步）。"
                     "對照：關掉 Wi-Fi 詳細資訊的自動更新、暫停雲端同步／備份，看週期是否消失。")
        elif p >= 2:
            f.append("幾秒一次的規律尖峰，常見於 Wi-Fi 層的週期行為：macOS 的 AirDrop／接力（AWDL）頻道切換、"
                     "藍牙與 2.4 GHz 共存、或路由器的省電／排程機制。對照：先關 AirDrop 與接力、"
                     "改接網路線，看尖峰是否消失。")
    else:
        f.append("尖峰沒有固定週期、一陣一陣隨機出現——較像無線電波被搶（鄰居 Wi-Fi 干擾、同頻道擁擠、"
                 "訊號偏弱時速率反覆調整）或路由器忙碌。對照：換頻道／改 40 MHz 寬度、靠近路由器、"
                 "改接網路線；若有線也跳，才懷疑路由器本身。")
    return f
