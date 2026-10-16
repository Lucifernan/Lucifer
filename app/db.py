"""SQLite 数据层：建表、查询、去重插入。"""
import sqlite3
import threading
from datetime import datetime

from .config import DATA_DIR

DB_PATH = DATA_DIR / "app.db"
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'notice',
  title TEXT NOT NULL,
  content TEXT DEFAULT '',
  url TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  dedupe_key TEXT UNIQUE,
  is_read INTEGER DEFAULT 0,
  is_new INTEGER DEFAULT 1,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS courses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  course_name TEXT NOT NULL,
  teacher TEXT DEFAULT '',
  course_id TEXT DEFAULT '',
  clazz_id TEXT DEFAULT '',
  url TEXT DEFAULT '',
  extra TEXT DEFAULT '',
  updated_at TEXT,
  UNIQUE(source, course_name, course_id)
);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  course_name TEXT DEFAULT '',
  title TEXT NOT NULL,
  file_type TEXT DEFAULT '',
  url TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  dedupe_key TEXT UNIQUE,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS sync_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,
  status TEXT,
  detail TEXT,
  created_at TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 旧版本遗留的教务数据表/记录：功能已下线，整表清掉
    for tbl in ("schedule", "grades", "exams"):
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        except Exception:
            pass
    try:
        conn.execute("DELETE FROM notices WHERE source = 'jwglxt'")
    except Exception:
        pass
    conn.commit()


def query(sql: str, args=()) -> list:
    cur = get_conn().execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def one(sql: str, args=()):
    cur = get_conn().execute(sql, args)
    row = cur.fetchone()
    return dict(row) if row else None


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def insert_new(table: str, data: dict) -> bool:
    """带 UNIQUE(dedupe_key) 的表：新数据返回 True。"""
    keys = ", ".join(data.keys())
    marks = ", ".join(["?"] * len(data))
    try:
        cur = get_conn().execute(
            f"INSERT OR IGNORE INTO {table}({keys}) VALUES({marks})",
            list(data.values()),
        )
        get_conn().commit()
        return cur.rowcount > 0
    except Exception:
        return False


def log_sync(source: str, status: str, detail: str = ""):
    get_conn().execute(
        "INSERT INTO sync_log(source,status,detail,created_at) VALUES(?,?,?,?)",
        (source, status, detail[:2000], now()),
    )
    get_conn().commit()
