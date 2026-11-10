"""speedtest.py —— 下載速度測試（用系統 curl 從 Cloudflare 下載固定大小的檔案）。

💡 為什麼不另外裝測速套件？curl 是 macOS 內建的，不用多裝東西；
   Cloudflare 的 `__down?bytes=N` 會回傳 N 個位元組的測試資料，N 必須小於 1 億（100,000,000）。
⚠️ 下載時會把頻寬吃滿，同一時間的延遲數字會變差（這叫 bufferbloat，本身也是有用的資訊）。
"""
from __future__ import annotations

DEFAULT_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
MAX_BYTES = 90_000_000


def build_cmd(nbytes: int, url_tpl: str = DEFAULT_URL, max_time: int = 40) -> list:
    nbytes = max(1_000_000, min(int(nbytes), MAX_BYTES))
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


async def run_curl(runner, nbytes: int, url_tpl: str = DEFAULT_URL) -> dict:
    try:
        code, out = await runner(build_cmd(nbytes, url_tpl))
    except OSError:
        return {"ok": False, "error": "找不到 curl"}
    res = parse_result(out) if out.strip() else None
    if res is None:
        return {"ok": False, "error": f"curl 失敗（代碼 {code}），可能是網路不通或逾時"}
    if not res["ok"]:
        res["error"] = f"伺服器回應 {res['http']}"
    return res
