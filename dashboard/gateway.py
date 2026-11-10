"""gateway.py —— 找出「實體路由器」的 IP（開 VPN 時也不會抓錯）。

💡 為什麼不能只用 `route -n get default`？
   開 VPN 時，系統有「兩條」預設路由（作者的 Mac 實測，NordVPN 開啟時）：
       default  10.5.0.2     UGScg    utun6   ← VPN 通道
       default  192.168.0.1  UGScIg   en0     ← 真正的路由器（I = 限定在此介面）
   `route -n get default` 只會回報第一條（VPN），把它當路由器會量到 VPN 的延遲，
   而且 10.5.0.2 其實是「通道在你這端的 IP」，ping 它只會得到 0.1 ms，毫無意義。
   所以改讀 `netstat -rn -f inet`，挑出「不是 VPN 介面」的那一條。
"""
from __future__ import annotations

import re
from typing import Optional

VPN_PREFIXES = ("utun", "ppp", "ipsec", "tun", "tap")   # 這些介面名稱 = 通道/VPN
_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def is_vpn_iface(name: str) -> bool:
    return name.startswith(VPN_PREFIXES)


def parse_default_routes(text: str) -> list:
    """從 `netstat -rn -f inet` 的輸出取出所有 default 路由：[{gateway, iface, flags}]。"""
    routes = []
    for line in text.splitlines():
        parts = line.split()
        # 欄位：Destination Gateway Flags Netif [Expire]
        if len(parts) >= 4 and parts[0] == "default" and _IPV4.match(parts[1]):
            routes.append({"gateway": parts[1], "flags": parts[2], "iface": parts[3]})
    return routes


def pick_gateways(routes: list) -> dict:
    """分出「實體路由器」與「VPN 通道」。沒有就是 None。"""
    physical = next((r for r in routes if not is_vpn_iface(r["iface"])), None)
    vpn = next((r for r in routes if is_vpn_iface(r["iface"])), None)
    return {"physical": physical, "vpn": vpn}


async def get_gateways(runner) -> dict:
    try:
        code, out = await runner(["netstat", "-rn", "-f", "inet"])
    except OSError:
        return {"physical": None, "vpn": None}
    return pick_gateways(parse_default_routes(out)) if code == 0 else {"physical": None, "vpn": None}


async def get_gateway(runner) -> Optional[str]:
    """相容舊介面：回傳實體路由器 IP。"""
    g = await get_gateways(runner)
    return g["physical"]["gateway"] if g["physical"] else None
