"""学习问答：纯本地智能问答，零 API Key、零外呼。

基于已采集的通知/课程/文件数据做意图识别 + 关键词检索作答，
所有数据保存在本地 SQLite，隐私数据不会离开本机。
"""
import re

from . import db

_SRC = {"chaoxing": "超星", "zhihuishu": "智慧树"}


def _label(src: str) -> str:
    return _SRC.get(src, src or "未知")


def _notice_line(r) -> str:
    """通知回答行：来源平台 + 标题 + 发布时间 + 原文链接（前端自动可点）。"""
    parts = [f"[{_label(r.get('source'))}]"]
    parts.append(r.get("title") or "")
    when = r.get("published_at") or r.get("fetched_at") or ""
    if when:
        parts.append(f"发布 {when[:10]}")
    url = r.get("url") or ""
    if url:
        parts.append(url)
    return "- " + " · ".join(str(p) for p in parts if p)


def _keyword_hits(query: str) -> list:
    """中文 bigram 检索：在通知/文件/课程标题中找相关条目。"""
    text = re.sub(r"[^一-龥A-Za-z0-9]", "", query or "")
    if len(text) < 2:
        return []
    terms = set()
    for n in (4, 3, 2):
        for i in range(len(text) - n + 1):
            terms.add(text[i : i + n])
    if not terms:
        return []
    hits, seen = [], set()
    for table, title_col in (
        ("notices", "title"),
        ("files", "title"),
        ("courses", "course_name"),
    ):
        for term in list(terms)[:30]:
            try:
                rows = db.query(
                    f"SELECT * FROM {table} WHERE {title_col} LIKE ? LIMIT 5",
                    (f"%{term}%",),
                )
            except Exception:
                rows = []
            for r in rows:
                key = f"{table}:{r.get(title_col)}"
                if key in seen:
                    continue
                seen.add(key)
                if table == "notices":
                    hits.append(_notice_line(r))
                elif table == "files":
                    hits.append(f"[文件] {r.get('course_name','')}: {r['title']}"
                                + (f" {r['url']}" if r.get("url") else ""))
                elif table == "courses":
                    line = f"[课程] ({_label(r.get('source'))}) {r['course_name']}"
                    if r.get("teacher"):
                        line += f" · {r['teacher']}"
                    hits.append(line)
                if len(hits) >= 15:
                    return hits
    return hits


def _save(role: str, content: str):
    db.get_conn().execute(
        "INSERT INTO chat_history(role, content, created_at) VALUES(?,?,?)",
        (role, content, db.now()),
    )
    db.get_conn().commit()


def _overview() -> str:
    n_notice = db.one("SELECT COUNT(*) c FROM notices")["c"]
    n_course = db.one("SELECT COUNT(*) c FROM courses")["c"]
    n_file = db.one("SELECT COUNT(*) c FROM files")["c"]
    n_unread = db.one("SELECT COUNT(*) c FROM notices WHERE is_read = 0")["c"]
    latest = db.query("SELECT * FROM notices ORDER BY fetched_at DESC LIMIT 3")
    out = [
        f"已为你采集：通知 {n_notice} 条（未读 {n_unread}）、课程 {n_course} 门、文件 {n_file} 个。",
        "",
        "最新通知：",
    ]
    out += [_notice_line(n) for n in latest] or ["- 暂无"]
    out += [
        "",
        "可以这样问我：「有什么新通知」「我有哪些课程」「有哪些课程文件」「今日简报」「本周有什么要关注的」，"
        "也可以直接输入关键词（如课程名、作业、考试）检索相关内容。",
    ]
    return "\n".join(out)


def _brief_answer(q: str) -> str:
    """简报意图：返回每日 / 每周学习简报。"""
    from .scheduler import build_brief

    scope = "week" if re.search(r"本周|每周|周报|这周", q) else "today"
    b = build_brief(scope)
    return b["title"] + f"（{b['date']}）\n" + "\n".join(b["lines"])


def _local_answer(message: str) -> str:
    """本地智能问答：意图识别 + 关键词检索，直接基于已采集数据作答。"""
    q = re.sub(r"[\s，。？?！!、]+", "", message or "")

    # 意图：简报 / 本周关注
    if re.search(r"简报|今天有什么|今日安排|本周|周报|每周|要关注|重点", q):
        return _brief_answer(q)

    # 意图：通知
    if re.search(r"通知|公告|消息|动态|新闻|提醒", q):
        rows = db.query(
            "SELECT * FROM notices ORDER BY is_new DESC, fetched_at DESC LIMIT 8"
        )
        if not rows:
            return "暂时没有采集到新通知，先到仪表盘点「立即同步」试试。"
        return "最近的通知（可点击“发布 xx”后的链接查看原文）：\n" + "\n".join(
            _notice_line(r) for r in rows
        )

    # 意图：课程
    if re.search(r"课程|上课|开了什么课|选了什么课|课表|教室", q):
        rows = db.query("SELECT * FROM courses ORDER BY source, course_name")
        if not rows:
            return "还没有采集到课程，先到仪表盘点「立即同步」试试。"
        lines = [
            f"- ({_label(r['source'])}) {r['course_name']}"
            + (f" · {r['teacher']}" if r.get("teacher") else "")
            + (f" {r['url']}" if r.get("url") else "")
            for r in rows
        ]
        return f"已采集到 {len(rows)} 门课程：\n" + "\n".join(lines)

    # 意图：文件
    if re.search(r"文件|课件|资料|讲义|下载", q):
        rows = db.query(
            "SELECT * FROM files ORDER BY id DESC LIMIT 10"
        )
        if not rows:
            return "暂时没有采集到课程文件。"
        lines = [
            f"- {r['course_name']}: {r['title']}（{r['file_type']}）"
            + (f" {r['url']}" if r.get("url") else "")
            for r in rows
        ]
        return "最近的课程文件：\n" + "\n".join(lines)

    # 意图：未读
    if re.search(r"未读|没看|未查看", q):
        rows = db.query(
            "SELECT * FROM notices WHERE is_read = 0 ORDER BY fetched_at DESC LIMIT 8"
        )
        if not rows:
            return "目前没有未读通知，消息都看完了。"
        return f"你有 {len(rows)} 条未读通知：\n" + "\n".join(
            _notice_line(r) for r in rows
        )

    # 关键词检索：有命中就列相关条目
    hits = _keyword_hits(message)
    if hits:
        return "在已采集的数据里找到这些相关内容：\n" + "\n".join(f"- {h}" for h in hits)

    # 兜底总览
    return _overview()


def ask(message: str) -> str:
    _save("user", message)
    answer = _local_answer(message)
    _save("assistant", answer)
    return answer
