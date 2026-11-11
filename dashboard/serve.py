"""serve.py —— 啟動儀表板的網頁伺服器。

誰會執行它：run_dashboard.sh（終端機啟動）、或「安裝.command」裝好的背景服務（開機自動啟動）。
為什麼不直接用 `uvicorn app:app` 指令？為了按 Ctrl+C 時能「立刻、乾淨」地結束：
先通知網頁的即時連線收工，再關閉伺服器。
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
