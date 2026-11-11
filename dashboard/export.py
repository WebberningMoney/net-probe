"""export.py —— 把各種紀錄轉成 CSV（可以用 Excel、Numbers、Google 試算表打開的表格檔）。

這裡只負責「排成表格文字」，不碰網路、不碰資料庫，所以很容易測試。
兩個貼心設計：
  • 檔案開頭加上 BOM（一個看不見的記號），Excel 才會把中文顯示正確，不會變亂碼。
  • 文字欄位如果以 = + - @ 開頭，前面補一個單引號。否則試算表會把它當成「公式」執行
    （例如有人把標籤取名為 =1+1）。數字欄位不受影響。
"""
from __future__ import annotations

import csv
import io
import time

BOM = "﻿"


def when(ts) -> str:
    """時間戳記（秒）→ 這台電腦當地時間的文字，例如 2026-11-12 01:23:45。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


def safe(text) -> str:
    """文字欄位防呆：避免被試算表當成公式。"""
    s = "" if text is None else str(text)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _num(v):
    return "" if v is None else v


def line(cells: list) -> str:
    """把一列資料變成 CSV 的一行（自動處理逗號、引號、換行）。"""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(cells)
    return buf.getvalue()


def table(header: list, rows) -> str:
    return BOM + line(header) + "".join(line(r) for r in rows)


def samples_stream(series):
    """量測紀錄。series 是一個「(目標名稱, [(時間, 延遲或 None), ...])」的序列；
    一個目標一個目標吐出來，資料很多（一天幾十萬筆）也不會一次佔用大量記憶體。"""
    yield BOM + line(["時間", "目標", "延遲(ms)"])
    for name, rows in series:
        n = safe(name)
        yield "".join(line([when(ts), n, "逾時" if rtt is None else rtt]) for ts, rtt in rows)


def alerts_table(alerts: list, events: list) -> str:
    rows = [(a["ts"], "警示", safe("全部目標" if a.get("target") == "全部" else a.get("target", "")), safe(a.get("message", "")))
            for a in alerts]
    rows += [(e["ts"], "Wi-Fi 資訊更新" if e.get("minor") else "網路環境變化", "", safe(e.get("text", ""))) for e in events]
    rows.sort(key=lambda r: r[0], reverse=True)
    return table(["時間", "類型", "目標", "內容"], [[when(r[0]), *r[1:]] for r in rows])


def reports_table(rows: list) -> str:
    """rows 是 /api/reports 回傳的格式（每份報告一列摘要）。"""
    out = []
    for r in rows:
        c, R, E, S = r.get("context") or {}, r.get("router") or {}, r.get("external") or {}, r.get("spikes") or {}
        out.append([safe(r.get("label", "")), when(r.get("started")), when(r.get("finished")),
                    safe(c.get("interface_type") or c.get("interface") or ""), c.get("band") or "", _num(c.get("channel")),
                    c.get("width") or "", _num(c.get("signal_dbm")), "開" if c.get("vpn") else "關",
                    _num(R.get("avg")), _num(R.get("p95")), _num(R.get("jitter")), _num(R.get("loss_pct")),
                    _num(E.get("avg")), _num(E.get("p95")), _num(E.get("jitter")), _num(E.get("loss_pct")),
                    _num(S.get("per_min")), _num(S.get("period_s"))])
    return table(["標籤", "開始", "結束", "連線方式", "頻段", "頻道", "頻寬", "訊號強度(dBm)", "VPN",
                  "路由器 平均(ms)", "路由器 慢的時候(ms)", "路由器 抖動(ms)", "路由器 丟包(%)",
                  "外部 平均(ms)", "外部 慢的時候(ms)", "外部 抖動(ms)", "外部 丟包(%)",
                  "每分鐘尖峰次數", "尖峰週期(秒)"], out)


def curl_table(results: list) -> str:
    out = []
    for c in results:
        note = ("時間到，只算已下載的部分 " if c.get("partial") else "") + (c.get("error") or "")
        out.append([when(c.get("ts")), "成功" if c.get("ok") else "失敗",
                    round(c["bytes"] / 1e6, 1) if c.get("bytes") else "", _num(c.get("mbps")),
                    _num(c.get("connect_ms")), _num(c.get("ttfb_ms")), _num(c.get("seconds")),
                    "開" if c.get("vpn") else "關", safe(note.strip())])
    return table(["時間", "結果", "下載大小(MB)", "速度(Mbps)", "連上花費(ms)", "開始回應(ms)", "總時間(秒)", "VPN", "備註"], out)


def trace_table(job: dict) -> str:
    out = [[h.get("hop"), safe(h.get("ip") or "（不回應）"), _num(h.get("avg")), _num(h.get("max")), _num(h.get("loss_pct"))]
           for h in job.get("hops", [])]
    return table(["第幾站", "位址", "平均(ms)", "最高(ms)", "丟包(%)"], out)
