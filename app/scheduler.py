"""定时任务：周期同步、每日/每周学习简报。"""
import re
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db
from .notifier import enabled, notify
from .sync import run_sync

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

_SRC = {"chaoxing": "超星", "zhihuishu": "智慧树"}
_WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_DATE_RE = re.compile(r"(20\d{2}[-/年.]\s?\d{1,2}[-/月.]\s?\d{1,2}日?|\d{1,2}月\d{1,2}日)")
_URGENT_RE = re.compile(r"截止|逾期|最晚|之前|前交|限时|今晚|明天|后天|本周|即将")


def _label(src: str) -> str:
    return _SRC.get(src, src or "")


def _extract_date(text: str) -> str:
    """从文本中提取日期，统一为 YYYY-MM-DD；提不出返回空。"""
    m = _DATE_RE.search(text or "")
    if not m:
        return ""
    d = m.group(1)
    d = re.sub(r"[\s年月]", "-", d).replace("/", "-").replace(".", "-").replace("日", "")
    parts = d.split("-")
    if len(parts) == 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            return ""
    return ""


def _focus_rows(start: str) -> list:
    """扫描重点通知（作业/考试类，或标题内容含截止语），按日期排序取前 5。"""
    rows = db.query(
        "SELECT title, content, source, kind, published_at FROM notices "
        "WHERE fetched_at >= ? ORDER BY fetched_at DESC LIMIT 120",
        (start,),
    )
    out = []
    for r in rows:
        text = f"{r.get('title', '')} {str(r.get('content', ''))[:120]}"
        if r.get("kind") not in ("homework", "exam") and not _URGENT_RE.search(text):
            continue
        when = _extract_date(text) or _extract_date(r.get("published_at") or "")
        line = f"[{_label(r.get('source'))}] {r.get('title', '')[:46]}"
        if when:
            line += f"（{when}）"
        out.append((when or "9999", line))
    out.sort()
    return [ln for _, ln in out[:5]]


def build_brief(scope: str = "today") -> dict:
    """生成学习简报。scope: today=每日简报 / week=每周简报。
    返回 {scope, title, date, lines}，lines 为可直接展示的文本行。"""
    today = date.today()
    now = datetime.now()
    unread = db.one("SELECT COUNT(*) c FROM notices WHERE is_read = 0")["c"]
    n_course = db.one("SELECT COUNT(*) c FROM courses")["c"]
    n_file = db.one("SELECT COUNT(*) c FROM files")["c"]
    lines = []

    if scope == "week":
        ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        new_n = db.one(
            "SELECT COUNT(*) c FROM notices WHERE fetched_at >= ?", (ws,)
        )["c"]
        focus = _focus_rows(ws)
        lines.append(f"本周（{ws} ~ {today}）新增通知 {new_n} 条，未读 {unread} 条。")
        if focus:
            lines.append("重点关注：")
            lines.extend(f"· {x}" for x in focus)
        else:
            lines.append("本周暂无作业 / 考试 / 截止类重点消息。")
        lines.append(f"在读课程 {n_course} 门 · 课程文件 {n_file} 个。")
        return {
            "scope": "week",
            "title": "每周学习简报",
            "date": ws,
            "lines": lines,
        }

    d0 = today.strftime("%Y-%m-%d")
    new_n = db.one("SELECT COUNT(*) c FROM notices WHERE fetched_at >= ?", (d0,))["c"]
    # 重点扫描回看昨天，捕捉“今晚截止”这类跨日消息
    focus = _focus_rows((today - timedelta(days=1)).strftime("%Y-%m-%d"))
    lines.append(
        f"今天 {now.strftime('%m月%d日')}（{_WEEK_CN[today.weekday()]}）："
        f"新增通知 {new_n} 条，未读 {unread} 条。"
    )
    if focus:
        lines.append("重点关注：")
        lines.extend(f"· {x}" for x in focus)
    else:
        lines.append("暂无作业 / 考试类重点消息。")
    lines.append(f"在读课程 {n_course} 门 · 课程文件 {n_file} 个。")
    return {"scope": "today", "title": "每日学习简报", "date": d0, "lines": lines}


def _brief_text(scope: str) -> tuple:
    b = build_brief(scope)
    return b["title"], "\n".join(b["lines"])


def daily_digest():
    """每日简报推送。"""
    if not enabled("digest"):
        return
    title, text = _brief_text("today")
    notify(title, text)


def weekly_digest():
    """每周简报推送（每周一与每日简报同时段）。"""
    if not enabled("weekly"):
        return
    title, text = _brief_text("week")
    notify(title, text)


def _sync_job():
    try:
        run_sync(with_files=True)
    except Exception as e:
        print(f"[同步失败] {e}", flush=True)


def _digest_times() -> tuple:
    try:
        hh, mm = str(config.get("daily_digest_time") or "08:00").split(":")
        return int(hh), int(mm)
    except Exception:
        return 8, 0


def start():
    if scheduler.running:
        return
    try:
        interval = max(5, int(config.get("sync_interval_minutes") or 30))
    except ValueError:
        interval = 30
    scheduler.add_job(_sync_job, "interval", minutes=interval, id="sync", replace_existing=True)
    hh, mm = _digest_times()
    scheduler.add_job(
        daily_digest, "cron", hour=hh, minute=mm, id="digest", replace_existing=True
    )
    # 每周一同一时刻推送每周简报
    scheduler.add_job(
        weekly_digest, "cron", day_of_week="mon", hour=hh, minute=mm,
        id="weekly", replace_existing=True,
    )
    scheduler.start()


def restart_sync_job():
    if not scheduler.running:
        return start()
    try:
        interval = max(5, int(config.get("sync_interval_minutes") or 30))
    except ValueError:
        interval = 30
    scheduler.add_job(_sync_job, "interval", minutes=interval, id="sync", replace_existing=True)
    hh, mm = _digest_times()
    scheduler.add_job(
        daily_digest, "cron", hour=hh, minute=mm, id="digest", replace_existing=True
    )
    scheduler.add_job(
        weekly_digest, "cron", day_of_week="mon", hour=hh, minute=mm,
        id="weekly", replace_existing=True,
    )
