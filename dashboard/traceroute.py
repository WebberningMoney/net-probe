"""traceroute.py —— 路徑分析：一站一站看「從這裡到目標」的延遲。

macOS 內建 `traceroute` 不需要 sudo（作者 Mac 實測）。用 -n 不做反向 DNS，較快。
💡 看懂結果：
   • 某一跳顯示 `*` = 沒回應。很多路由器為了安全/效能不回應 traceroute，不代表有問題。
   • 只有「單一跳」特別高、後面都正常 → 多半是該節點「不優先處理追蹤封包」，不是真的塞車。
   • 延遲「從某一跳開始升高，之後每一跳都維持高檔」→ 問題多半在那一跳附近。
"""
from __future__ import annotations

import asyncio
import re
import statistics
from typing import AsyncIterator, Optional

_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_IPV6 = re.compile(r"^[0-9a-fA-F:]+:[0-9a-fA-F:]*$")
_NUM = re.compile(r"^\d+(\.\d+)?$")
_TARGET_OK = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$|^[0-9a-fA-F:]{2,45}$")


def valid_target(t: str) -> bool:
    """只允許網址／IPv4／IPv6 文字，且不得以 - 開頭（避免被當成指令選項）。"""
    return bool(t) and len(t) <= 253 and not t.startswith("-") and bool(_TARGET_OK.match(t))


def build_cmd(target: str, queries: int = 3, wait: int = 1, max_hops: int = 20) -> list:
    return ["traceroute", "-n", "-q", str(queries), "-w", str(wait), "-m", str(max_hops), target]


def parse_hop_line(line: str) -> Optional[dict]:
    """解析一行，例：` 3  10.0.0.1  9.1 ms  10.2 ms  *`。不是「跳」的行回傳 None。"""
    m = re.match(r"^\s*(\d+)\s+(.*)$", line)
    if not m:
        return None
    tokens = m.group(2).split()
    ips, rtts, stars = [], [], 0
    for i, t in enumerate(tokens):
        if t == "*":
            stars += 1
        elif _NUM.match(t) and i + 1 < len(tokens) and tokens[i + 1] == "ms":
            rtts.append(float(t))
        elif _IPV4.match(t) or (_IPV6.match(t) and ":" in t):
            if t not in ips:
                ips.append(t)
    sent = len(rtts) + stars
    return {"hop": int(m.group(1)), "ip": ips[0] if ips else None, "ips": ips, "rtts": rtts,
            "lost": stars, "loss_pct": round(stars / sent * 100, 1) if sent else 0.0,
            "min": round(min(rtts), 1) if rtts else None,
            "avg": round(sum(rtts) / len(rtts), 1) if rtts else None,
            "max": round(max(rtts), 1) if rtts else None}


def analyze_hops(hops: list, vpn_active: bool = False) -> dict:
    """為每一跳標記狀態（ok／high／none），並產生白話結論。"""
    status = {h["hop"]: ("none" if not h["rtts"] else "ok") for h in hops}
    resp = [h for h in hops if h["rtts"]]
    title, detail = "沒有發現明顯異常", "各節點延遲沒有出現持續升高的跡象。"
    rise_at = None
    for j in range(1, len(resp)):
        later = [x["avg"] for x in resp[j:]]
        if resp[j]["avg"] - resp[j - 1]["avg"] >= 30 and min(later) >= 0.7 * resp[j]["avg"]:
            rise_at = resp[j]["hop"]
            break
    spikes = []
    for j, h in enumerate(resp[:-1]):
        later = [x["avg"] for x in resp[j + 1:]]
        med = statistics.median(later)
        if h["avg"] > 1.5 * med and h["avg"] - med >= 20:
            spikes.append(h["hop"])
    if rise_at is not None:
        status[rise_at] = "high"
        title = f"延遲從第 {rise_at} 站開始升高，之後都維持高檔"
        detail = (f"第 {rise_at} 站之後每一站都偏高，問題多半在第 {rise_at - 1}～{rise_at} 站之間的線路"
                  "（如果是第 1～2 站，通常是你的 Wi-Fi、路由器或網路公司接到你家的線路）。建議在不同時段多測幾次再判斷。")
    elif spikes:
        for s in spikes:
            status[s] = "high"
        title = "第 " + "、".join(map(str, spikes)) + " 站偏高，但後面都正常"
        detail = "通常是那一站「不急著回應這種測試」，不代表真的塞車。真正要在意的是：延遲從某一站開始升高，之後每一站都一樣高。"
    if vpn_active:
        detail += "　⚠️ VPN 開啟中：第 1 站通常是 VPN 通道，後面是 VPN 伺服器之後的路線，看不到你家網路公司那一段；要檢查網路公司請先關閉 VPN。"
    return {"status": status, "title": title, "detail": detail}


async def iter_lines(cmd: list) -> AsyncIterator[str]:
    """執行指令並「一行一行」回傳輸出（讓畫面可以邊跑邊顯示）。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            yield raw.decode(errors="replace").rstrip("\n")
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
