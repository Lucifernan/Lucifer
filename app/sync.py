"""同步编排：调用爬虫 -> 入库 -> 识别新增 -> 桌面提醒。"""
from datetime import datetime

from . import config, db
from .crawlers import chaoxing as cx
from .crawlers import zhihuishu as zhs
from .notifier import enabled, notify


def _summary_add(summary, source, key, n):
    summary.setdefault(source, {})
    summary[source][key] = summary[source].get(key, 0) + n


def run_sync(with_files: bool = True) -> dict:
    summary: dict = {"errors": []}
    has_cookie = False

    # ---------------- 超星 ----------------
    if config.get("chaoxing_cookie"):
        has_cookie = True
        try:
            courses = cx.fetch_courses()
            for c in courses:
                db.insert_new(
                    "courses",
                    {
                        "source": "chaoxing",
                        "course_name": c["course_name"],
                        "teacher": c.get("teacher", ""),
                        "course_id": c.get("course_id", ""),
                        "clazz_id": c.get("clazz_id", ""),
                        "url": c.get("url", ""),
                        "updated_at": db.now(),
                    },
                )
            _summary_add(summary, "chaoxing", "courses", len(courses))
            db.log_sync("chaoxing", "ok", f"课程 {len(courses)} 门")
        except Exception as e:
            summary["errors"].append(f"超星课程: {e}")
            db.log_sync("chaoxing", "error", str(e))

        try:
            items = cx.fetch_interaction()
            new_titles = []
            for it in items:
                if db.insert_new(
                    "notices",
                    {
                        "source": "chaoxing",
                        "kind": it.get("kind", "notice"),
                        "title": it["title"],
                        "content": it.get("content", ""),
                        "url": it.get("url", ""),
                        "published_at": it.get("published_at", ""),
                        "dedupe_key": f"cx::{it['title']}::{it.get('url', '')}",
                        "fetched_at": db.now(),
                    },
                ):
                    new_titles.append(it["title"])
            _summary_add(summary, "chaoxing", "notices", len(new_titles))
            db.log_sync("chaoxing", "ok", f"互动消息 {len(items)} 条，新增 {len(new_titles)}")
            if new_titles and enabled("notice"):
                notify(
                    f"超星新消息 x{len(new_titles)}",
                    "\n".join(new_titles[:3]) + ("\n..." if len(new_titles) > 3 else ""),
                )
        except Exception as e:
            summary["errors"].append(f"超星互动: {e}")
            db.log_sync("chaoxing", "error", str(e))

        if with_files and config.get("chaoxing_fetch_files"):
            try:
                files = cx.fetch_files()
                n = 0
                for f in files:
                    if db.insert_new(
                        "files",
                        {
                            "source": "chaoxing",
                            "course_name": f.get("course_name", ""),
                            "title": f["title"],
                            "file_type": f.get("file_type", ""),
                            "url": f.get("url", ""),
                            "fetched_at": db.now(),
                            "dedupe_key": f"cx::file::{f.get('objectid', f['title'])}",
                        },
                    ):
                        n += 1
                _summary_add(summary, "chaoxing", "files", n)
                if files:
                    db.log_sync("chaoxing", "ok", f"文件 {len(files)} 个，新增 {n}")
            except Exception as e:
                summary["errors"].append(f"超星文件: {e}")
                db.log_sync("chaoxing", "error", str(e))

    # ---------------- 智慧树（知到） ----------------
    if config.get("zhihuishu_cookie"):
        has_cookie = True
        try:
            items = zhs.fetch_notices()
            new_titles = []
            for it in items:
                if db.insert_new(
                    "notices",
                    {**it, "fetched_at": db.now()},
                ):
                    new_titles.append(it["title"])
            _summary_add(summary, "zhihuishu", "notices", len(new_titles))
            db.log_sync("zhihuishu", "ok", f"通知 {len(items)} 条，新增 {len(new_titles)}")
            if new_titles and enabled("notice"):
                notify(
                    f"知到新通知 x{len(new_titles)}",
                    "\n".join(new_titles[:3]) + ("\n..." if len(new_titles) > 3 else ""),
                )
        except Exception as e:
            summary["errors"].append(f"智慧树: {e}")
            db.log_sync("zhihuishu", "error", str(e))

    summary["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not has_cookie:
        summary.setdefault("errors", []).append("未配置 Cookie，请到设置页填写后重试")
    return summary
