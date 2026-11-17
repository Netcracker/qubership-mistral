FROM haproxy:3.4.7-alpine@sha256:b9fe316f718d5015c5cfebd8ca019591f3e44656f61d93cb8b59a1028961e530

ENV CONF_DIR=/usr/local/etc/haproxy/ \
    PROXY_PORT=5433 \
    POSTGRES_URL=localhost:5432

COPY conf "${CONF_DIR}"

CMD haproxy -d -f /usr/local/etc/haproxy/haproxy.cfg
