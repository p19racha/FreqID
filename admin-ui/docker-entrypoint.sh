#!/bin/sh
set -e

# Injects runtime API URL configuration into config.js if specified via env var
CONFIG_FILE="/usr/share/nginx/html/config.js"

if [ -n "$FREQID_API_URL" ]; then
  cat <<EOF > "$CONFIG_FILE"
// Runtime configuration injected by container entrypoint
window.__FREQID_CONFIG__ = {
  apiUrl: "$FREQID_API_URL"
};
EOF
fi

# Execute the default container command
exec "$@"
