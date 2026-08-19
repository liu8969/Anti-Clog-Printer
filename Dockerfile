FROM python:3.13-slim

# 安装中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config_manager.py .
COPY log_manager.py .
COPY content_generator.py .
COPY ipp_client.py .
COPY scheduler_manager.py .
COPY web_main.py .

EXPOSE 18080

# 默认每 2 天早上 9:00，可通过环境变量覆盖
ENV SCHEDULE_FREQUENCY=every_2
ENV SCHEDULE_HOUR=9
ENV SCHEDULE_MINUTE=0
# 省墨测试模式：1=只打印一条细色带（验证打印链路用）
ENV TEST_MODE=0
# 测试页旋转补偿：1=预先旋转90°（部分打印机把横向图片旋转竖排，需补偿）
ENV TEST_ROTATE=1

CMD ["python", "web_main.py"]
