# 腾讯云 CloudBase / 通用容器部署镜像
FROM python:3.11-slim

# 不缓冲输出，方便看日志；容器内必须监听 0.0.0.0
# PORT 必须与平台健康检查端口一致（腾讯云 CloudBase Run 探针检查 8000）
ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 先装依赖（利用分层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt

# 再拷贝代码
COPY . .

# CloudBase Run 会在控制台或环境变量里覆盖 PORT，这里给出默认值
EXPOSE 80

CMD ["python", "-m", "app.main"]
