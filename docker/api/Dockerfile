# 使用 Python 3.11 轻量级镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY main.py .

# 暴露端口
EXPOSE 8080

# 启动命令 - 使用 CPU 核心数作为 worker 数量
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080 --workers $(nproc) --loop uvloop"]
