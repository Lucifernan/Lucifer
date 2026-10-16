"""爬虫公共工具：会话构造、调试落盘、JSON 通用解析。"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from .. import config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def make_session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": cookie.strip(),
        }
    )
    return s


def fetch(session: requests.Session, url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", 20)
    kw.setdefault("allow_redirects", True)
    resp = session.get(url, **kw)
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp


def save_debug(name: str, text: str):
    if not config.get("debug"):
        return
    from ..config import DEBUG_DIR

    safe = re.sub(r"[^\w\-.]+", "_", name)[:80]
    path = DEBUG_DIR / f"{safe}_{int(time.time())}.txt"
    try:
        path.write_text(text[:400000], encoding="utf-8", errors="ignore")
    except Exception:
        pass


def pick(d: dict, *keys, default=""):
    """按候选键名取值，兼容不同版本字段。"""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def rows_of(obj, *list_keys):
    """从响应里提取列表：支持根列表 / rows / records / data 等常见包装。"""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in list_keys:
            v = obj.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = rows_of(v, *list_keys)
                if inner:
                    return inner
        # 兜底：找第一个值是列表的键
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def try_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return None


def strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def abs_url(base: str, href: str) -> str:
    return urljoin(base, href) if href else ""


def load_json_text(text: str):
    """有些接口把 JSON 包在回调或注释里，尽量解析出可用对象。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("{") or t.startswith("["):
        try:
            return json.loads(t)
        except Exception:
            pass
    m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None
