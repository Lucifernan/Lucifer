"""智慧树（知到）爬虫：站内学习通知 / 消息中心。

依赖浏览器复制的 Cookie（zhihuishu.com 域）。页面结构随版本变化，
采用“多策略 + 宽松匹配”解析，原始响应会落到 data/debug/ 便于调整。
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .. import config
from .base import abs_url, fetch, make_session, save_debug, strip_html

JUNK = {
    "首页", "登录", "注册", "下载", "APP下载", "客户端下载", "客服", "帮助",
    "关于", "更多", "查看更多", "进入", "返回", "我的", "个人中心", "知到",
    "意见反馈", "版权声明", "联系我们", "全部课程", "我的课程", "消息", "设置",
}

# 消息中心常见入口（依次尝试，命中一个即可）
MESSAGE_PATHS = [
    "/portal/messageCenter",          # 消息中心
    "/mySystem/messageCenter",        # 个人消息中心
    "/studentMessage/queryMessageList",  # 消息列表接口（JSON）
    "/myIndex/messagePage",           # 消息页
]


def _session():
    cookie = config.get("zhihuishu_cookie")
    if not cookie:
        raise RuntimeError("未配置智慧树 Cookie")
    return make_session(cookie)


def _base() -> str:
    return config.get("zhihuishu_base").rstrip("/")


def _is_login_page(html: str, url: str) -> bool:
    low = url.lower()
    if "caslogin" in low or "/login" in low or "passport" in low:
        return True
    return bool(re.search(r'name="(username|loginName|account|userAccount)"', html, re.I))


def _classify(text: str) -> str:
    for kind, words in (
        ("exam", ["考试", "测验", "期中", "期末"]),
        ("homework", ["作业", "习题", "测试", "互评"]),
        ("notice", ["通知", "公告", "活动", "答疑", "签到"]),
    ):
        if any(w in text for w in words):
            return kind
    return "notice"


def _is_junk(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return True
    if t in JUNK:
        return True
    return any(x in t.lower() for x in ("javascript:", "版权", "icp", "备案"))


def _add(items, seen, title, href="", context=""):
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title or _is_junk(title):
        return
    url = abs_url(_base(), href or "")
    key = f"zhs::{title}::{url}"
    if key in seen:
        return
    seen.add(key)
    full = f"{title} {context or ''}"
    m = re.search(r"(20\d\d[-/]\d{1,2}[-/]\d{1,2})", context or "")
    items.append(
        {
            "source": "zhihuishu",
            "kind": _classify(full),
            "title": title,
            "content": strip_html(context or "")[:500],
            "url": url,
            "published_at": m.group(1).replace("/", "-") if m else "",
            "dedupe_key": key,
        }
    )


def _parse_html(html: str, base_url: str):
    """从任意消息页面解析条目：JSON 内嵌 → 表格 → 通用链接/列表块。"""
    items, seen = [], set()
    soup = BeautifulSoup(html, "lxml")

    # 策略1：内嵌 JSON（很多 SPA 把消息列表放在 window.xxx = [...]）
    import json

    for m in re.finditer(r"(?:messageList|msgList|records|list)\s*[:=]\s*(\[[\s\S]{100,}?\])", html):
        try:
            arr = json.loads(m.group(1))
        except Exception:
            continue
        for it in arr:
            if not isinstance(it, dict):
                continue
            title = (
                it.get("title") or it.get("msgTitle") or it.get("theme")
                or it.get("content") or it.get("msgContent") or ""
            )
            ctx = str(it.get("content") or it.get("msgContent") or it.get("summary") or "")
            pub = str(it.get("sendTime") or it.get("createTime") or it.get("publishTime") or "")
            link = str(it.get("url") or it.get("link") or "")
            _add(items, seen, strip_html(str(title)), link, f"{ctx} {pub}")

    # 策略2：表格行
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = tr.get_text(" ", strip=True)
        for a in tr.find_all("a", href=True):
            _add(items, seen, a.get_text(strip=True), a["href"], row_text)

    # 策略3：通用链接
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript", "#", "mailto")):
            continue
        parent = a.find_parent(["li", "div", "dd"])
        ctx = parent.get_text(" ", strip=True)[:300] if parent else ""
        _add(items, seen, a.get_text(" ", strip=True), href, ctx)

    # 策略4：无链接的消息卡片
    for box in soup.select(
        ".message-item, .notice, .notify, [class*='message'], [class*='notice'], [class*='msg']"
    ):
        text = box.get_text(" ", strip=True)
        if 6 <= len(text) <= 160:
            _add(items, seen, text, "", text)

    return items


def fetch_notices():
    """抓取智慧树学习通知。"""
    s = _session()
    base = _base()
    candidates = []
    custom = str(config.get("zhihuishu_message_url") or "").strip()
    if custom:
        candidates.append(custom)
    candidates += [base + p for p in MESSAGE_PATHS]
    candidates.append(base)

    collected, last_err = [], ""
    for url in candidates:
        try:
            resp = fetch(s, url)
        except Exception as e:
            last_err = str(e)
            continue
        dbg_name = "zhihuishu_" + re.sub(r"[^\w]+", "_", url.split("//", 1)[-1])[:50]
        save_debug(dbg_name, resp.text)
        if _is_login_page(resp.text, resp.url):
            last_err = "智慧树 Cookie 已失效，请重新复制"
            # 首页/CAS 跳转即视为失效，不再继续尝试其它入口
            break
        if resp.status_code != 200 or len(resp.text) < 500:
            continue
        items = _parse_html(resp.text, resp.url)
        collected.extend(items)
        # 任何一个入口拿到内容就停止
        if items and url != base:
            break

    # 去重
    dedup, seen = [], set()
    for it in collected:
        if it["dedupe_key"] in seen:
            continue
        seen.add(it["dedupe_key"])
        dedup.append(it)

    if not dedup and last_err:
        raise RuntimeError(last_err)
    if not dedup:
        raise RuntimeError("未解析到通知内容，可到设置页填写「消息中心 URL」，或检查 data/debug/ 下的智慧树抓取文件")
    return dedup


def ping() -> dict:
    s = _session()
    url = str(config.get("zhihuishu_message_url") or "").strip() or _base()
    resp = fetch(s, url)
    save_debug("zhihuishu_ping", resp.text)
    ok = (
        resp.status_code == 200
        and not _is_login_page(resp.text, resp.url)
        and len(resp.text) > 1000
    )
    return {"ok": ok, "url": resp.url, "status": resp.status_code, "len": len(resp.text)}
