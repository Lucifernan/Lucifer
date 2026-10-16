"""超星学习通爬虫：课程互动(通知/作业/考试)、课程列表、课程文件。

说明：页面结构随版本变化，解析全部采用“多策略 + 宽松匹配”，
原始响应会落到 data/debug/ 便于对照页面调整选择器。
"""
import json
import re
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup

from .. import config
from .base import abs_url, fetch, make_session, save_debug, strip_html

# 导航/推广类干扰词
JUNK = {
    "首页", "登录", "注册", "下载", "APP下载", "客户端下载", "客服", "帮助",
    "关于", "更多", "查看更多", "进入", "进入课程", "返回", "我的", "个人中心",
    "意见反馈", "网站地图", "版权声明", "联系我们", "微博", "微信", "QQ",
    "mooc", "超星", "学习通", "爱课程", "图书馆", "全部课程", "我的课程",
}

KIND_WORDS = {
    "homework": ["作业", "习题", "测试", "答题", "互评"],
    "exam": ["考试", "测验", "期中", "期末"],
    "notice": ["通知", "公告", "活动", "答疑", "签到", "课堂"],
}


def _session():
    cookie = config.get("chaoxing_cookie")
    if not cookie:
        raise RuntimeError("未配置超星 Cookie")
    return make_session(cookie)


def _classify(text: str) -> str:
    for kind, words in KIND_WORDS.items():
        if any(w in text for w in words):
            return kind
    return "notice"


def _is_junk(text: str) -> bool:
    t = text.strip()
    if len(t) < 4:
        return True
    low = t.lower()
    if t in JUNK or any(w == t for w in JUNK):
        return True
    if any(x in low for x in ("javascript:", "版权", "icp", "备案")):
        return True
    return False


# ---------------------------------------------------------------- 课程列表
def fetch_courses():
    base = config.get("chaoxing_base").rstrip("/")
    s = _session()
    resp = fetch(s, f"{base}/visit/stu-learn")
    save_debug("chaoxing_stu-learn", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")
    courses, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"courseid=", href, re.I):
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        cid = (q.get("courseid") or q.get("courseId") or [""])[0]
        clz = (q.get("clazzid") or q.get("clazzId") or [""])[0]
        name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if not name:
            img = a.find("img")
            if img:
                name = (img.get("alt") or "").strip()
        if not name and clz:
            # 名称可能在相邻节点
            parent = a.parent
            if parent:
                name = strip_html(str(parent))[:60]
        if not name:
            continue
        key = (name, cid)
        if key in seen:
            continue
        seen.add(key)
        courses.append(
            {
                "source": "chaoxing",
                "course_name": name,
                "course_id": cid,
                "clazz_id": clz,
                "url": abs_url(base, href),
                "teacher": "",
            }
        )
    return courses


# ---------------------------------------------------- 课程互动（通知/作业/考试）
def fetch_interaction():
    base = config.get("chaoxing_base").rstrip("/")
    url = config.get("chaoxing_interaction") or f"{base}/visit/interaction"
    s = _session()
    resp = fetch(s, url)
    save_debug("chaoxing_interaction", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")
    items, seen = [], set()

    def add(title, href, context=""):
        title = re.sub(r"\s+", " ", title).strip()
        if not title or _is_junk(title):
            return
        full = f"{title} {context}"
        kind = _classify(full)
        m = re.search(r"(20\d\d[-/]\d{1,2}[-/]\d{1,2})", context)
        pub = m.group(1).replace("/", "-") if m else ""
        u = abs_url(base, href or "")
        key = f"cx::{title}::{u}"
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "source": "chaoxing",
                "kind": kind,
                "title": title,
                "url": u,
                "published_at": pub,
                "content": strip_html(context)[:500],
            }
        )

    # 策略1：表格行
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = tr.get_text(" ", strip=True)
        for a in tr.find_all("a", href=True):
            add(a.get_text(strip=True), a["href"], row_text)

    # 策略2：通用链接
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript", "#", "mailto")):
            continue
        text = a.get_text(" ", strip=True)
        ctx = ""
        parent = a.find_parent(["li", "div", "dd"])
        if parent:
            ctx = parent.get_text(" ", strip=True)[:300]
        add(text, href, ctx)

    # 策略3：卡片/列表块里的标题文本（没有链接的通知）
    for box in soup.select(".notice, .notify, .dynamic, [class*='notice'], [class*='msg']"):
        text = box.get_text(" ", strip=True)
        if 6 <= len(text) <= 120:
            add(text, "", text)

    return items


# ---------------------------------------------------------------- 课程文件
def _iter_courses(soup):
    """yield (course_id, clazz_id, course_name)。"""
    seen = set()
    for a in soup.find_all("a", href=True):
        if not re.search(r"courseid=", a["href"], re.I):
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(a["href"]).query)
        cid = (q.get("courseid") or [""])[0]
        clz = (q.get("clazzid") or [""])[0]
        if not cid or (cid, clz) in seen:
            continue
        seen.add((cid, clz))
        name = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if not name:
            img = a.find("img")
            name = (img.get("alt") if img else "") or ""
        yield cid, clz, name[:60]


def _chapters_of(soup):
    """从课程页提取章节 knowledgeId。"""
    kids, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"knowledge|chapter", href, re.I):
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        kid = (q.get("knowledgeId") or q.get("knowledgeid") or q.get("chapterId") or [""])[0]
        if not kid:
            m = re.search(r"(?:chapterId|knowledgeId)=(\d+)", href, re.I)
            kid = m.group(1) if m else ""
        if kid and kid not in seen:
            seen.add(kid)
            kids.append(kid)
    return kids


def _cards_attachments(html: str, base: str):
    """knowledge/cards 页面里附件藏在 li[data] 的 JSON 中。"""
    soup = BeautifulSoup(html, "lxml")
    out = []

    def walk(obj):
        if isinstance(obj, dict):
            oid = obj.get("objectid") or obj.get("objectId")
            name = obj.get("name") or obj.get("filename") or obj.get("title") or ""
            if oid and name:
                url = obj.get("url") or obj.get("download") or obj.get("preview") or ""
                prop = obj.get("property") if isinstance(obj.get("property"), dict) else {}
                ftype = str(obj.get("type") or prop.get("type") or "")
                out.append(
                    {
                        "title": str(name),
                        "objectid": str(oid),
                        "file_type": ftype,
                        "url": url if str(url).startswith("http") else abs_url(base, str(url)),
                    }
                )
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for li in soup.find_all(attrs={"data": True}):
        raw = li.get("data") or ""
        if "objectid" not in raw and "objectId" not in raw:
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            for m in re.finditer(r'"objectid"\s*:\s*"?(\w+)', raw):
                out.append(
                    {
                        "title": li.get_text(" ", strip=True)[:80] or f"附件 {m.group(1)}",
                        "objectid": m.group(1),
                        "file_type": "",
                        "url": "",
                    }
                )
            break
    # 兜底：整页正则
    if not out:
        for m in re.finditer(r'"objectid"\s*:\s*"?(\w+)"?[^}]{0,400}?"name"\s*:\s*"([^"]{1,120})"', html):
            out.append(
                {
                    "title": m.group(2),
                    "objectid": m.group(1),
                    "file_type": "",
                    "url": "",
                }
            )
    res, seen = [], set()
    for f in out:
        if f["objectid"] in seen:
            continue
        seen.add(f["objectid"])
        if not f["url"]:
            f["url"] = f"{base}/visit/uobject?objectid={f['objectid']}"
        res.append(f)
    return res


_files_last_run = 0.0


def fetch_files(force: bool = False, max_chapters: int = 10):
    """按 课程 -> 章节 -> 附件 抓取课件文件（较重，由 sync 控制频率）。"""
    import time

    global _files_last_run
    if not force and time.time() - _files_last_run < 6 * 3600:
        return []
    base = config.get("chaoxing_base").rstrip("/")
    s = _session()
    files = []
    # 课程入口
    resp = fetch(s, f"{base}/visit/stu-learn")
    soup = BeautifulSoup(resp.text, "lxml")
    for cid, clz, cname in _iter_courses(soup):
        try:
            page = fetch(
                s,
                f"{base}/mycourse/studentcourse",
                params={"courseid": cid, "clazzid": clz, "ut": "s"},
            )
            csoup = BeautifulSoup(page.text, "lxml")
            kids = _chapters_of(csoup)
            if not kids:
                # 尝试另一个入口页
                page2 = fetch(
                    s,
                    f"{base}/visit/stu-learn",
                    params={"courseid": cid, "clazzid": clz},
                )
                kids = _chapters_of(BeautifulSoup(page2.text, "lxml"))
            for kid in kids[:max_chapters]:
                try:
                    card = fetch(
                        s,
                        f"{base}/knowledge/cards",
                        params={
                            "courseid": cid,
                            "clazzid": clz,
                            "knowledgeId": kid,
                            "ut": "s",
                            "vc": "true",
                            "mooc": "true",
                        },
                    )
                    if "objectid" in card.text:
                        save_debug(f"cx_cards_{cid}_{kid}", card.text)
                    for f in _cards_attachments(card.text, base):
                        f["course_name"] = cname or cid
                        files.append(f)
                except Exception:
                    continue
        except Exception:
            continue
    _files_last_run = time.time()
    return files


def ping() -> dict:
    """连通性测试。"""
    base = config.get("chaoxing_base").rstrip("/")
    s = _session()
    resp = fetch(s, config.get("chaoxing_interaction") or f"{base}/visit/interaction")
    ok = "login" not in resp.url.lower() and resp.status_code == 200 and len(resp.text) > 2000
    save_debug("chaoxing_ping", resp.text)
    return {"ok": ok, "url": resp.url, "status": resp.status_code, "len": len(resp.text)}
