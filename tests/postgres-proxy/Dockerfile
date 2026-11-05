FROM haproxy:1.8.13-alpine@sha256:18f854d2aaacae5b478f055bda916af57b26bbd56ae328523a235c376e30182f

ENV CONF_DIR=/usr/local/etc/haproxy/ \
    PROXY_PORT=5433 \
    POSTGRES_URL=localhost:5432

COPY conf "${CONF_DIR}"

CMD haproxy -d -f /usr/local/etc/haproxy/haproxy.cfg
