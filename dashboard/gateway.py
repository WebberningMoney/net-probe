"""gateway.py —— 找出「預設閘道」（通常就是你家的路由器）的 IP。

💡 為什麼要 ping 路由器？它是你和網際網路之間的第一站：
   • 路由器自己就有尖峰 → 問題在你這一端（Wi-Fi 訊號、路由器）
   • 路由器正常、外部目標才有尖峰 → 問題在路由器之後（ISP 或遠端）
macOS 指令：`route -n get default`，輸出中有一行 `gateway: 192.168.0.1`。
"""
from __future__ import annotations

import re
from typing import Optional

_GW_RE = re.compile(r"^\s*gateway:\s*(\S+)\s*$", re.MULTILINE)


def parse_route_output(text: str) -> Optional[str]:
    m = _GW_RE.search(text)
    return m.group(1) if m else None


async def get_gateway(runner) -> Optional[str]:
    """回傳閘道 IP；沒網路（沒有預設路由）或指令失敗回傳 None。"""
    try:
        code, out = await runner(["route", "-n", "get", "default"])
    except OSError:
        return None
    return parse_route_output(out) if code == 0 else None
