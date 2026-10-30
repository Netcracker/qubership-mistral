#!/usr/bin/env python3
"""Detect whether the RabbitMQ broker looks like an externally managed one.

Prints "external" to stdout when RabbitMQ is considered externally managed
(Amazon MQ, Azure Service Bus, CloudAMQP, ...), prints nothing otherwise.
Always exits 0 so it can never break container start-up; any doubt means
"not external".

Signals (inputs are existing env vars only: RABBIT_HOST, RABBIT_PORT and
RABBITMQ_SSL_CA_FILE, which defaults to the platform CA bundle path):
  0. Explicit override. RABBITMQ_EXTERNALLY_MANAGED=true|false skips the
     detection (use it when the broker is behind a custom DNS name and its CA
     is already part of the platform CA bundle, which defeats signal 2).
  1. Canonical host name. An ExternalName Service is resolved in-cluster as a
     CNAME, so the canonical name reveals the real target.
  2. TLS probe. If the server certificate does not chain to the platform CA
     bundle, the broker is not the platform-managed one.
"""
import logging
import os
import re
import socket
import ssl
import sys

MANAGED_PATTERNS = tuple(re.compile(p) for p in (
    # Amazon MQ: b-<id>.mq.<region>.amazonaws.com[.cn] (and *.on.aws)
    r"\.mq\.[a-z0-9-]+\.(amazonaws\.com(\.cn)?|on\.aws)$",
    r"\.servicebus\.windows\.net$",
    r"\.servicebus\.usgovcloudapi\.net$",
    r"\.servicebus\.chinacloudapi\.cn$",
    r"\.cloudamqp\.com$",
))
DEFAULT_CA_FILE = "/opt/mistral/mount_configs/tls/ca.crt"
TIMEOUT = 5

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s,%(msecs)03d][%(levelname)-5s][category=%(name)s]"
           "[pid=%(process)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOG = logging.getLogger("rmq_ssl_detect")


def canonical_name(host):
    try:
        info = socket.getaddrinfo(host, None, flags=socket.AI_CANONNAME)
        return (info[0][3] or host).lower().rstrip(".")
    except OSError as e:
        LOG.warning(f"cannot resolve canonical name of {host}: {e}; using host as is")
        return host.lower().rstrip(".")


def looks_managed(host):
    names = {host.lower().rstrip("."), canonical_name(host)}
    return any(p.search(n) for n in names for p in MANAGED_PATTERNS)


def cert_chains_to(host, port, root_cert):
    """True: chains to root_cert; False: does not; None: could not determine."""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False  # only the chain matters here
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(root_cert)
        with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
            sock.settimeout(TIMEOUT)
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except ssl.SSLCertVerificationError as e:
        LOG.info(f"server certificate of {host}:{port} does not chain to "
                 f"{root_cert}: {e.verify_message}")
        return False
    except Exception as e:
        LOG.warning(f"TLS probe of {host}:{port} inconclusive "
                    f"({type(e).__name__}: {e}); keeping current settings")
        return None


def main():
    override = os.environ.get("RABBITMQ_EXTERNALLY_MANAGED", "").strip().lower()
    if override in ("true", "false"):
        LOG.info(f"RABBITMQ_EXTERNALLY_MANAGED={override}; skipping detection")
        if override == "true":
            print("external")
        return

    host = os.environ.get("RABBIT_HOST", "").strip()
    if not host:
        LOG.warning("RABBIT_HOST is not set; nothing to detect")
        return
    try:
        port = int(os.environ.get("RABBIT_PORT") or 5671)
    except ValueError:
        port = 5671

    if looks_managed(host):
        LOG.info(f"{host} resolves to a known managed RabbitMQ domain")
        print("external")
        return

    root = os.environ.get("RABBITMQ_SSL_CA_FILE") or DEFAULT_CA_FILE
    if not os.path.isfile(root):
        LOG.warning(f"CA file {root!r} is not a file; skipping TLS probe, "
                    f"treating {host} as not external")
        return

    result = cert_chains_to(host, port, root)
    if result is False:
        print("external")
    elif result is True:
        LOG.info(f"server certificate of {host}:{port} chains to {root}; "
                 f"treating as not external")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
