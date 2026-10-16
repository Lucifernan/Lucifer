"""Web API 路由。"""
import threading

from fastapi import APIRouter, Body, HTTPException

from . import chat, config, db
from .crawlers import chaoxing as cx
from .crawlers import zhihuishu as zhs
from .notifier import notify
from .scheduler import restart_sync_job
from .sync import run_sync

router = APIRouter(prefix="/api")

_sync_state = {"running": False, "last": None}


# ------------------------------------------------------------------ 概览
@router.get("/overview")
def overview():
    unread = db.one("SELECT COUNT(*) c FROM notices WHERE is_read = 0")["c"]
    notices_total = db.one("SELECT COUNT(*) c FROM notices")["c"]
    latest_notices = db.query("SELECT * FROM notices ORDER BY fetched_at DESC LIMIT 8")
    files_total = db.one("SELECT COUNT(*) c FROM files")["c"]
    courses_total = db.one("SELECT COUNT(*) c FROM courses")["c"]
    from datetime import date, datetime, timedelta

    soon = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    new_week = db.one(
        "SELECT COUNT(*) c FROM notices WHERE fetched_at >= ?",
        (date.today().strftime("%Y-%m-%d"),),
    )["c"]
    return {
        "unread": unread,
        "notices_total": notices_total,
        "latest_notices": latest_notices,
        "files_total": files_total,
        "courses_total": courses_total,
        "new_week": new_week,
        "sync_state": _sync_state,
    }


# ------------------------------------------------------------------ 数据查询
@router.get("/notices")
def notices(source: str = "", unread: int = 0, limit: int = 200):
    sql, args = "SELECT * FROM notices WHERE 1=1", []
    if source:
        sql += " AND source = ?"
        args.append(source)
    if unread:
        sql += " AND is_read = 0"
    sql += " ORDER BY fetched_at DESC LIMIT ?"
    args.append(limit)
    return db.query(sql, tuple(args))


@router.post("/notices/read")
def mark_read(payload: dict = Body(...)):
    conn = db.get_conn()
    if payload.get("all"):
        conn.execute("UPDATE notices SET is_read = 1, is_new = 0")
    else:
        ids = payload.get("ids") or []
        if ids:
            conn.execute(
                f"UPDATE notices SET is_read = 1, is_new = 0 WHERE id IN ({','.join('?'*len(ids))})",
                ids,
            )
    conn.commit()
    return {"ok": True}


@router.get("/courses")
def courses():
    return db.query("SELECT * FROM courses ORDER BY source, course_name")


@router.get("/files")
def files(q: str = "", limit: int = 500):
    if q:
        return db.query(
            "SELECT * FROM files WHERE title LIKE ? OR course_name LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (f"%{q}%", f"%{q}%", limit),
        )
    return db.query("SELECT * FROM files ORDER BY id DESC LIMIT ?", (limit,))


# ------------------------------------------------------------------ 同步
def _sync_worker():
    try:
        result = run_sync(with_files=True)
        _sync_state["last"] = result
    except Exception as e:
        _sync_state["last"] = {"errors": [str(e)]}
    finally:
        _sync_state["running"] = False


@router.post("/sync")
def start_sync():
    if _sync_state["running"]:
        return {"started": False, "reason": "正在同步中"}
    _sync_state["running"] = True
    _sync_state["last"] = None
    threading.Thread(target=_sync_worker, daemon=True).start()
    return {"started": True}


@router.get("/sync/status")
def sync_status():
    return _sync_state


@router.get("/sync/log")
def sync_log(limit: int = 30):
    return db.query("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/sync/last-run")
def last_run():
    return db.query("SELECT * FROM sync_log ORDER BY id DESC LIMIT 10")


# ------------------------------------------------------------------ 设置
@router.get("/settings")
def get_settings():
    return config.get()


@router.post("/settings")
def save_settings(payload: dict = Body(...)):
    cfg = config.update(payload)
    restart_sync_job()
    return cfg


# ------------------------------------------------------------------ 连通性 / 提醒测试
@router.post("/ping")
def ping(payload: dict = Body(...)):
    site = payload.get("site")
    try:
        if site == "chaoxing":
            return {"site": site, **cx.ping()}
        if site == "zhihuishu":
            return {"site": site, **zhs.ping()}
        raise HTTPException(400, "site 必须是 chaoxing 或 zhihuishu")
    except HTTPException:
        raise
    except Exception as e:
        return {"site": site, "ok": False, "error": str(e)}


@router.post("/test/notify")
def test_notify():
    ok = notify("学习提醒助手", "这是一条测试提醒，看到即表示通知正常！")
    return {"ok": ok}


# ------------------------------------------------------------------ 问答
@router.post("/chat")
def do_chat(payload: dict = Body(...)):
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message 不能为空")
    reply = chat.ask(message)
    return {"reply": reply}


@router.get("/chat/history")
def chat_history():
    return db.query(
        "SELECT role, content, created_at FROM chat_history ORDER BY id DESC LIMIT 50"
    )[::-1]


@router.delete("/chat/history")
def clear_chat():
    db.get_conn().execute("DELETE FROM chat_history")
    db.get_conn().commit()
    return {"ok": True}
