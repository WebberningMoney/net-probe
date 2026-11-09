"""probe.py —— 實際去 ping（呼叫 macOS 內建的 ping 指令）。

💡 為什麼用系統 ping，而不是自己送 ICMP？自己送需要 root 權限；
   系統 ping 不需要，而且 -W/-t 旗標已在作者的 Mac 驗證過。

macOS（BSD）ping 旗標：-n 不做反向 DNS｜-c 1 只送 1 包｜
   -W <毫秒> 等回應多久｜-t <秒> 整個指令最長執行秒數（保險，避免卡住）。
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional

# 🔰 正規表示式：抓出 "time=12.345 ms" 的數字部分。
_TIME_RE = re.compile(r"time[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms")

# Runner：接受指令列表、回傳 (結束碼, 標準輸出)。測試時可換成假的。
Runner = Callable[[list], Awaitable[tuple]]


def parse_ping_output(text: str) -> Optional[float]:
    """從 ping 輸出取出延遲(ms)；找不到回傳 None。"""
    m = _TIME_RE.search(text)
    return float(m.group(1)) if m else None


def build_ping_cmd(host: str, timeout_sec: int = 1) -> list:
    return ["ping", "-n", "-c", "1", "-W", str(timeout_sec * 1000),
            "-t", str(timeout_sec + 1), host]


async def _real_runner(cmd: list) -> tuple:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace")


async def ping_once(host: str, timeout_sec: int = 1,
                    runner: Runner = _real_runner) -> Optional[float]:
    """ping 一次。成功回傳毫秒，逾時/失敗回傳 None。"""
    try:
        code, out = await runner(build_ping_cmd(host, timeout_sec))
    except OSError:   # 例如找不到 ping 指令
        return None
    return parse_ping_output(out) if code == 0 else None
