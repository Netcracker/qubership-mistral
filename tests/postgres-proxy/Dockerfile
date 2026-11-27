FROM haproxy:3.4.8-alpine@sha256:8aa6458a9d22a8364a2d2ee9ce93de0cc4a2789e3cf63f0b44adc972863724d7

ENV CONF_DIR=/usr/local/etc/haproxy/ \
    PROXY_PORT=5433 \
    POSTGRES_URL=localhost:5432

COPY conf "${CONF_DIR}"

CMD haproxy -d -f /usr/local/etc/haproxy/haproxy.cfg
