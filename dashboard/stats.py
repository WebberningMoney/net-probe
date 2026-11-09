"""stats.py —— 統計與品質分數（純計算，不碰網路、不碰檔案）。

💡 為什麼獨立成一支？「純函式」（同樣輸入必得同樣輸出）最容易測試：
   本檔可以在任何系統用假資料驗證，不需要真的連網。

資料格式：一串「樣本」，每個樣本是延遲毫秒（float），逾時/丟包則是 None。
   例：[12.3, 11.9, None, 13.0]
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

Sample = Optional[float]


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """百分位數（線性插值）。p 介於 0~100。

    🔰 p95 = 「95% 的樣本都比這個值小」，比平均更能反映偶爾的尖峰；
       p50 就是中位數，不會被少數極端值拉歪。
    """
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def jitter(samples: Sequence[Sample]) -> Optional[float]:
    """抖動 = 「連續兩次成功樣本」差的絕對值的平均（與 Bash 版相同定義）。"""
    ok = [x for x in samples if x is not None]
    if len(ok) < 2:
        return None
    diffs = [abs(b - a) for a, b in zip(ok, ok[1:])]
    return sum(diffs) / len(diffs)


def ping_score(loss_pct: float, avg: Optional[float], jit: Optional[float]) -> Optional[float]:
    """與 Bash 版相同：Score = 100 − (Loss%×2 + Avg/2 + Jit×1.5)，限制在 0~100。"""
    if avg is None:
        return None
    j = jit if jit is not None else 0.0
    return max(0.0, min(100.0, 100 - (loss_pct * 2 + avg / 2 + j * 1.5)))


def mos(avg: Optional[float], jit: Optional[float], loss_pct: float) -> Optional[float]:
    """MOS（平均意見分，1~4.5）：把延遲/抖動/丟包換算成「通話品質」分數。

    採用常見的 E-model 簡化近似（ITU-T G.107 的簡化形式，網路業界常用）：
      有效延遲 = Avg + 2×Jitter + 10
      R = 93.2 − 有效延遲/40            （有效延遲 < 160ms）
        = 93.2 − (有效延遲−120)/10      （否則）
      R −= 2.5 × 丟包%
      MOS = 1 + 0.035R + R(R−60)(100−R)×7e-6
    4.3 以上極佳、4.0 以上良好、3.6 以上尚可、更低通話會明顯受影響。
    """
    if avg is None:
        return None
    j = jit if jit is not None else 0.0
    eff = avg + 2 * j + 10
    r = 93.2 - eff / 40 if eff < 160 else 93.2 - (eff - 120) / 10
    r -= 2.5 * loss_pct
    r = max(0.0, min(100.0, r))
    m = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6
    return max(1.0, min(4.5, m))


def grade(score: Optional[float]) -> str:
    """等級（與 Bash 版相同門檻）。"""
    if score is None:
        return "N/A"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Moderate"
    return "Poor"


def summarize(samples: Sequence[Sample]) -> dict:
    """一次算出所有指標。沒有成功樣本時，延遲類欄位為 None。"""
    total = len(samples)
    ok = [x for x in samples if x is not None]
    lost = total - len(ok)
    loss_pct = (lost / total * 100.0) if total else 0.0
    avg = (sum(ok) / len(ok)) if ok else None
    jit = jitter(samples)
    score = ping_score(loss_pct, avg, jit)
    return {
        "count": total,
        "lost": lost,
        "loss_pct": round(loss_pct, 2),
        "avg": _r(avg),
        "min": _r(min(ok)) if ok else None,
        "max": _r(max(ok)) if ok else None,
        "p50": _r(percentile(ok, 50)),
        "p95": _r(percentile(ok, 95)),
        "p99": _r(percentile(ok, 99)),
        "jitter": _r(jit),
        "score": _r(score, 1),
        "grade": grade(score),
        "mos": _r(mos(avg, jit, loss_pct), 2),
    }


def _r(x: Optional[float], n: int = 3) -> Optional[float]:
    return None if x is None else round(x, n)
