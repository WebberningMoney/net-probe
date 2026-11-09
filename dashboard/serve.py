"""serve.py —— 啟動儀表板伺服器（run_dashboard.sh 呼叫這支）。

為什麼不直接用 `uvicorn app:app`？為了讓 Ctrl+C 能「立刻、乾淨」地結束：
收到結束信號時，先通知網頁串流（SSE）收工，再讓 uvicorn 正常關閉。
"""
import json
from pathlib import Path

import uvicorn

import app as appmod


class Server(uvicorn.Server):
    def handle_exit(self, sig, frame):
        appmod.app.state.engine.stop_streams()
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    cfg = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    config = uvicorn.Config(appmod.app, host="127.0.0.1", port=cfg["port"],
                            log_level="warning",
                            timeout_graceful_shutdown=3)   # 保險：最多再等 3 秒就強制收尾
    try:
        Server(config).run()
    except KeyboardInterrupt:
        # 🔰 uvicorn 乾淨關閉後會把 Ctrl+C 再丟出來一次；這裡接住，避免印出一大串錯誤訊息。
        pass
    print("👋 儀表板已結束")
