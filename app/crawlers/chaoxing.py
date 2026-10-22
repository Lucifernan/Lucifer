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
from .base import abs_url, fetch, make_session, save_debug, strip_html, try_json

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
    """课程列表。

    老入口 /visit/stu-learn 已 404（页面结构改版）；课程实际由互动页
    的 AJAX 接口 /visit/courselistdata 按 courseType 分页加载：
      1 = 我学的课（学生课程），0 = 我教的课（教师课程）。
    返回 HTML 片段，课程卡片为 <li class="course" courseid=... clazzid=...>。
    """
    base = config.get("chaoxing_base").rstrip("/")
    s = _session()
    courses, seen = [], set()

    for ctype in (1, 0):
        resp = fetch(s, f"{base}/visit/courselistdata?courseType={ctype}")
        save_debug(f"chaoxing_courselist_{ctype}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")
        for li in soup.select("li.course"):
            cid = li.get("courseid") or li.get("courseId") or ""
            clz = li.get("clazzid") or li.get("clazzId") or ""
            link = li.select_one('a[href*="courseid="]') or li.find("a", href=True)
            name_el = li.select_one(".course-name") or li.select_one("[class*='course-name']")
            name = ""
            if name_el:
                name = (name_el.get("title") or name_el.get_text(" ", strip=True)).strip()
            if not name and link:
                name = (link.get("title") or link.get_text(" ", strip=True)).strip()
            if not name or _is_junk(name):
                continue
            # 教师：卡片里带非空 title 的 line2 段落
            teacher = ""
            for p in li.select("p"):
                cls = " ".join(p.get("class") or [])
                if "line2" not in cls:
                    continue
                t = (p.get("title") or p.get_text(" ", strip=True)).strip()
                if t and len(t) <= 30:  # 过滤掉抓成课程简介的长文本
                    teacher = t
                    break
            u = abs_url(base, link.get("href", "")) if link else ""
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
                    "url": u,
                    "teacher": teacher,
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


# ------------------------------------------------- 账号密码一键获取 Cookie
def _session_ok(s) -> bool:
    """用互动页判断会话是否已登录（与 ping 同一判据，但用指定会话）。"""
    base = config.get("chaoxing_base").rstrip("/")
    target = config.get("chaoxing_interaction") or f"{base}/visit/interaction"
    try:
        r = fetch(s, target)
    except Exception:
        return False
    u = r.url.lower()
    return r.status_code == 200 and "login" not in u and "passport" not in u and len(r.text) > 2000


# 现行登录入口（旧 /fanya/login 已 404）与提交接口、前端加密参数
_LOGIN_URL = "https://passport2.chaoxing.com/login"
_FANYALOGIN_URL = "https://passport2.chaoxing.com/fanyalogin"
_AES_KEY = b"u2oh6Vu^HWe4_AES"
_LOGIN_FIELDS = (
    "fid", "refer", "t", "forbidotherlogin", "validate",
    "doubleFactorLogin", "independentId", "independentNameId",
)


def _aes_encrypt(text: str) -> str:
    """与超星前端 login.js 一致：AES-128-CBC，密钥=IV，Pkcs7，输出 Base64。"""
    import base64

    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_KEY)
    return base64.b64encode(cipher.encrypt(pad(text.encode("utf-8"), 16))).decode()


def _login_error(msg: str) -> dict:
    msg = (msg or "登录未成功").strip()[:200]
    if re.search(r"验证码|校验码|图形", msg):
        hint = "（可能触发图形验证码：先在浏览器网页登录一次再重试，或改用手动方式）"
    elif re.search(r"密码|账号|用户名", msg):
        hint = "（请核对账号密码）"
    elif re.search(r"风险|异常|锁|频繁", msg):
        hint = "（账号触发风控，请稍后再试）"
    else:
        hint = ""
    return {"ok": False, "error": f"自动登录失败：{msg}{hint}"}


def auto_login(username: str, password: str) -> dict:
    """账号密码自动登录超星并保存 Cookie（傻瓜式获取，无需手动 F12）。

    流程：GET /login 登录页取隐藏参数（fid/refer/t 等）→ 账号密码按
    前端规则 AES 加密 → POST /fanyalogin（返回 JSON）→ 跟随返回跳转
    完成各子域登录 → 互动页校验登录态 → 保存 Cookie 并刷新互动页 URL。
    """
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return {"ok": False, "error": "请填写超星账号和密码"}
    base = config.get("chaoxing_base").rstrip("/")
    s = make_session("")
    # 登录态交给 Cookie jar；requests 下静态 Cookie 头会遮蔽 jar（实测空头也遮蔽）
    s.headers.pop("Cookie", None)

    # 1) 打开登录页，解析隐藏参数
    try:
        resp = fetch(s, _LOGIN_URL)
    except Exception as e:
        return {"ok": False, "error": f"登录页访问失败：{e}"}
    save_debug("chaoxing_login_page", resp.text)
    if "passport404" in resp.url:
        return {"ok": False, "error": "自动登录失败：登录入口已失效，请改用手动方式并反馈我更新"}
    soup = BeautifulSoup(resp.text, "lxml")
    form = next(
        (f for f in soup.find_all("form") if f.find("input", attrs={"type": "password"})),
        None,
    )
    if form is None:
        return {"ok": False, "error": "自动登录失败：登录页结构变化，请改用手动方式"}
    fields = {
        i.get("name"): (i.get("value") or "")
        for i in form.find_all("input")
        if i.get("name")
    }

    # 2) 组装参数；t=true 时按前端规则加密账号与密码
    data = {k: fields.get(k, "") for k in _LOGIN_FIELDS}
    if fields.get("t") == "true":
        data["uname"] = _aes_encrypt(username)
        data["password"] = _aes_encrypt(password)
    else:
        data["uname"] = username
        data["password"] = password

    # 3) 提交 JSON 登录接口
    try:
        r = s.post(
            _FANYALOGIN_URL,
            data=data,
            timeout=20,
            headers={
                "Referer": resp.url,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
    except Exception as e:
        return {"ok": False, "error": f"登录提交失败：{e}"}
    save_debug("chaoxing_fanyalogin", r.text)
    j = try_json(r)
    if not isinstance(j, dict):
        return {"ok": False, "error": f"自动登录失败：接口返回异常(HTTP {r.status_code})，请改用手动方式"}
    if not j.get("status"):
        return _login_error(j.get("msg2") or j.get("msg") or j.get("message") or "")

    # 4) 跟随登录跳转，完成各子域 cookie 落地
    dest = urllib.parse.unquote(j.get("url") or "")
    if dest.startswith("http"):
        try:
            fetch(s, dest)
        except Exception:
            pass

    # 5) 校验登录态（互动页可达且未跳登录）
    if not _session_ok(s):
        return {"ok": False, "error": "自动登录失败：登录成功但会话校验未通过，请改用手动方式"}

    # 6) 保存 Cookie
    cookie = "; ".join(f"{k}={v}" for k, v in s.cookies.get_dict().items())
    if not cookie:
        return {"ok": False, "error": "登录成功但未获得 Cookie，请手动获取"}
    config.update({"chaoxing_cookie": cookie})

    # 7) 尝试刷新账号专属互动页 URL（s 令牌随账号变化）
    try:
        ir = fetch(s, config.get("chaoxing_interaction") or f"{base}/visit/interaction")
        final = ir.url
        if "interaction" in final and "s=" in final and final != config.get("chaoxing_interaction"):
            config.update({"chaoxing_interaction": final})
    except Exception:
        pass

    # 8) 用新 Cookie 复核连通性
    try:
        p = ping()
    except Exception as e:
        p = {"ok": False, "error": str(e)}
    return {"ok": True, "cookie": cookie, "ping": p}
