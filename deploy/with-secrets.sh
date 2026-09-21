#!/bin/sh
set -eu

KEY_FILE="${SECRETS_KEY_FILE:-/data/secrets/fernet.key}"

if [ -z "${SECRETS_ENCRYPTION_KEY:-}" ] && [ -s "$KEY_FILE" ]; then
    SECRETS_ENCRYPTION_KEY="$(cat "$KEY_FILE")"
    export SECRETS_ENCRYPTION_KEY
fi

exec "$@"
