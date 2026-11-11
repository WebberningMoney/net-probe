"""speedtest.py —— 下載速度測試（用 Mac 內建的 curl 從 Cloudflare 下載一個測試檔）。

💡 為什麼不另外裝測速軟體？curl 是 macOS 內建的；Cloudflare 的網址 `__down?bytes=N`
   會直接給你 N 個位元組的測試資料，很適合拿來量速度。
   先試著一次下載整個大小；如果 Cloudflare 拒絕（作者 2026 年實測：1 億位元組以上會被拒），
   才自動拆成幾段分別下載，再合併計算。
⚠️ 下載時會把網路塞滿，同一段時間的延遲會變差（這叫 bufferbloat，本身也是有用的資訊）。
"""
from __future__ import annotations

import time

DEFAULT_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
CHUNK_MAX = 90_000_000                      # Cloudflare 單次 bytes 必須 < 1 億
SIZES_MB = (25, 50, 100, 200, 500, 1000)    # 介面可選的總下載量
MAX_TOTAL_SEC = 180                         # 全部下載的時間上限，超過就用「已下載的部分」計算


def plan_chunks(total_bytes: int) -> list:
    """總量超過單次上限就平均切成數次：500 MB → 6 次 × 約 83 MB。"""
    n = -(-total_bytes // CHUNK_MAX)         # 無條件進位
    return [total_bytes // n] * n


def build_cmd(nbytes: int, url_tpl: str = DEFAULT_URL, max_time: int = 40, cap: int = CHUNK_MAX) -> list:
    nbytes = max(1_000_000, min(int(nbytes), cap))
    return ["curl", "-s", "-o", "/dev/null", "--max-time", str(max_time),
            "-w", "%{http_code} %{speed_download} %{time_connect} %{time_starttransfer} %{time_total} %{size_download}",
            url_tpl.format(bytes=nbytes)]


def parse_result(out: str) -> dict | None:
    """解析 curl -w 輸出：`200 12345678.0 0.03 0.12 4.5 25000000`。"""
    try:
        code, speed, conn, ttfb, total, size = out.split()
        d = {"http": int(code), "mbps": round(float(speed) * 8 / 1e6, 1),
             "connect_ms": round(float(conn) * 1000), "ttfb_ms": round(float(ttfb) * 1000),
             "seconds": round(float(total), 1), "bytes": int(float(size))}
    except ValueError:
        return None
    d["ok"] = d["http"] == 200 and d["bytes"] > 0
    return d


async def run_curl(runner, total_bytes: int, url_tpl: str = DEFAULT_URL,
                   max_total_sec: float = MAX_TOTAL_SEC, clock=time.monotonic) -> dict:
    """下載並計算速度＝總位元組 ÷ 總下載時間；超過時間上限就只算已下載的部分。

    💡 大於 1 億位元組時，先「直接要整個大小」試試（Cloudflare 的限制可能已放寬）；
       伺服器拒絕（HTTP 4xx）才自動改成拆成多段。
    """
    total = max(1_000_000, int(total_bytes))
    chunks = [total] if total > CHUNK_MAX else plan_chunks(total)
    t0, parts, err, i = clock(), [], None, 0
    while i < len(chunks):
        n = chunks[i]
        left = max_total_sec - (clock() - t0)
        if parts and left < 5:               # 時間用完：停止，用已下載的部分計算
            break
        try:
            code, out = await runner(build_cmd(n, url_tpl, max_time=max(5, int(left)), cap=max(n, CHUNK_MAX)))
        except OSError:
            return {"ok": False, "error": "找不到 curl"}
        r = parse_result(out) if out.strip() else None
        if r is not None and 400 <= r["http"] < 500 and n > CHUNK_MAX:
            chunks, i = plan_chunks(total), 0      # 伺服器拒絕單次大檔 → 改拆段
            continue
        if r is None or not r["ok"]:
            err = f"curl 失敗（代碼 {code}）" if r is None else f"伺服器回應 {r['http']}"
            break
        parts.append(r)
        i += 1
    if not parts:
        return {"ok": False, "error": (err or "下載失敗") + "，可能是網路不通或逾時"}
    secs = sum(p["seconds"] for p in parts) or 0.001
    got = sum(p["bytes"] for p in parts)
    req = total
    return {"ok": True, "http": 200, "bytes": got, "requested": req, "chunks": len(parts),
            "seconds": round(secs, 1), "mbps": round(got * 8 / secs / 1e6, 1),
            "connect_ms": parts[0]["connect_ms"], "ttfb_ms": parts[0]["ttfb_ms"],
            "partial": got < req * 0.99, "error": err if got < req * 0.99 else None}
