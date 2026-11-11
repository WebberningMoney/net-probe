"""dns_info.py —— 把 DNS 伺服器的 IP 翻成「是誰提供的」。

三層，由便宜到貴：
  ① 內建名單：Google、Cloudflare、Quad9、OpenDNS、AdGuard、中華電信 HiNet 等常見服務。
  ② 私有位址（192.168.x.x、10.x.x.x…）：代表「你的路由器負責轉送」，實際上游由路由器決定。
  ③ 線上查詢 RDAP（IP 註冊資料庫，查這個 DNS 位址屬於哪個單位）＋反向解析（PTR）。
     只會送出「DNS 伺服器的 IP」，不會送出你自己的 IP；在設定關掉「查詢對外 IP」時不做這一層。
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from typing import Optional

KNOWN = {
    "8.8.8.8": "Google Public DNS", "8.8.4.4": "Google Public DNS",
    "2001:4860:4860::8888": "Google Public DNS", "2001:4860:4860::8844": "Google Public DNS",
    "1.1.1.1": "Cloudflare DNS", "1.0.0.1": "Cloudflare DNS", "1.1.1.2": "Cloudflare DNS（封鎖惡意網站）",
    "1.0.0.2": "Cloudflare DNS（封鎖惡意網站）", "1.1.1.3": "Cloudflare DNS（家庭過濾）", "1.0.0.3": "Cloudflare DNS（家庭過濾）",
    "2606:4700:4700::1111": "Cloudflare DNS", "2606:4700:4700::1001": "Cloudflare DNS",
    "9.9.9.9": "Quad9", "149.112.112.112": "Quad9", "2620:fe::fe": "Quad9", "2620:fe::9": "Quad9",
    "208.67.222.222": "Cisco OpenDNS", "208.67.220.220": "Cisco OpenDNS",
    "94.140.14.14": "AdGuard DNS", "94.140.15.15": "AdGuard DNS",
    "168.95.1.1": "中華電信 HiNet DNS", "168.95.192.1": "中華電信 HiNet DNS", "168.95.126.1": "中華電信 HiNet DNS",
    "101.101.101.101": "TWNIC Quad101", "101.102.103.104": "TWNIC Quad101",
}


def is_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_link_local or a.is_loopback or a in ipaddress.ip_network("100.64.0.0/10")


def classify(ip: str) -> Optional[dict]:
    """不連網就能判斷的部分；認不出來回傳 None（交給線上查詢）。"""
    if ip in KNOWN:
        return {"name": KNOWN[ip], "source": "builtin"}
    if is_private(ip):
        return {"name": "路由器（轉送給上游 DNS）", "source": "private"}
    return None


def _rdap(ip: str, timeout: float) -> Optional[str]:
    req = urllib.request.Request(f"https://rdap.org/ip/{ip}", headers={"Accept": "application/rdap+json", "User-Agent": "NetSonar"})
    with urllib.request.urlopen(req, timeout=timeout) as r:          # 會自動轉址到負責該 IP 的註冊機構
        d = json.loads(r.read(200_000).decode("utf-8", "replace"))
    for e in d.get("entities", []):                                    # 優先用「持有單位」的名稱
        if any(role in ("registrant", "administrative") for role in e.get("roles", [])):
            for item in (e.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn" and item[3]:
                    return str(item[3])[:60]
    return str(d["name"])[:60] if d.get("name") else None


def _ptr(ip: str) -> Optional[str]:
    try:
        return socket.gethostbyaddr(ip)[0][:80]
    except (OSError, UnicodeError):
        return None


def lookup(ip: str, online: bool = True, timeout: float = 5.0) -> dict:
    """完整查詢（會阻塞，請在執行緒裡呼叫）。永遠回傳可顯示的結果。"""
    c = classify(ip)
    if c:
        return c
    if not online:
        return {"name": "未知（已關閉線上查詢）", "source": "none"}
    org = host = None
    try:
        org = _rdap(ip, timeout)
    except Exception:
        pass
    host = _ptr(ip)
    if org:
        return {"name": org + (f"（{host}）" if host and host not in org else ""), "source": "rdap"}
    if host:
        return {"name": host, "source": "ptr"}
    return {"name": "未知", "source": "none"}
