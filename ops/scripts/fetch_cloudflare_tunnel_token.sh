#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID in your environment}"
: "${CLOUDFLARE_TUNNEL_ID:?Set CLOUDFLARE_TUNNEL_ID in your environment}"
: "${CLOUDFLARE_EMAIL:?Set CLOUDFLARE_EMAIL in your environment}"
: "${CLOUDFLARE_API_KEY:?Set CLOUDFLARE_API_KEY in your environment}"

curl "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel/${CLOUDFLARE_TUNNEL_ID}/token" \
  -H "X-Auth-Email: ${CLOUDFLARE_EMAIL}" \
  -H "X-Auth-Key: ${CLOUDFLARE_API_KEY}"