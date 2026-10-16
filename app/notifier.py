"""提醒通道：Windows 用桌面弹窗（winotify），其它平台（云端 Linux）降级为控制台日志。"""
import platform
import sys

from . import config


def notify(title: str, msg: str) -> bool:
    title = (title or "").strip()[:80]
    msg = (msg or "").strip()[:250]
    if platform.system() != "Windows":
        # 云端部署没有桌面，写日志即可（同步状态也会在网页上展示）
        print(f"[提醒] {title} | {msg}", flush=True)
        return True
    try:
        from winotify import Notification, audio

        toast = Notification(
            app_id="学习提醒助手",
            title=title,
            msg=msg,
            duration="short",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
        return True
    except Exception as e:
        print(f"[提醒失败] {title} | {msg} | {e}", file=sys.stderr, flush=True)
        return False


def enabled(kind: str) -> bool:
    return bool(config.get(f"notify_{kind}"))
