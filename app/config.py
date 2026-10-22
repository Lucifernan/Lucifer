"""全局配置：存放在 data/config.json，提供读写接口。"""
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 云端部署可用环境变量 APP_DATA_DIR 指到持久化磁盘（如 Render Disk）
DATA_DIR = Path(os.environ.get("APP_DATA_DIR") or (BASE_DIR / "data"))
DEBUG_DIR = DATA_DIR / "debug"
CONFIG_PATH = DATA_DIR / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    # ---- 超星学习通 ----
    "chaoxing_cookie": "",
    "chaoxing_base": "https://mooc1-1.chaoxing.com",
    # 用户给的“课程互动”页面，留空则用默认拼接
    "chaoxing_interaction": "https://mooc1-1.chaoxing.com/visit/interaction?s=0ef41e041a0a92b0fd6c2ed219537606%277",
    "chaoxing_fetch_files": True,
    # ---- 智慧树（知到） ----
    "zhihuishu_cookie": "",
    "zhihuishu_base": "https://www.zhihuishu.com",
    # 消息/通知中心页面 URL，留空则先抓首页并尝试常见消息接口
    "zhihuishu_message_url": "",
    # ---- 提醒与同步 ----
    "sync_interval_minutes": 30,
    "daily_digest_time": "08:00",
    "notify_new_notice": True,
    "notify_digest": True,
    "notify_weekly": True,
    "debug": True,
}

_lock = threading.Lock()


def _load() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


_cache = _load()


def get(key: str = None):
    with _lock:
        if key is None:
            return dict(_cache)
        return _cache.get(key, DEFAULTS.get(key))


def update(patch: dict) -> dict:
    with _lock:
        for k, v in patch.items():
            if k in DEFAULTS:
                _cache[k] = v
        CONFIG_PATH.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return dict(_cache)
