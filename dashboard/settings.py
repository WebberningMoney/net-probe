"""settings.py —— 「設定」頁的後端：檢查你輸入的值、存起來、跟預設值合併。

💡 設計：程式附帶的預設值在 config.json；你在網頁上改的部分另外存在 settings.json，
   啟動時「蓋」在預設值上面。好處：更新程式不會蓋掉你的設定；按「恢復預設」只要刪掉 settings.json。
   「匯出設定」就是把目前生效的設定存成檔案；「匯入設定」把檔案內容送回來，同樣要通過下面 validate 的檢查。
   settings.json 放在哪：用終端機啟動時在 dashboard/ 資料夾；用「安裝.command」安裝時在
   ~/Library/Application Support/NetSonar/data/。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import traceroute as tr

EDITABLE = ("targets", "interval_sec", "ping_timeout_sec", "gateway", "alerts", "public_ip_lookup", "wifi_refresh_sec", "curl_test")
_NAME_BAD = re.compile(r"[\x00-\x1f<>&\"']")


class SettingsError(ValueError):
    pass


def _num(v, lo, hi, label, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SettingsError(f"{label} 必須是數字")
    if not lo <= v <= hi:
        raise SettingsError(f"{label} 必須在 {lo}–{hi} 之間")
    return int(v) if integer else float(v)


def validate(body: dict, router_name_default: str = "路由器") -> dict:
    """檢查使用者送來的設定，回傳「乾淨」的設定；有問題丟 SettingsError（訊息是給使用者看的白話）。"""
    out = {}
    targets = body.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 8:
        raise SettingsError("監測目標要有 1–8 個")
    seen, clean = set(), []
    for t in targets:
        name = str(t.get("name", "")).strip() if isinstance(t, dict) else ""
        host = str(t.get("host", "")).strip() if isinstance(t, dict) else ""
        if not 1 <= len(name) <= 20 or _NAME_BAD.search(name):
            raise SettingsError(f"目標名稱「{name}」不正確（1–20 字，不可含特殊符號）")
        if not tr.valid_target(host):
            raise SettingsError(f"目標位址「{host}」不正確（只接受網址或 IP）")
        if name in seen:
            raise SettingsError(f"目標名稱「{name}」重複了")
        seen.add(name)
        item = {"name": name, "host": host}
        p = t.get("p95_ms")                      # 這個目標專屬的 p95 警示門檻（空白＝用全域門檻）
        if p not in (None, ""):
            item["p95_ms"] = _num(p, 10, 5000, f"「{name}」的 p95 門檻（毫秒）")
        if t.get("mute"):                        # 不對這個目標發延遲／丟包警示
            item["mute"] = True
        clean.append(item)
    out["targets"] = clean
    out["interval_sec"] = _num(body.get("interval_sec", 1.0), 0.5, 10, "測量間隔（秒）")
    out["ping_timeout_sec"] = _num(body.get("ping_timeout_sec", 1), 1, 5, "逾時（秒）", integer=True)
    gw = body.get("gateway") or {}
    gname = str(gw.get("name", router_name_default)).strip() or router_name_default
    if len(gname) > 20 or _NAME_BAD.search(gname) or gname in seen:
        raise SettingsError("路由器名稱不正確或與目標重複")
    out["gateway"] = {"enabled": bool(gw.get("enabled", True)), "name": gname}
    a = body.get("alerts") or {}
    out["alerts"] = {
        "enabled": bool(a.get("enabled", True)),
        "macos_notification": bool(a.get("macos_notification", True)),
        "cooldown_sec": _num(a.get("cooldown_sec", 300), 10, 3600, "冷卻時間（秒）", integer=True),
        "loss_pct_1m": _num(a.get("loss_pct_1m", 10), 1, 100, "丟包門檻（%）"),
        "p95_ms_1m": _num(a.get("p95_ms_1m", 150), 10, 5000, "p95 門檻（ms）"),
        "consecutive_timeouts": _num(a.get("consecutive_timeouts", 5), 2, 120, "連續逾時次數", integer=True)}
    out["public_ip_lookup"] = bool(body.get("public_ip_lookup", True))
    out["wifi_refresh_sec"] = 0 if not body.get("wifi_refresh_sec") else _num(body["wifi_refresh_sec"], 60, 3600, "Wi-Fi 資訊更新間隔（秒）", integer=True)
    url = str((body.get("curl_test") or {}).get("url", "")).strip()
    if url:
        if not re.match(r"^https://[^\s]+$", url) or "{bytes}" not in url:
            raise SettingsError("下載測試網址必須以 https:// 開頭，並包含 {bytes}")
        out["curl_test"] = {"url": url}
    return out


def load_overrides(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k in EDITABLE} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def merge(base: dict, overrides: dict) -> dict:
    return {**base, **overrides}


def save_overrides(path: Path, clean: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)                                   # 先寫暫存檔再改名，避免寫到一半當機留下壞檔


def reset(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
