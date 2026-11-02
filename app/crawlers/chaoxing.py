"""超星学习通爬虫：课程互动(通知/作业/考试)、课程列表、课程文件。

说明：页面结构随版本变化，解析全部采用“多策略 + 宽松匹配”，
原始响应会落到 data/debug/ 便于对照页面调整选择器。
"""
import re
import time
import urllib.parse

from bs4 import BeautifulSoup

from .. import config
from .base import (
    abs_url,
    fetch,
    make_session,
    save_debug,
    save_debug_file,
    strip_html,
    try_json,
)

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
        if ctype == 1:
            # 固定文件名，方便直接在 data/debug 下查阅
            save_debug_file("cx_studentcourse_first", resp.text)
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
            # 资料页需要 cpi（课程卡片链接里带，如 ...&cpi=489744663&ismooc2=1）
            q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
            cpi = (q.get("cpi") or [""])[0]
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
                    "cpi": cpi,
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


# ---------------------------------------------------------------- 课程资料
# 「资料」页（mooc2 课程才有）：服务端渲染 HTML，文件夹/文件都是一行 ul.dataBody_td
_MAT_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist"
_DOWNLOAD_URL = "https://mooc1.chaoxing.com/coursedata/downloadData"
_PLACEHOLDER_TYPES = {"tch-courseware", ""}  # “返回上一级”等占位行
_MAX_FOLDER_DEPTH = 3


def _mat_rows(html: str):
    """解析资料页每一行 -> {name, type, data_id, objectid, folder}。

    行结构：<ul class="dataBody_td" type="afolder|pdf|doc|mp4|..."
              id="dataId" dataname="名称" objectid="...">
    """
    rows, seen = [], set()
    soup = BeautifulSoup(html, "lxml")
    for ul in soup.select("ul.dataBody_td"):
        name = (ul.get("dataname") or "").strip()
        rtype = (ul.get("type") or "").strip()
        data_id = (ul.get("id") or "").strip()
        if not name or rtype in _PLACEHOLDER_TYPES or data_id in seen:
            continue
        seen.add(data_id)
        rows.append(
            {
                "name": name,
                "type": rtype,
                "data_id": data_id,
                "objectid": (ul.get("objectid") or "").strip(),
                "folder": rtype == "afolder",
            }
        )
    return rows


def _mat_meta(html: str):
    """取资料页隐藏域：enc、totalPages（总页数）、datalistSize（总条数）。"""

    def val(hid):
        m = re.search(r'id="%s"[^>]*value="([^"]*)"' % hid, html)
        return m.group(1) if m else ""

    def num(hid):
        try:
            return int(val(hid) or 0)
        except ValueError:
            return 0

    return {"enc": val("enc"), "pages": max(1, num("totalPages")), "size": num("datalistSize")}


def _mat_page(s, cid, clz, cpi, data_id="", page=1, enc="", parent=""):
    """资料页请求。

    分页参数是 pages（不是 page）；文件夹用 dataId + parent（祖先 id 链）。
    """
    params = {
        "courseid": cid,
        "clazzid": clz,
        "cpi": cpi,
        "ut": "s",
        "t": str(int(time.time() * 1000)),
        "pages": str(page),
        "type": "1",
        "dataId": data_id or "0",
        "order": "0",
    }
    if enc:
        params["enc"] = enc
    if parent:
        params["parent"] = parent
    return fetch(s, _MAT_URL, params=params)


def _collect_files(s, cid, clz, cpi, data_id, depth, ancestors, visited, out, course_name,
                   save_first=False):
    """递归抓文件夹里的文件（深度 <= _MAX_FOLDER_DEPTH），并翻完每一页。"""
    if depth > _MAX_FOLDER_DEPTH or (data_id and data_id in visited):
        return
    if data_id:
        visited.add(data_id)
    try:
        first = _mat_page(s, cid, clz, cpi, data_id, 1, "", ",".join(ancestors))
    except Exception:
        return
    if first.status_code != 200:
        return
    meta = _mat_meta(first.text)
    total = meta["pages"]
    for page in range(1, total + 1):
        if page == 1:
            html = first.text
        else:
            try:
                resp = _mat_page(s, cid, clz, cpi, data_id, page, meta["enc"],
                                 ",".join(ancestors))
            except Exception:
                break
            if resp.status_code != 200:
                break
            html = resp.text
        if save_first and depth == 0 and page == 1:
            save_debug_file("cx_material_first", html)
        for row in _mat_rows(html):
            if row["folder"]:
                _collect_files(
                    s, cid, clz, cpi, row["data_id"], depth + 1,
                    (ancestors + [data_id]) if data_id else [], visited, out, course_name,
                )
                continue
            out.append(
                {
                    "title": row["name"],
                    "file_type": row["type"],
                    "objectid": row["objectid"],
                    "course_name": course_name,
                    "url": (
                        f"{_DOWNLOAD_URL}?dataId={row['data_id']}&classId={clz}"
                        f"&cpi={cpi}&courseId={cid}&ut=s"
                    ),
                }
            )


def fetch_files(force: bool = False):
    """课程 -> 资料：抓取课程「资料」页里的资料。

    数据来源：课程「资料」页（教师推送的课件 + 同学共享的资料），
    文件夹递归展开、多页翻完。不是学生个人云盘，也不是章节卡片附件。
    cpi 取自课程卡片链接（/visit/courselistdata），缺 cpi 的课直接跳过。
    """
    s = _session()
    files = []
    first_done = False
    for c in fetch_courses():
        cid = c.get("course_id", "")
        clz = c.get("clazz_id", "")
        cpi = c.get("cpi", "")
        if not cid or not cpi:
            continue
        out = []
        _collect_files(
            s, cid, clz, cpi, "", 0, [], set(), out,
            c.get("course_name") or cid, save_first=(not first_done),
        )
        if out:
            first_done = True
        files.extend(out)
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
