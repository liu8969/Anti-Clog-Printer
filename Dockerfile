FROM python:3.13-slim

# 安装中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config_manager.py .
COPY log_manager.py .
COPY content_generator.py .
COPY ipp_client.py .
COPY docker_main.py .

# 默认每 2 天早上 9:00，可通过环境变量覆盖
ENV SCHEDULE_FREQUENCY=every_2
ENV SCHEDULE_HOUR=9
ENV SCHEDULE_MINUTE=0

CMD ["python", "docker_main.py", "run"]
