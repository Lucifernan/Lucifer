"""PythonAnywhere 的 WSGI 入口。

PythonAnywhere 只托管 WSGI 应用，而本项目是 FastAPI(ASGI)，
通过 a2wsgi 做一次协议桥接即可原样运行。

注意：a2wsgi 不会触发 FastAPI 的 lifespan 事件，
所以数据库初始化与定时调度必须在这里手动启动（只执行一次）。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

try:
    from a2wsgi import ASGIMiddleware
except ImportError:  # 兼容不同版本的 a2wsgi
    from a2wsgi.asgi import ASGIMiddleware

from app import config, db  # noqa: E402
from app.main import app as asgi_app  # noqa: E402
from app.scheduler import start as start_scheduler  # noqa: E402

if not getattr(config, "_wsgi_ready", False):
    db.init_db()
    config._wsgi_ready = True  # 防止多进程加载时重复启动调度器
    try:
        start_scheduler()
        print("[WSGI] 数据库与定时调度已启动", flush=True)
    except Exception as e:
        print(f"[WSGI] 调度器启动失败: {e}", flush=True)

application = ASGIMiddleware(asgi_app)
