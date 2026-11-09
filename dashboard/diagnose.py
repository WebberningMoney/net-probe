"""diagnose.py —— 把「路由器 vs 外部目標」的數據翻成白話判讀。

判斷邏輯（門檻可在 config.json 的 diagnosis 調整）：
  路由器異常（丟包 ≥ router_loss_pct 或 p95 ≥ router_p95_ms）
      → local：問題偏向你這一端（Wi-Fi／路由器）
  路由器正常，且至少一半外部目標異常（丟包 ≥ ext_loss_pct 或 p95 ≥ ext_p95_ms）
      → upstream：問題偏向路由器之後（ISP 或遠端）
  路由器正常，只有少數目標異常 → target：可能是該目標自己的問題
  都正常 → ok
⚠️ 這是「提示」不是鑑定；樣本太少時會回報 unknown。
"""
from __future__ import annotations

DEFAULTS = {"router_loss_pct": 1.0, "router_p95_ms": 30.0,
            "ext_loss_pct": 2.0, "ext_p95_ms": 80.0, "min_samples": 20}


def _bad(s: dict, loss_th: float, p95_th: float) -> bool:
    return s["loss_pct"] >= loss_th or (s["p95"] is not None and s["p95"] >= p95_th)


def diagnose(summaries: dict, router_name: str | None, cfg: dict | None = None) -> dict:
    th = {**DEFAULTS, **(cfg or {})}
    router = summaries.get(router_name) if router_name else None
    ext = {k: v for k, v in summaries.items()
           if k != router_name and v["count"] >= th["min_samples"]}
    if router is None:
        return {"code": "no_router", "title": "未偵測到路由器",
                "detail": "找不到預設閘道（可能沒連上網路），無法判斷問題在哪一段。"}
    if router["count"] < th["min_samples"] or not ext:
        return {"code": "unknown", "title": "資料還不夠",
                "detail": f"至少需要 {th['min_samples']} 筆樣本才能判讀，請再等一下。"}
    router_bad = _bad(router, th["router_loss_pct"], th["router_p95_ms"])
    bad_names = [k for k, v in ext.items() if _bad(v, th["ext_loss_pct"], th["ext_p95_ms"])]
    if router_bad:
        return {"code": "local", "title": "問題偏向你這一端（Wi-Fi／路由器）",
                "detail": "路由器本身就有延遲尖峰或丟包。可試著：靠近路由器、改用網路線、重新啟動路由器。"}
    if len(bad_names) * 2 >= len(ext):
        return {"code": "upstream", "title": "問題偏向路由器之後（ISP 或遠端）",
                "detail": "路由器正常，但多數外部目標都不穩（" + "、".join(bad_names) +
                          "）。可持續觀察是否固定時段發生，必要時聯絡網路業者。"}
    if bad_names:
        return {"code": "target", "title": "只有部分目標不穩",
                "detail": "不穩的只有：" + "、".join(bad_names) + "，可能是該目標自己的問題。"}
    return {"code": "ok", "title": "目前正常", "detail": "路由器與外部目標都在正常範圍。"}
