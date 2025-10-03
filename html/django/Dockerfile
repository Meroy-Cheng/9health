FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 重點：libmariadb-dev 取代 libmysqlclient-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    libmariadb-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

RUN pip install --upgrade pip && pip install -r requirements.txt

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY LINE_APP_api/google_sheet_key.json /app/LINE_APP_api/google_sheet_key.json

COPY . /app


EXPOSE 8002

CMD ["python", "manage.py", "runserver", "0.0.0.0:8002"]
