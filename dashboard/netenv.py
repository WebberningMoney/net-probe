"""netenv.py —— 偵測「目前的網路環境」：連線類型、IP、DNS、VPN、Wi-Fi 訊號。

資料來源（皆為 macOS 內建、唯讀、不需要 sudo；格式已用作者 Mac 的真實輸出驗證）：
  netstat -rn -f inet        預設路由 → 實體路由器、是否走 VPN（見 gateway.py）
  scutil --nwi               各介面的 IP
  scutil --dns               DNS 伺服器
  scutil --proxy             Proxy 設定
  networksetup -listallhardwareports   介面名稱 → 類型（Wi-Fi／USB 網卡…）
  system_profiler SPAirPortDataType    Wi-Fi 頻道、訊號、速率（較慢，約 7 秒）
⚠️ macOS 會把 Wi-Fi 網路名稱（SSID）遮成 <redacted>，所以讀不到；有讀到才顯示。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.request
from typing import Optional

import gateway


# ----------------------------------------------------------------- 解析器（純函式，可用假資料測試）
def parse_hardware_ports(text: str) -> dict:
    """`networksetup -listallhardwareports` → {裝置: 類型}，例：{"en0": "Wi-Fi"}。"""
    out, port = {}, None
    for line in text.splitlines():
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and port:
            out[line.split(":", 1)[1].strip()] = port
            port = None
    return out


def parse_nwi(text: str) -> dict:
    """`scutil --nwi` → {"ipv4": {介面: IP}, "ipv6": {介面: IP}}。"""
    res, section, iface = {"ipv4": {}, "ipv6": {}}, None, None
    for line in text.splitlines():
        if "IPv4 network interface" in line:
            section = "ipv4"
        elif "IPv6 network interface" in line:
            section = "ipv6"
        m = re.match(r"^\s*(\S+)\s*:\s*flags", line)
        if m:
            iface = m.group(1)
        m = re.match(r"^\s*address\s*:\s*(\S+)", line)
        if m and section and iface:
            res[section][iface] = m.group(1)
    return res


def parse_dns(text: str) -> list:
    """`scutil --dns` → 不重複、依出現順序的 DNS 伺服器清單。"""
    seen = []
    for m in re.finditer(r"nameserver\[\d+\]\s*:\s*(\S+)", text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


_PROXY_NAMES = {"HTTPEnable": "HTTP", "HTTPSEnable": "HTTPS", "SOCKSEnable": "SOCKS",
                "ProxyAutoConfigEnable": "自動設定檔(PAC)", "ProxyAutoDiscoveryEnable": "自動偵測(WPAD)",
                "FTPEnable": "FTP"}


def parse_proxy(text: str) -> list:
    """`scutil --proxy` → 已啟用的 Proxy 種類清單（沒有就是空清單）。"""
    on = []
    for key, label in _PROXY_NAMES.items():
        m = re.search(rf"^\s*{key}\s*:\s*(\d+)", text, re.MULTILINE)
        if m and m.group(1) == "1":
            on.append(label)
    return on


def parse_mtu(text: str) -> Optional[int]:
    m = re.search(r"\bmtu\s+(\d+)", text)
    return int(m.group(1)) if m else None


def parse_wifi(text: str) -> Optional[dict]:
    """`system_profiler SPAirPortDataType` → 目前連線的 Wi-Fi 資訊；沒連線回傳 None。"""
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if "Current Network Information:" in l)
    except StopIteration:
        return None
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    info, name = {}, None
    for l in lines[start + 1:]:
        if not l.strip():
            continue
        indent = len(l) - len(l.lstrip())
        if indent <= base_indent:               # 離開這個區塊
            break
        s = l.strip()
        if name is None and s.endswith(":"):    # 第一行是網路名稱（通常是 <redacted>）
            name = s[:-1]
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            info[k.strip()] = v.strip()
    if name is None:
        return None
    out = {"ssid": None if name == "<redacted>" else name, "ssid_hidden_by_os": name == "<redacted>",
           "phy": info.get("PHY Mode"), "security": info.get("Security")}
    m = re.match(r"(\d+)\s*\((\d+)GHz,\s*(\d+)MHz\)", info.get("Channel", ""))
    if m:
        out.update(channel=int(m.group(1)), band=f"{m.group(2)} GHz", width=f"{m.group(3)} MHz")
    m = re.match(r"(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", info.get("Signal / Noise", ""))
    if m:
        out.update(signal_dbm=int(m.group(1)), noise_dbm=int(m.group(2)),
                   snr_db=int(m.group(1)) - int(m.group(2)))
        out["signal_label"] = signal_label(int(m.group(1)))
    m = re.match(r"(\d+)", info.get("Transmit Rate", ""))
    if m:
        out["tx_rate_mbps"] = int(m.group(1))
    return out


def signal_label(dbm: int) -> str:
    """訊號強度白話等級（業界常用的粗略分級，僅供參考）。"""
    if dbm >= -50: return "極佳"
    if dbm >= -60: return "良好"
    if dbm >= -67: return "尚可"
    if dbm >= -72: return "偏弱"
    return "很弱"


def has_global_ipv6(addr: Optional[str]) -> bool:
    return bool(addr) and addr not in ("::1",) and not addr.lower().startswith("fe80")


# ----------------------------------------------------------------- 收集（呼叫系統指令）
async def _run(runner, cmd: list) -> str:
    try:
        code, out = await runner(cmd)
    except OSError:
        return ""
    return out if code == 0 else ""


async def collect_env(runner) -> dict:
    """快速部分（每次 < 1 秒）：連線、IP、DNS、VPN、Proxy。Wi-Fi 另外收集。"""
    gws, nwi, dns, proxy, ports = await asyncio.gather(
        gateway.get_gateways(runner),
        _run(runner, ["scutil", "--nwi"]), _run(runner, ["scutil", "--dns"]),
        _run(runner, ["scutil", "--proxy"]), _run(runner, ["networksetup", "-listallhardwareports"]))
    nwi_d, ports_d = parse_nwi(nwi), parse_hardware_ports(ports)
    phys, vpn = gws["physical"], gws["vpn"]
    iface = phys["iface"] if phys else None
    mtu = parse_mtu(await _run(runner, ["ifconfig", iface])) if iface else None
    return {
        "ts": int(time.time()),
        "interface": iface,
        "interface_type": ports_d.get(iface, iface) if iface else None,
        "local_ip": nwi_d["ipv4"].get(iface) if iface else None,
        "gateway": phys["gateway"] if phys else None,
        "mtu": mtu,
        "vpn": {"active": bool(vpn), "interface": vpn["iface"] if vpn else None,
                "local_ip": nwi_d["ipv4"].get(vpn["iface"]) if vpn else None},
        "dns": parse_dns(dns),
        "proxy": parse_proxy(proxy),
        "ipv6": has_global_ipv6(nwi_d["ipv6"].get(iface)) if iface else False,
        "ipv6_via_vpn_only": bool(vpn) and not has_global_ipv6(nwi_d["ipv6"].get(iface)),
    }


async def collect_wifi(runner) -> Optional[dict]:
    """慢速部分（作者的 Mac 實測約 6.7 秒）：Wi-Fi 頻道/訊號/速率。"""
    return parse_wifi(await _run(runner, ["system_profiler", "SPAirPortDataType"]))


def lookup_public(timeout: float = 5.0) -> Optional[dict]:
    """查「對外 IP 與 ISP」（沿用 Bash 版的 ipinfo.io）。⚠️ 會對第三方發出一次請求，可在設定關閉。"""
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return {"ip": d.get("ip"), "org": re.sub(r"^AS\d+\s+", "", d.get("org", "")) or None}
    except Exception:
        return None


# ----------------------------------------------------------------- 變更偵測（用來在圖上標事件）
def fingerprint(env: dict, wifi: Optional[dict]) -> dict:
    return {"interface": env.get("interface"), "type": env.get("interface_type"),
            "ip": env.get("local_ip"), "gateway": env.get("gateway"),
            "vpn": env["vpn"]["active"],
            "channel": (wifi or {}).get("channel")}


def describe_changes(old: Optional[dict], new: dict) -> list:
    """比較前後兩次的網路環境，回傳白話事件清單（第一次偵測不產生事件）。"""
    if old is None:
        return []
    ev = []
    if old["vpn"] != new["vpn"]:
        ev.append("VPN 已連線" if new["vpn"] else "VPN 已中斷")
    if old["interface"] != new["interface"]:
        ev.append(f"網路介面改為 {new['type'] or new['interface'] or '（無連線）'}")
    elif old["gateway"] != new["gateway"] and new["gateway"]:
        ev.append("路由器位址改變（可能換了 Wi-Fi 或網路）")
    elif old["ip"] != new["ip"] and new["ip"]:
        ev.append("本機 IP 改變")
    if old["channel"] != new["channel"] and old["channel"] and new["channel"]:
        ev.append(f"Wi-Fi 頻道 {old['channel']} → {new['channel']}")
    return ev
