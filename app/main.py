r"""服务入口：启动 Web 界面 + 定时任务。

本地启动（项目根目录）：
    .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
云端部署（用环境变量控制，无需改代码）：
    HOST=0.0.0.0 PORT=8000 APP_DATA_DIR=/data python -m uvicorn app.main:app
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routes import router
from .scheduler import start as start_scheduler

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    config.get()  # 触发配置加载
    try:
        start_scheduler()
    except Exception as e:
        print(f"[调度器启动失败] {e}")
    print(f"[学习提醒助手] 数据目录: {config.DATA_DIR}")
    yield


app = FastAPI(title="大学生教学指导提醒智能体", lifespan=lifespan)
app.include_router(router)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def run():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    run()
