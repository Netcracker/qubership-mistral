FROM python:3.10.21-alpine3.24@sha256:8d62622e4ad0e5adfd01efecd25a0a5ea571a22aaaeff481796ce10828d46504

WORKDIR /app
RUN echo 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main/' > /etc/apk/repositories && \
    echo 'https://dl-cdn.alpinelinux.org/alpine/v3.24/community/' >> /etc/apk/repositories && \
    apk update && apk upgrade --no-cache && apk add --no-cache \
    curl

COPY requirements.txt .

RUN pip install --upgrade pip==25.3 && pip install -r requirements.txt

# RUN pip install --upgrade pip==23.3 "setuptools==70.0.0"

COPY . .

EXPOSE 8000

ENV DEBUG_LOG=false \
    HOST=0.0.0.0 \
    PG_USER='postgres' \
    PG_PASSWORD="" \
    PG_HOST='postgres' \
    PG_PORT='5432' \
    PG_DB_NAME='mistral'\
    TLS_ENABLED=false

USER 1005000:1005000
RUN find / -perm /6000 -type f -exec chmod a-s {} \; || true

CMD ["python3", "main.py"]
