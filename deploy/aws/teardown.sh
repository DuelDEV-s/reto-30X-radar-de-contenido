#!/usr/bin/env bash
# Deletes everything provision.sh created (instance and its disk, Elastic IP, security group, IAM role).
#   deploy/aws/teardown.sh                 keep the /radar30x/* parameters (keys, PIN)
#   deploy/aws/teardown.sh --with-secrets  delete them too
# The database lives on the instance disk: it is deleted with it.
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/common.sh"
check_account

ID=$(instance_id)
if [ -n "$ID" ]; then
  log "Terminating $ID"
  $AWS ec2 terminate-instances --instance-ids "$ID" >/dev/null
  $AWS ec2 wait instance-terminated --instance-ids "$ID"
fi

ALLOC=$($AWS ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME-ip" --query "Addresses[0].AllocationId" --output text)
if [ "$ALLOC" != "None" ]; then
  log "Releasing Elastic IP"
  $AWS ec2 release-address --allocation-id "$ALLOC"
fi

SG=$($AWS ec2 describe-security-groups --filters "Name=group-name,Values=$NAME-web" --query "SecurityGroups[0].GroupId" --output text)
if [ "$SG" != "None" ]; then
  log "Deleting security group $SG"
  $AWS ec2 delete-security-group --group-id "$SG"
fi

ROLE="$NAME-ec2"
if $AWS iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  $AWS iam remove-role-from-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE" 2>/dev/null || true
  $AWS iam delete-instance-profile --instance-profile-name "$ROLE"
fi
if $AWS iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  log "Deleting IAM role $ROLE"
  $AWS iam delete-role-policy --role-name "$ROLE" --policy-name "$NAME-read-params" 2>/dev/null || true
  $AWS iam detach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore 2>/dev/null || true
  $AWS iam delete-role --role-name "$ROLE"
fi

if [ "${1:-}" = "--with-secrets" ]; then
  names=$($AWS ssm get-parameters-by-path --path "$PARAM_PREFIX" --recursive --query "Parameters[].Name" --output text)
  for n in $names; do $AWS ssm delete-parameter --name "$n"; done
  log "Deleted $PARAM_PREFIX/* parameters"
fi
log "Done"
