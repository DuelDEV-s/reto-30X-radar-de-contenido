#!/usr/bin/env bash
# Stores the app settings as encrypted SSM parameters under /radar30x/ (SecureString, free tier).
#   deploy/aws/secrets.sh path/to/.env [more .env files...]
# Later files win. Empty values are skipped. Values never pass through the SSM command history:
# the instance reads them itself with its role when deploy.sh runs.
# APP_PIN (6 digits) and POSTGRES_PASSWORD are generated if they don't exist yet.
# Database settings are managed here, never taken from .env files: PostgreSQL keeps the user, database
# and password it was first created with, so a local value (e.g. radar_local_change_me) uploaded later
# would lock the API out of the existing data. Compose builds DATABASE_URL from them.
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/common.sh"
check_account
[ $# -ge 1 ] || die "Usage: $0 path/to/.env [more .env files...]"

# Local-only settings that Compose or the server define on their own.
SKIP="^(DATABASE_URL|CORS_ORIGINS|TRENDS_DB_PATH|POSTGRES_[A-Z_]+)$"

declare -A values skipped
for file in "$@"; do
  [ -f "$file" ] || die "Not found: $file"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*([A-Z][A-Z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
    value="${value#\"}"; value="${value%\"}"; value="${value#\'}"; value="${value%\'}"
    [[ -z "$value" ]] && continue
    if [[ "$key" =~ $SKIP ]]; then
      skipped[$key]=1
      continue
    fi
    values[$key]="$value"
  done < "$file"
done

put() {
  $AWS ssm put-parameter --name "$PARAM_PREFIX/$1" --type SecureString --overwrite --value "$2" >/dev/null
}
exists() {
  $AWS ssm get-parameter --name "$PARAM_PREFIX/$1" >/dev/null 2>&1
}

for key in "${!values[@]}"; do
  put "$key" "${values[$key]}"
  log "Stored $PARAM_PREFIX/$key"
done
[ ${#skipped[@]} -eq 0 ] || log "Ignored (managed by the deployment): ${!skipped[*]}"

if [ -z "${values[POSTGRES_PASSWORD]:-}" ] && ! exists POSTGRES_PASSWORD; then
  put POSTGRES_PASSWORD "$(python -c 'import secrets; print(secrets.token_hex(24))')"
  log "Generated $PARAM_PREFIX/POSTGRES_PASSWORD"
fi
if [ -z "${values[APP_PIN]:-}" ] && ! exists APP_PIN; then
  put APP_PIN "$(python -c 'import secrets; print(f"{secrets.randbelow(10**6):06d}")')"
  log "Generated $PARAM_PREFIX/APP_PIN"
fi
log "Access PIN: $($AWS ssm get-parameter --name "$PARAM_PREFIX/APP_PIN" --with-decryption --query Parameter.Value --output text)"
