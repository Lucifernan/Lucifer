#!/bin/bash
# 腾讯云服务器一键部署脚本（Ubuntu/Debian/CentOS 通用）
# 用法：上传本项目到 /opt/xuexiaozhu 后执行  sudo bash deploy/deploy.sh
set -e

APP_DIR=/opt/xuexiaozhu
cd "$APP_DIR"

# 1. 安装 Python 3 及依赖
if ! command -v python3 >/dev/null; then
  if command -v apt-get >/dev/null; then
    apt-get update && apt-get install -y python3 python3-venv
  else
    yum install -y python3
  fi
fi

# 2. 创建虚拟环境并安装依赖
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple

# 3. 创建服务运行用户（若不存在）
id -u www >/dev/null 2>&1 || useradd -r -s /sbin/nologin www
chown -R www:www "$APP_DIR"

# 4. 安装 systemd 服务并启动
cp deploy/xuexiaozhu.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable xuexiaozhu
systemctl restart xuexiaozhu

sleep 3
systemctl --no-pager status xuexiaozhu | head -5
echo
echo "部署完成：http://$(hostname -I | awk '{print $1}'):8000"
