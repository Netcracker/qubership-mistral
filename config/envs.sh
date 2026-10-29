#!/bin/bash

function unset_if_empty {
    env_name="${1}"
    env_val="$(printf '%s\n' "${!env_name}")"

    if [[ -z "${env_val// }" ]] || [[ "${env_val}" = "null" ]] ;
    then
        unset "${env_name}"
    fi
}

unset_if_empty HTTP_PROXY
unset_if_empty HTTPS_PROXY
unset_if_empty NO_PROXY

# Do not use internal certificates for externally managed PostgreSQL
function unset_pg_ssl_certs_if_external_pg {
    case "${PGSSLMODE:-require}" in
        verify-ca|verify-full) return 0 ;;
    esac

    local detected
    detected="$(python3 "$(dirname "${BASH_SOURCE[0]}")/pg_ssl_detect.py" 2>/dev/null)" || return 0

    if [ "${detected}" = "external" ]; then
        echo "PostgreSQL ${PG_HOST} detected as externally managed and sslmode is '${PGSSLMODE:-require}': unsetting PGSSLROOTCERT, PGSSLCERT, PGSSLKEY"
        unset PGSSLROOTCERT PGSSLCERT PGSSLKEY
    fi
}

unset_pg_ssl_certs_if_external_pg

export K8S_SA_AUDIENCE="${K8S_SA_AUDIENCE:-netcracker}"

ENGINE_TOPIC="${QUEUE_NAME_PREFIX}_mistral_engine"
EXECUTOR_TOPIC="${QUEUE_NAME_PREFIX}_mistral_executor"
NOTIFIER_TOPIC="${QUEUE_NAME_PREFIX}_mistral_notifier"


SECRETS_DIR="/var/run/secrets/mistral"

_read_secret() {
    local file="$SECRETS_DIR/$1"
    [ -f "$file" ] && cat "$file" || echo ""
}

export PG_USER=$(_read_secret pg-user)
export PG_PASSWORD=$(_read_secret pg-password)
export PG_ADMIN_USER=$(_read_secret pg-admin-user)
export PG_ADMIN_PASSWORD=$(_read_secret pg-admin-password)
export RABBIT_USER=$(_read_secret rabbit-user)
export RABBIT_PASSWORD=$(_read_secret rabbit-password)
export RABBIT_ADMIN_USER=$(_read_secret rabbit-admin-user)
export RABBIT_ADMIN_PASSWORD=$(_read_secret rabbit-admin-password)
export KAFKA_SASL_PLAIN_USERNAME=$(_read_secret kafka-sasl-plain-username)
export KAFKA_SASL_PLAIN_PASSWORD=$(_read_secret kafka-sasl-plain-password)
if [ "$IDP_CREDS_SOURCE" = "cloudcore" ]; then
    export IDP_CLIENT_ID=$(cat /var/run/secrets/mistral-client-credentials/username 2>/dev/null || echo "")
    export IDP_CLIENT_SECRET=$(cat /var/run/secrets/mistral-client-credentials/password 2>/dev/null || echo "")
elif [ "$IDP_CREDS_SOURCE" = "precreated" ]; then
    export IDP_CLIENT_ID=$(cat /var/run/secrets/idp-precreated-user/idp-client-id 2>/dev/null || echo "")
    export IDP_CLIENT_SECRET=$(cat /var/run/secrets/idp-precreated-user/idp-client-secret 2>/dev/null || echo "")
else
    export IDP_CLIENT_ID=$(_read_secret idp-client-id)
    export IDP_CLIENT_SECRET=$(_read_secret idp-client-secret)
fi
export IDP_JWK_EXP=$(_read_secret idp-jwk-exp)
export IDP_JWK_MOD=$(_read_secret idp-jwk-mod)
export IDP_USER=$(_read_secret idp-user-robot)
export IDP_PASSWORD=$(_read_secret idp-password-robot)
export CLIENT_REGISTRATION_TOKEN=$(_read_secret idp-registration-token)

export ENGINE_TOPIC
export EXECUTOR_TOPIC
export NOTIFIER_TOPIC

MISTRAL_VERSION=$(cat /opt/mistral/mistral_version)
export MISTRAL_VERSION

exec "$@"
