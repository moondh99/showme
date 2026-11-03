FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY web ./web
COPY public/demo/sample-notepad.jpg ./public/demo/sample-notepad.jpg
COPY public/demo/sample-photo-source.json ./public/demo/sample-photo-source.json
COPY scripts/serve_hosted.py ./scripts/serve_hosted.py
COPY public/demo/reception-setup ./public/demo/reception-setup
ENV SHOWME_DATA_DIR=/data SHOWME_SEED_DEMO=1 SHOWME_AI_DAILY_LIMIT=40 PORT=8000
EXPOSE 8000
CMD ["python", "scripts/serve_hosted.py"]
