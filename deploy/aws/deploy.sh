#!/usr/bin/env bash
# Deploys (or updates) the app on the EC2 instance: pulls the branch from GitHub, writes .env from the
# /radar30x/* SSM parameters with the instance role, and rebuilds the containers. Re-run after each merge.
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/common.sh"
check_account

remote=$(mktemp)
cat > "$remote" <<EOF
set -euo pipefail
test -f /var/lib/radar30x-ready || { echo "First boot is still installing Docker; retry in a minute."; exit 1; }
mkdir -p /opt && cd /opt
[ -d radar ] || git clone --quiet --branch "$BRANCH" "$REPO_URL" radar
cd radar
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"
echo "Code: \$(git log --oneline -1)"

# Settings and secrets come from SSM Parameter Store; they never travel in this command.
# The snap build of the AWS CLI writes nothing when stdout is redirected to a file, so pipe it.
/snap/bin/aws ssm get-parameters-by-path --region "$REGION" --path "$PARAM_PREFIX" --recursive \
  --with-decryption --output json | cat > /root/radar-params.json
python3 - <<'PY'
import json
params = json.load(open("/root/radar-params.json"))["Parameters"]
lines = []
for p in sorted(params, key=lambda p: p["Name"]):
    key, value = p["Name"].rsplit("/", 1)[1], p["Value"]
    if "'" in value or "\n" in value:
        raise SystemExit(f"{key}: values can't contain quotes or line breaks")
    lines.append(f"{key}='{value}'")
open(".env", "w").write("\n".join(lines) + "\n")
print(f"Wrote .env with {len(lines)} settings: " + ", ".join(sorted(l.split('=')[0] for l in lines)))
PY
rm -f /root/radar-params.json
chmod 600 .env

docker compose -f compose.yaml -f deploy/aws/compose.prod.yaml up -d --build --remove-orphans --wait --wait-timeout 420
docker image prune -f >/dev/null
docker compose -f compose.yaml -f deploy/aws/compose.prod.yaml ps --format "table {{.Service}}\t{{.Status}}"
curl -fsS http://localhost/api/health && echo
EOF

log "Deploying $BRANCH to the instance (first build takes ~6-8 min)"
run_remote "$remote" "radar30x deploy $BRANCH"
rm -f "$remote"
log "App: http://$(public_ip)"
