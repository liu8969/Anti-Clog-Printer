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
# 无界面入口：容器内可用 docker compose exec anti-clog python docker_main.py preview 生成预览
COPY docker_main.py .
COPY healthcheck.py .

EXPOSE 18080

# 默认每 2 天早上 9:00，可通过环境变量覆盖
ENV SCHEDULE_FREQUENCY=every_2
ENV SCHEDULE_HOUR=9
ENV SCHEDULE_MINUTE=0
# 打印图案与覆盖强度：coverage=全喷嘴斜线覆盖页（防堵主力，默认）
#                        classic=经典彩色页 | link_test=细色带自检（不防堵）
ENV PATTERN=coverage
ENV DUTY=standard
# 省墨测试模式：1=只打印一条细色带。⚠️ 只润湿极少数喷孔，不能用于日常防堵
ENV TEST_MODE=0
# 测试页旋转补偿：默认 0（与 README / docker-compose 保持一致），
# 仅当个别打印机连 A4 竖向图也旋转时才设 1
ENV TEST_ROTATE=0

# 健康检查：Web 服务返回 200 或 401（已启用 Basic Auth）均视为健康
HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["python", "web_main.py"]
