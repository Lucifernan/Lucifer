"""学习问答：纯本地智能问答，零 API Key、零外呼。

基于已采集的通知/课程/文件数据做意图识别 + 关键词检索作答，
所有数据保存在本地 SQLite，隐私数据不会离开本机。
"""
import re

from . import db


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
                    hits.append(f"[通知] {r['title']} {r.get('published_at','')} {r.get('content','')[:150]}")
                elif table == "files":
                    hits.append(f"[文件] {r.get('course_name','')}: {r['title']}")
                elif table == "courses":
                    hits.append(f"[课程] ({r.get('source','')}) {r['course_name']}")
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
    latest = db.query("SELECT title, source FROM notices ORDER BY fetched_at DESC LIMIT 3")
    out = [
        f"已为你采集：通知 {n_notice} 条（未读 {n_unread}）、课程 {n_course} 门、文件 {n_file} 个。",
        "",
        "最新通知：",
    ]
    out += [f"- [{n['source']}] {n['title']}" for n in latest] or ["- 暂无"]
    out += [
        "",
        "可以这样问我：「有什么新通知」「我有哪些课程」「有哪些课程文件」，"
        "也可以直接输入关键词（如课程名、作业、考试）检索相关内容。",
    ]
    return "\n".join(out)


def _local_answer(message: str) -> str:
    """本地智能问答：意图识别 + 关键词检索，直接基于已采集数据作答。"""
    q = re.sub(r"[\s，。？?！!、]+", "", message or "")

    # 意图：通知
    if re.search(r"通知|公告|消息|动态|新闻|提醒", q):
        rows = db.query(
            "SELECT title, source, published_at FROM notices "
            "ORDER BY is_new DESC, fetched_at DESC LIMIT 8"
        )
        if not rows:
            return "暂时没有采集到新通知，先到仪表盘点「立即同步」试试。"
        lines = [f"- ({r['source']}) {r['title']} {r['published_at']}" for r in rows]
        return "最近的通知：\n" + "\n".join(lines)

    # 意图：课程
    if re.search(r"课程|上课|开了什么课|选了什么课|课表|教室", q):
        rows = db.query("SELECT course_name, source FROM courses ORDER BY source, course_name")
        if not rows:
            return "还没有采集到课程，先到仪表盘点「立即同步」试试。"
        lines = [f"- ({r['source']}) {r['course_name']}" for r in rows]
        return f"已采集到 {len(rows)} 门课程：\n" + "\n".join(lines)

    # 意图：文件
    if re.search(r"文件|课件|资料|讲义|下载", q):
        rows = db.query(
            "SELECT course_name, title, file_type FROM files ORDER BY id DESC LIMIT 10"
        )
        if not rows:
            return "暂时没有采集到课程文件。"
        lines = [f"- {r['course_name']}: {r['title']}（{r['file_type']}）" for r in rows]
        return "最近的课程文件：\n" + "\n".join(lines)

    # 意图：未读
    if re.search(r"未读|没看|未查看", q):
        rows = db.query(
            "SELECT title, source FROM notices WHERE is_read = 0 "
            "ORDER BY fetched_at DESC LIMIT 8"
        )
        if not rows:
            return "目前没有未读通知，消息都看完了。"
        lines = [f"- ({r['source']}) {r['title']}" for r in rows]
        return f"你有 {len(rows)} 条未读通知：\n" + "\n".join(lines)

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
