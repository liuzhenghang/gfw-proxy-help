# 使用Python 3.10官方镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
#RUN apt-get update && apt-get install -y \
#    curl \
#    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .

# 创建非root用户
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# 暴露端口
EXPOSE 6789

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:6789/health || exit 1

# 启动命令
CMD ["gunicorn", "--bind", "0.0.0.0:6789", "--workers", "4", "--timeout", "60", "app:app"] 