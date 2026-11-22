FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY kiln ./kiln
COPY scripts ./scripts
ENV PYTHONUNBUFFERED=1
