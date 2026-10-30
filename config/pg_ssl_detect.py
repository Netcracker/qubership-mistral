#!/usr/bin/env python3
"""Detect whether the PostgreSQL server looks like an externally managed one.

Prints "external" to stdout when PG is considered externally managed
(AWS RDS, Azure, GCP, ...), prints nothing otherwise. Always exits 0 so it can
never break container start-up; any doubt means "not external".

Signals (inputs are existing env vars only: PG_HOST, PG_PORT, PGSSLROOTCERT):
  1. Canonical host name. An ExternalName Service is resolved in-cluster as a
     CNAME, so the canonical name reveals the real target.
  2. TLS probe. If the server certificate does not chain to the platform CA
     configured in PGSSLROOTCERT, the server is not the platform-managed one.
"""
import logging
import os
import socket
import ssl
import struct
import sys

MANAGED_SUFFIXES = (
    ".rds.amazonaws.com",
    ".rds.amazonaws.com.cn",
    ".postgres.database.azure.com",
    ".postgres.database.usgovcloudapi.net",
    ".postgres.database.chinacloudapi.cn",
    ".sql.goog",
)
TIMEOUT = 5
PG_SSL_REQUEST = struct.pack("!II", 8, 80877103)

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s,%(msecs)03d][%(levelname)-5s][category=%(name)s]"
           "[pid=%(process)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOG = logging.getLogger("pg_ssl_detect")


def canonical_name(host):
    try:
        info = socket.getaddrinfo(host, None, flags=socket.AI_CANONNAME)
        return (info[0][3] or host).lower().rstrip(".")
    except OSError as e:
        LOG.warning(f"cannot resolve canonical name of {host}: {e}; using host as is")
        return host.lower().rstrip(".")


def looks_managed(host):
    names = {host.lower().rstrip("."), canonical_name(host)}
    return any(n.endswith(MANAGED_SUFFIXES) for n in names)


def cert_chains_to(host, port, root_cert):
    """True: chains to root_cert; False: does not; None: could not determine."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
            sock.settimeout(TIMEOUT)
            sock.sendall(PG_SSL_REQUEST)
            answer = sock.recv(1)
            if answer != b"S":
                LOG.warning(f"{host}:{port} did not accept TLS upgrade "
                    f"(reply={answer!r}); cannot compare certificates")
                return None
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False  # only the chain matters here
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(root_cert)
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
    host = os.environ.get("PG_HOST", "").strip()
    if not host:
        LOG.warning("PG_HOST is not set; nothing to detect")
        return
    try:
        port = int(os.environ.get("PG_PORT") or 5432)
    except ValueError:
        port = 5432

    if looks_managed(host):
        LOG.info(f"{host} resolves to a known managed PostgreSQL domain")
        print("external")
        return

    root = os.environ.get("PGSSLROOTCERT", "")
    if not root or not os.path.isfile(root):
        LOG.warning(f"PGSSLROOTCERT {root!r} is not a file; skipping TLS probe, "
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
