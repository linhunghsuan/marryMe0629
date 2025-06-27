# 使用官方 Python 映像檔作為基底
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴 (Pillow 可能需要)
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴需求檔案並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製整個應用程式的原始碼到容器中
COPY . .

# 設定 Gunicorn 執行的環境變數
ENV PORT=8080
ENV HOST=0.0.0.0

# 開放容器的 8080 埠
EXPOSE 8080

# 執行 Gunicorn 伺服器
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "app:app"]