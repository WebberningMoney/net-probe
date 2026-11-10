import os, sys
from pathlib import Path
# 測試時不要自動建立正式的 app / 資料庫檔
os.environ["NETPROBE_NO_AUTOAPP"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
import tempfile
os.environ.setdefault("NETPROBE_SETTINGS", str(Path(tempfile.mkdtemp()) / "settings.json"))
