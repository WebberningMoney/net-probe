"""alerts.py —— 告警規則、冷卻時間、macOS 通知。

規則（門檻在 config.json 的 alerts 調整）：
  timeouts  連續逾時 ≥ N 次（預設 5）            → 可能整條線斷了
  loss      近 60 秒丟包率 ≥ X%（預設 10）       → 連線品質明顯變差
  p95       近 60 秒 p95 延遲 ≥ Y ms（預設 150） → 常有明顯延遲尖峰
冷卻：同一規則 + 同一目標，N 秒內只通知一次（預設 300），避免連續轟炸。
"""
from __future__ import annotations

import subprocess
import sys
import time
from collections import deque
from typing import Callable, Optional

import stats

DEFAULTS = {"enabled": True, "cooldown_sec": 300, "loss_pct_1m": 10.0,
            "p95_ms_1m": 150.0, "consecutive_timeouts": 5, "min_samples": 20, "group_min_targets": 3,
            "macos_notification": True}


def _applescript_quote(s: str) -> str:
    """AppleScript 字串要跳脫反斜線與雙引號（指令是用參數清單傳入，不經過 shell，所以不會有 shell 注入）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_notify(title: str, message: str) -> None:
    """用 osascript 顯示系統通知（右上角通知中心）。非 macOS 只印出文字。"""
    if sys.platform != "darwin":
        print(f"[通知] {title}: {message}")
        return
    script = f"display notification {_applescript_quote(message)} with title {_applescript_quote(title)}"
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class AlertManager:
    def __init__(self, cfg: dict | None = None, router_name: str | None = None,
                 notifier: Optional[Callable[[str, str], None]] = None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.router_name = router_name
        self.notifier = notifier if notifier is not None else (
            macos_notify if self.cfg["macos_notification"] else None)
        self._last: dict = {}                 # (規則, 目標) -> 上次通知時間
        self.history: deque = deque(maxlen=50)

    @staticmethod
    def _trailing_timeouts(samples: list) -> int:
        n = 0
        for x in reversed(samples):
            if x is not None:
                break
            n += 1
        return n

    def evaluate(self, windows: dict, ts: int) -> list:
        """windows = {目標名稱: 最近 60 筆樣本（毫秒或 None）}；回傳這一輪「新觸發」的告警。"""
        c = self.cfg
        if not c["enabled"]:
            return []
        cands = []                            # 這一輪的候選告警：(規則, 目標, 訊息, 嚴重度)
        for name, samples in windows.items():
            who = "路由器" if name == self.router_name else name
            t = self._trailing_timeouts(samples)
            if t >= c["consecutive_timeouts"]:
                hint = "可能是 Wi-Fi 斷線或路由器問題" if name == self.router_name else "網路可能中斷，或該目標暫時不可用"
                cands.append(("timeouts", name, f"{who} 已連續 {t} 秒沒有回應（{hint}）", "critical"))
            if len(samples) >= c["min_samples"]:
                s = stats.summarize(samples)
                if s["loss_pct"] >= c["loss_pct_1m"]:
                    cands.append(("loss", name, f"{who} 近 1 分鐘丟包率 {s['loss_pct']}%", "warning"))
                if s["p95"] is not None and s["p95"] >= c["p95_ms_1m"]:
                    cands.append(("p95", name, f"{who} 近 1 分鐘 p95 延遲 {s['p95']} ms", "warning"))
        # 先濾掉冷卻中的，再依規則分組
        by_rule: dict = {}
        for rule, name, message, severity in cands:
            if ts - self._last.get((rule, name), -10**12) >= c["cooldown_sec"]:
                by_rule.setdefault(rule, []).append((name, message, severity))
        fired = []
        for rule, items in by_rule.items():
            for name, _, _ in items:
                self._last[(rule, name)] = ts
            if len(items) >= c["group_min_targets"]:
                # 💡 多個目標「同時」出問題，幾乎一定是共同原因（本機網路/Wi-Fi），
                #    合併成一則比跳出一排通知更好讀。
                names = "、".join("路由器" if n == self.router_name else n for n, _, _ in items)
                tail = {"timeouts": "同時連續逾時，本機網路可能已中斷（Wi-Fi 斷線？）",
                        "loss": "近 1 分鐘同時丟包，多半是本機網路或 Wi-Fi 的問題",
                        "p95": "近 1 分鐘同時出現延遲尖峰，多半是共同路徑（Wi-Fi／路由器／ISP）的問題"}[rule]
                self._emit(fired, ts, rule, "全部", f"{len(items)} 個目標（{names}）{tail}", items[0][2])
            else:
                for name, message, severity in items:
                    self._emit(fired, ts, rule, name, message, severity)
        return fired

    def _emit(self, out: list, ts: int, rule: str, name: str, message: str, severity: str) -> None:
        alert = {"ts": ts, "rule": rule, "target": name, "severity": severity, "message": message}
        self.history.appendleft(alert)
        out.append(alert)
        if self.notifier:
            self.notifier("net-probe 網路警示", message)
