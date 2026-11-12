"""geo.py —— 查一個網路位址「大概在哪裡、是哪家公司的」（用在路徑分析的每一站，以及 DNS 服務商）。

資料來源是 ipinfo.io（和「查詢對外 IP」同一個服務）。只會送出要查的那個位址。
⚠️ 位置只是「推估」：通常只到城市，而且骨幹設備常被登記在公司所在地，不一定是機器真正的位置。
   所以畫面上一律寫「大約位置」，地圖也只當參考。
家裡或公司內部用的位址（192.168.x.x、10.x.x.x…）不是公開的，查不到也不需要查，這裡直接標示。
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.request
from typing import Optional

COUNTRY = {"TW": "台灣", "JP": "日本", "KR": "南韓", "HK": "香港", "CN": "中國", "SG": "新加坡", "US": "美國",
           "CA": "加拿大", "GB": "英國", "DE": "德國", "FR": "法國", "NL": "荷蘭", "AU": "澳洲", "IN": "印度",
           "MY": "馬來西亞", "TH": "泰國", "VN": "越南", "PH": "菲律賓", "ID": "印尼", "IT": "義大利", "ES": "西班牙",
           "SE": "瑞典", "CH": "瑞士", "RU": "俄羅斯", "BR": "巴西", "IE": "愛爾蘭", "PL": "波蘭", "FI": "芬蘭"}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def local_kind(ip: str) -> Optional[str]:
    """不公開的位址回傳種類：private（家裡／公司內部）、cgnat（網路公司內部）；公開位址回傳 None。"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if a.version == 4 and a in _CGNAT:
        return "cgnat"
    return "private" if (a.is_private or a.is_link_local or a.is_loopback) else None


def clean_org(org: str) -> str:
    """ipinfo 的 org 長得像 "AS9924 Taiwan Fixed Network ..."：去掉開頭的編號，只留公司名稱。"""
    return re.sub(r"^AS\d+\s+", "", org or "").strip()[:60]


def parse(d: dict) -> dict:
    """把 ipinfo 回傳的資料整理成我們要的欄位（查不到的欄位是 None）。"""
    lat = lon = None
    try:
        lat, lon = (round(float(x), 3) for x in str(d.get("loc", "")).split(","))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
    except ValueError:
        pass
    cc = str(d.get("country") or "")[:2].upper() or None
    city = str(d["city"])[:40] if d.get("city") else None
    cname = COUNTRY.get(cc, cc) if cc else None
    place = "，".join(x for x in (city, cname) if x) or None
    return {"kind": "public", "org": clean_org(d.get("org", "")) or None,
            "hostname": str(d["hostname"])[:80] if d.get("hostname") else None,
            "city": city, "country": cc, "place": place, "lat": lat, "lon": lon}


def lookup_ip(ip: str, timeout: float = 5.0) -> dict:
    """線上查詢（會阻塞，請在執行緒裡呼叫）。連不上會丟出例外，由呼叫的人決定怎麼處理。"""
    req = urllib.request.Request(f"https://ipinfo.io/{ip}/json", headers={"Accept": "application/json", "User-Agent": "NetSonar"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse(json.loads(r.read(100_000).decode("utf-8", "replace")))


def describe_local(kind: str) -> dict:
    return {"kind": kind, "org": None, "lat": None, "lon": None,
            "place": "你家（或公司）的內部網路" if kind == "private" else "網路公司的內部網路"}
