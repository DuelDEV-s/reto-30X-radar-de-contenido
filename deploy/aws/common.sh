# Shared settings for the AWS deploy scripts. Source it; don't run it.
# Every AWS call goes through $AWS with an explicit profile and region, never the default profile.
set -euo pipefail
export MSYS_NO_PATHCONV=1            # Git Bash on Windows rewrites arguments that start with "/"

PROFILE="${RADAR_AWS_PROFILE:-radar30x}"
REGION="${RADAR_AWS_REGION:-us-east-2}"
EXPECTED_ACCOUNT="${RADAR_AWS_ACCOUNT:-872582135424}"
NAME="radar30x"
PARAM_PREFIX="/radar30x"
INSTANCE_TYPE="${RADAR_INSTANCE_TYPE:-t3.small}"
VOLUME_GB="${RADAR_VOLUME_GB:-25}"
REPO_URL="https://github.com/DuelDEV-s/reto-30X-radar-de-contenido.git"
BRANCH="${RADAR_BRANCH:-main}"
AMI_PARAM="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"

AWS="aws --profile $PROFILE --region $REGION"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Refuse to touch any account other than the one this project was set up for.
check_account() {
  local account
  account=$($AWS sts get-caller-identity --query Account --output text 2>/dev/null) \
    || die "Profile $PROFILE has no valid session. Run: aws login --profile $PROFILE --region $REGION"
  [ "$account" = "$EXPECTED_ACCOUNT" ] \
    || die "Profile $PROFILE points to account $account, expected $EXPECTED_ACCOUNT. Nothing was changed."
}

instance_id() {
  $AWS ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME-app" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query "Reservations[].Instances[].InstanceId" --output text
}

public_ip() {
  $AWS ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME-ip" --query "Addresses[0].PublicIp" --output text
}

# Path the aws executable can open (on Git Bash, aws.exe needs a Windows path).
native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# Run a shell script on the instance through SSM (no SSH, no open port 22) and print its output.
run_remote() {
  local script_file="$1" comment="$2" id command_id status request
  id=$(instance_id)
  [ -n "$id" ] || die "No $NAME-app instance. Run provision.sh first."
  request=$(mktemp)
  python - "$(native_path "$script_file")" "$id" "$comment" > "$request" <<'PY'
import json, sys
script, instance, comment = sys.argv[1:4]
# AWS-RunShellScript runs commands with /bin/sh (dash on Ubuntu): hand the script to bash.
command = ("cat > /root/radar-remote.sh <<'RADAR_REMOTE_EOF'\n" + open(script, encoding="utf-8").read()
           + "\nRADAR_REMOTE_EOF\nbash /root/radar-remote.sh; rc=$?; rm -f /root/radar-remote.sh; exit $rc")
print(json.dumps({
    "InstanceIds": [instance],
    "DocumentName": "AWS-RunShellScript",
    "Comment": comment[:100],
    "TimeoutSeconds": 600,
    "Parameters": {"commands": [command], "executionTimeout": ["3600"]},
}))
PY
  command_id=$($AWS ssm send-command --cli-input-json "file://$(native_path "$request")" \
    --query Command.CommandId --output text)
  rm -f "$request"
  log "SSM command $command_id ($comment)"
  while true; do
    sleep 10
    status=$($AWS ssm get-command-invocation --command-id "$command_id" --instance-id "$id" \
      --query Status --output text 2>/dev/null || echo Pending)
    case "$status" in
      Pending|InProgress|Delayed) printf '.' ;;
      *) echo; break ;;
    esac
  done
  $AWS ssm get-command-invocation --command-id "$command_id" --instance-id "$id" \
    --query "[StandardOutputContent,StandardErrorContent]" --output text | tail -n 60
  [ "$status" = "Success" ] || die "Remote command ended with status $status"
}
