"""storage.py —— 把量測結果存進資料庫（SQLite，就是電腦裡的一個資料檔），以及讀出來。

存了哪些東西、存多久：
  • samples     每秒的原始量測結果，保留 24 小時
  • minute_agg  每分鐘的平均（平均、慢的時候、丟包），保留 90 天
  • reports     定時測試報告，一直保留到你在網頁上刪除
💡 為什麼要每分鐘平均一次？一天有 86,400 秒；看 7 天趨勢時，
   讀「每分鐘一筆」比讀「每秒一筆」快很多，也省空間。
"""
from __future__ import annotations

import json
import sqlite3
import threading

import stats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
  ts INTEGER NOT NULL,          -- Unix 秒
  target TEXT NOT NULL,
  rtt REAL                      -- 毫秒；NULL = 丟包
);
CREATE INDEX IF NOT EXISTS idx_samples ON samples(target, ts);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started INTEGER, finished INTEGER, label TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS minute_agg (
  minute INTEGER NOT NULL,      -- 該分鐘起點（Unix 秒，60 的倍數）
  target TEXT NOT NULL,
  count INTEGER, lost INTEGER, avg REAL, min REAL, max REAL,
  p50 REAL, p95 REAL, jitter REAL,
  PRIMARY KEY (target, minute)
);
"""


class Storage:
    def __init__(self, path: str = "netprobe.db"):
        # 🔰 check_same_thread=False：允許不同執行緒共用連線，再用鎖(lock)避免同時寫入打架。
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            # WAL：寫入不會擋住讀取、也少很多次磁碟同步，目標變多時比較不容易卡；
            # synchronous=NORMAL：當機最壞只會掉最後幾秒資料（監測資料可接受）。
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA)

    def add_samples(self, ts: int, results: dict) -> None:
        """results = {目標名稱: 毫秒或 None}"""
        rows = [(ts, name, rtt) for name, rtt in results.items()]
        with self._lock:
            self._db.executemany("INSERT INTO samples VALUES (?,?,?)", rows)
            self._db.commit()

    # ---- 定時測試報告（保存下來，之後可並排比較不同條件的結果）----
    def save_report(self, started: int, finished: int, label: str, data: dict) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO reports(started, finished, label, data) VALUES (?,?,?,?)",
                                   (started, finished, label, json.dumps(data, ensure_ascii=False)))
            self._db.commit()
            return cur.lastrowid

    def list_reports(self, limit: int = 100) -> list:
        with self._lock:
            rows = self._db.execute("SELECT id, started, finished, label, data FROM reports "
                                    "ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": i, "started": s, "finished": f, "label": l, "data": json.loads(d)} for i, s, f, l, d in rows]

    def get_report(self, rid: int):
        with self._lock:
            r = self._db.execute("SELECT id, started, finished, label, data FROM reports WHERE id=?", (rid,)).fetchone()
        return {"id": r[0], "started": r[1], "finished": r[2], "label": r[3], "data": json.loads(r[4])} if r else None

    def rename_report(self, rid: int, label: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE reports SET label=? WHERE id=?", (label, rid))
            self._db.commit()
            return cur.rowcount > 0

    def delete_report(self, rid: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM reports WHERE id=?", (rid,))
            self._db.commit()
            return cur.rowcount > 0

    def add_rows(self, rows: list) -> None:
        """rows = [(ts, 目標名稱, 毫秒或 None), ...]：一次寫入、一次 commit。"""
        with self._lock:
            self._db.executemany("INSERT INTO samples VALUES (?,?,?)", rows)
            self._db.commit()

    def recent_rtts(self, target: str, since_ts: int) -> list:
        """某目標自 since_ts 起的原始樣本（依時間排序）。"""
        with self._lock:
            cur = self._db.execute(
                "SELECT rtt FROM samples WHERE target=? AND ts>=? ORDER BY ts",
                (target, since_ts))
            return [r[0] for r in cur.fetchall()]

    def rollup(self, now_ts: int) -> int:
        """把「已結束的分鐘」彙總進 minute_agg，回傳新增筆數。可重複呼叫（不會重複寫入）。"""
        cutoff = now_ts - now_ts % 60          # 目前這分鐘還沒結束，不彙總
        added = 0
        with self._lock:
            cur = self._db.execute(
                """SELECT DISTINCT target, ts - ts % 60 AS m FROM samples
                   WHERE ts < ? AND NOT EXISTS (
                     SELECT 1 FROM minute_agg a
                     WHERE a.target = samples.target AND a.minute = samples.ts - samples.ts % 60)""",
                (cutoff,))
            todo = cur.fetchall()
            for target, m in todo:
                rtts = [r[0] for r in self._db.execute(
                    "SELECT rtt FROM samples WHERE target=? AND ts>=? AND ts<? ORDER BY ts",
                    (target, m, m + 60))]
                s = stats.summarize(rtts)
                self._db.execute(
                    "INSERT OR REPLACE INTO minute_agg VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m, target, s["count"], s["lost"], s["avg"], s["min"], s["max"],
                     s["p50"], s["p95"], s["jitter"]))
                added += 1
            self._db.commit()
        return added

    def purge(self, now_ts: int, raw_hours: int = 24, minute_days: int = 90) -> None:
        """刪除過期資料。⚠️ 先 rollup 再 purge，才不會把還沒彙總的資料刪掉。"""
        with self._lock:
            self._db.execute("DELETE FROM samples WHERE ts < ?", (now_ts - raw_hours * 3600,))
            self._db.execute("DELETE FROM minute_agg WHERE minute < ?", (now_ts - minute_days * 86400,))
            self._db.commit()

    def minute_series(self, target: str, since_ts: int) -> list:
        """每分鐘彙總序列（給長時間趨勢圖用），回傳 dict 清單。"""
        with self._lock:
            cur = self._db.execute(
                "SELECT minute,count,lost,avg,min,max,p50,p95,jitter FROM minute_agg "
                "WHERE target=? AND minute>=? ORDER BY minute", (target, since_ts))
            keys = ["minute", "count", "lost", "avg", "min", "max", "p50", "p95", "jitter"]
            return [dict(zip(keys, r)) for r in cur.fetchall()]

    def raw_series(self, target: str, since_ts: int, bucket_sec: int) -> list:
        """原始資料依 bucket_sec 秒分桶：每桶 avg/max/loss%（圖表用，避免一次送出數千點）。"""
        with self._lock:
            rows = self._db.execute(
                "SELECT (ts/?)*? AS b, COUNT(*), SUM(rtt IS NULL), AVG(rtt), MAX(rtt) "
                "FROM samples WHERE target=? AND ts>=? GROUP BY b ORDER BY b",
                (bucket_sec, bucket_sec, target, since_ts)).fetchall()
        return [{"ts": b, "count": n, "loss_pct": round(l / n * 100, 1),
                 "avg": None if a is None else round(a, 1), "max": m} for b, n, l, a, m in rows]

    def raw_rows(self, target: str, since_ts: int) -> list:
        with self._lock:
            return self._db.execute("SELECT ts, rtt FROM samples WHERE target=? AND ts>=? ORDER BY ts",
                                    (target, since_ts)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._db.close()
