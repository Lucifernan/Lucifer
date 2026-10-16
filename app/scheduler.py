"""定时任务：周期同步、每日简报。"""
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db
from .notifier import enabled, notify
from .sync import run_sync

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def daily_digest():
    """每日简报：未读通知 + 最新动态概览。"""
    if not enabled("digest"):
        return
    unread = db.one("SELECT COUNT(*) c FROM notices WHERE is_read = 0")["c"]
    latest = db.query("SELECT title, source FROM notices ORDER BY fetched_at DESC LIMIT 3")
    files = db.one("SELECT COUNT(*) c FROM files")["c"]
    lines = []
    if unread:
        lines.append(f"未读消息 {unread} 条")
    for n in latest:
        lines.append(f"  [{n['source']}] {n['title'][:40]}")
    lines.append(f"课程文件共 {files} 个")
    if not unread:
        lines.append("暂无未读，一切就绪")
    notify("每日学习简报", "\n".join(lines))


def _sync_job():
    try:
        run_sync(with_files=True)
    except Exception as e:
        print(f"[同步失败] {e}")


def start():
    if scheduler.running:
        return
    try:
        interval = max(5, int(config.get("sync_interval_minutes") or 30))
    except ValueError:
        interval = 30
    scheduler.add_job(_sync_job, "interval", minutes=interval, id="sync", replace_existing=True)
    hh, mm = str(config.get("daily_digest_time") or "08:00").split(":")
    scheduler.add_job(
        daily_digest, "cron", hour=int(hh), minute=int(mm), id="digest", replace_existing=True
    )
    scheduler.start()


def restart_sync_job():
    try:
        interval = max(5, int(config.get("sync_interval_minutes") or 30))
    except ValueError:
        interval = 30
    scheduler.add_job(_sync_job, "interval", minutes=interval, id="sync", replace_existing=True)
