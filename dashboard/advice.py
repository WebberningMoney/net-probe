"""advice.py —— 把所有檢查結果整理成「整體網路建議」，分段、白話、有狀態燈號。

輸入都是儀表板已經算好的東西（各目標統計、判讀、環境、Wi-Fi、抖動分析、DNS），這裡只負責翻成人話。
level：ok（正常）／warn（留意）／bad（需要處理）／info（僅供參考）。
⚠️ 全部是「提示」不是鑑定；門檻是業界常見的粗略分級。
"""
from __future__ import annotations

from statistics import median

ORDER = {"ok": 0, "info": 0, "warn": 1, "bad": 2}


def snr_label(snr: int) -> str:
    return "極佳" if snr >= 40 else "良好" if snr >= 25 else "偏低" if snr >= 15 else "很差"


def noise_label(dbm: int) -> str:
    return "很乾淨" if dbm <= -90 else "正常" if dbm <= -80 else "偏吵"


def _worst(*levels: str) -> str:
    return max(levels, key=lambda x: ORDER[x])


def _wifi(env: dict, wifi: dict | None) -> dict | None:
    typ = (env or {}).get("interface_type")
    if not wifi:
        if typ and "Wi-Fi" not in typ:
            return {"key": "wifi", "title": "連線方式", "level": "ok", "summary": f"目前是{typ}，沒有 Wi-Fi 的訊號問題。", "tips": []}
        return None
    sig, snr, tips = wifi.get("signal_dbm"), wifi.get("snr_db"), []
    lv = "ok"
    if sig is not None:
        if sig < -72:
            lv, _ = "bad", tips.append("訊號很弱：靠近路由器、減少中間的牆，或加一台 Wi-Fi 延伸器（Mesh）。")
        elif sig < -67:
            lv, _ = "warn", tips.append("訊號偏弱：視訊或遊戲可能不穩，建議靠近路由器一點。")
    if snr is not None:
        if snr < 15:
            lv, _ = _worst(lv, "bad"), tips.append("訊噪比很差：周圍干擾多，試著換 Wi-Fi 頻道，或改用 5 GHz。")
        elif snr < 25:
            lv, _ = _worst(lv, "warn"), tips.append("訊噪比偏低：周圍可能有干擾（鄰居的 Wi-Fi、微波爐等）。")
    if wifi.get("band") == "2.4 GHz":
        tips.append("目前連在 2.4 GHz：穿牆好但很擁擠；若路由器有 5 GHz，優先連 5 GHz。")
    if wifi.get("tx_rate_mbps") and wifi["tx_rate_mbps"] < 100:
        tips.append("連線速率偏低（低於 100 Mbps），大檔案下載可能受限。")
    parts = []
    if sig is not None:
        parts.append(f"訊號強度 {sig} dBm（{wifi.get('signal_label', '')}）")
    if snr is not None:
        parts.append(f"訊噪比 {snr} dB（{snr_label(snr)}）")
    if wifi.get("band"):
        parts.append(f"{wifi['band']}・{wifi.get('width', '')}")
    return {"key": "wifi", "title": "Wi-Fi 連線", "level": lv, "summary": "，".join(parts) + "。", "tips": tips}


def _router(s: dict | None, name: str | None) -> dict | None:
    if not name or not s or s.get("count", 0) < 20 or s.get("avg") is None:
        return None
    lv, tips = "ok", []
    if s["loss_pct"] >= 1 or (s["p95"] or 0) >= 30:
        lv = "bad"
        tips.append("你的裝置到路由器這一小段就不穩，問題在你家裡（Wi-Fi、路由器或這台電腦），不是網路公司。")
    elif (s["jitter"] or 0) >= 5 or (s["p95"] or 0) >= 15:
        lv = "warn"
        tips.append("到路由器的延遲偶爾跳動，可能有無線干擾或本機背景程式；詳見「抖動」。")
    return {"key": "router", "title": "家裡這一段（到路由器）", "level": lv,
            "summary": f"平均 {round(s['avg'], 1)} ms，慢的時候 {round(s['p95'], 1)} ms，丟包 {round(s['loss_pct'], 2)}%。", "tips": tips}


def _external(summaries: dict, router: str | None, dead: set) -> dict | None:
    ext = {k: v for k, v in summaries.items() if k != router and k not in dead and v.get("count", 0) >= 20 and v.get("avg") is not None}
    if not ext:
        return None
    jit = median(v["jitter"] or 0 for v in ext.values())
    loss = max(v["loss_pct"] for v in ext.values())
    far = [k for k, v in ext.items() if v["avg"] > 50 and (v["jitter"] or 0) < 10 and v["loss_pct"] < 1]
    lv, tips = "ok", []
    if loss >= 5 or jit >= 25:
        lv = "bad"
        tips.append("外部目標普遍不穩。若「家裡這一段」正常，問題在家以外：可以記下發生的時段，向網路公司反映。")
    elif loss >= 2 or jit >= 10:
        lv = "warn"
        tips.append("外部連線有些不穩，持續觀察是否固定在某些時段發生。")
    if far:
        tips.append("、".join(far) + " 的延遲較高是因為伺服器離台灣比較遠（物理距離），不是網路壞掉，可放心忽略。")
    near_avg = median(v["avg"] for v in ext.values())
    return {"key": "external", "title": "連到外面的網路", "level": lv,
            "summary": f"{len(ext)} 個外部目標，典型延遲約 {round(near_avg)} ms，抖動約 {round(jit, 1)} ms，最高丟包 {round(loss, 2)}%。", "tips": tips}


def _jitter(j: dict | None) -> dict:
    if not j or not j.get("ok"):
        return {"key": "jitter", "title": "抖動（忽快忽慢）", "level": "info",
                "summary": "資料還不夠，再等幾分鐘。", "tips": []}
    pm = j["per_min"]
    lv = "ok" if pm < 1 else "warn" if pm < 6 else "bad"
    summ = "幾乎沒有延遲尖峰，連線很穩。" if pm < 1 else f"每分鐘約 {pm} 次延遲尖峰" + (f"，約每 {j['period_s']} 秒一次。" if j.get("period_s") else "，沒有固定規律。")
    return {"key": "jitter", "title": "抖動（忽快忽慢）", "level": lv, "summary": summ,
            "tips": [] if lv == "ok" else list(j.get("findings", []))}


def _dns(env: dict, names: dict) -> dict | None:
    ips = (env or {}).get("dns") or []
    if not ips:
        return None
    rows = [f"{ip}：{(names.get(ip) or {}).get('name', '查詢中…')}" for ip in ips]
    tips = []
    if all(ip.startswith(("192.168.", "10.", "172.")) for ip in ips):
        tips.append("電腦把所有網址查詢交給路由器代辦；路由器再去問上游，實際用誰由路由器的設定決定。")
    return {"key": "dns", "title": "DNS（網址翻譯服務）", "level": "info", "summary": "；".join(rows) + "。", "tips": tips}


def _vpn(env: dict) -> dict | None:
    v = (env or {}).get("vpn") or {}
    if not v.get("active"):
        return None
    return {"key": "vpn", "title": "VPN", "level": "info",
            "summary": f"VPN 開啟中（{v.get('interface', '')}）。", "tips": ["所有延遲都包含「繞到 VPN 伺服器」的距離，數值會偏高；『家裡這一段』才是你家到路由器的真實狀況。"]}


def build(summaries: dict, diagnosis: dict, env: dict, wifi: dict | None, jitter: dict | None,
          dns_names: dict, router_name: str | None, dead: set) -> dict:
    sections = []
    code = diagnosis.get("code")
    sections.append({"key": "where", "title": "問題出在哪一段？", "info_only": True,
                     "level": {"ok": "ok", "target": "warn", "local": "bad", "upstream": "bad"}.get(code, "info"),
                     "summary": diagnosis.get("title", ""), "tips": [diagnosis["detail"]] if diagnosis.get("detail") and code not in ("ok",) else []})
    for sec in (_wifi(env, wifi), _router(summaries.get(router_name) if router_name else None, router_name),
                _external(summaries, router_name, dead), _jitter(jitter), _dns(env, dns_names), _vpn(env)):
        if sec:
            sections.append(sec)
    worst = _worst("ok", *[s["level"] for s in sections])
    n = sum(1 for s in sections if s["level"] == worst)
    title = {"ok": "整體狀況良好", "warn": f"有 {n} 項需要留意", "bad": f"有 {n} 項需要處理"}[worst]
    detail = {"ok": "各項檢查都在正常範圍。", "warn": "整體可用，但下面標黃色的項目值得看一下。",
              "bad": "請先處理下面標紅色的項目。"}[worst]
    return {"overall": {"level": worst, "title": title, "detail": detail}, "sections": sections}
