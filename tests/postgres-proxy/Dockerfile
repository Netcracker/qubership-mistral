FROM haproxy:1.9.16-alpine@sha256:1ce3536f2a9ad53f1ccb953c23146e88e9bb138b74f38dae03e9494140a643cf

ENV CONF_DIR=/usr/local/etc/haproxy/ \
    PROXY_PORT=5433 \
    POSTGRES_URL=localhost:5432

COPY conf "${CONF_DIR}"

CMD haproxy -d -f /usr/local/etc/haproxy/haproxy.cfg
