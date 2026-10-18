#!/usr/bin/env bash
# Creates the AWS infrastructure for the app. Safe to re-run: existing pieces are reused.
#   IAM role + instance profile (SSM access and read-only access to /radar30x/* parameters)
#   Security group (HTTP 80 and HTTPS 443 only; no SSH, administration goes through SSM)
#   EC2 instance (Ubuntu 24.04, t3.small, 25 GB gp3, IMDSv2, CPU credits "standard" = no burst charges)
#   Elastic IP, so the address survives stop/start
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/common.sh"
check_account

TAGS="Key=Project,Value=$NAME"
ACCOUNT="$EXPECTED_ACCOUNT"

# --- IAM ------------------------------------------------------------------------------
ROLE="$NAME-ec2"
if ! $AWS iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  log "Creating IAM role $ROLE"
  $AWS iam create-role --role-name "$ROLE" --tags "$TAGS" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  $AWS iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
fi
$AWS iam put-role-policy --role-name "$ROLE" --policy-name "$NAME-read-params" --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{\"Effect\": \"Allow\",
    \"Action\": [\"ssm:GetParametersByPath\", \"ssm:GetParameters\", \"ssm:GetParameter\"],
    \"Resource\": [\"arn:aws:ssm:$REGION:$ACCOUNT:parameter$PARAM_PREFIX\", \"arn:aws:ssm:$REGION:$ACCOUNT:parameter$PARAM_PREFIX/*\"]}]
}"
if ! $AWS iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  log "Creating instance profile $ROLE"
  $AWS iam create-instance-profile --instance-profile-name "$ROLE" --tags "$TAGS" >/dev/null
  $AWS iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  sleep 15   # new instance profiles take a few seconds to be usable by EC2
fi

# --- Network --------------------------------------------------------------------------
VPC=$($AWS ec2 describe-vpcs --filters Name=is-default,Values=true --query "Vpcs[0].VpcId" --output text)
[ "$VPC" != "None" ] || die "The account has no default VPC in $REGION."
SG=$($AWS ec2 describe-security-groups --filters "Name=group-name,Values=$NAME-web" "Name=vpc-id,Values=$VPC" \
  --query "SecurityGroups[0].GroupId" --output text)
if [ "$SG" = "None" ]; then
  log "Creating security group $NAME-web (80, 443)"
  SG=$($AWS ec2 create-security-group --group-name "$NAME-web" --vpc-id "$VPC" \
    --description "Radar 30X: public HTTP/HTTPS only" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$NAME-web},{$TAGS}]" \
    --query GroupId --output text)
  for port in 80 443; do
    $AWS ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
      "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]" >/dev/null
  done
fi

# --- Instance -------------------------------------------------------------------------
ID=$(instance_id)
if [ -z "$ID" ]; then
  AMI=$($AWS ssm get-parameters --names "$AMI_PARAM" --query "Parameters[0].Value" --output text)
  log "Launching $INSTANCE_TYPE from $AMI"
  ID=$($AWS ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
    --security-group-ids "$SG" --iam-instance-profile "Name=$ROLE" \
    --credit-specification CpuCredits=standard \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
    --user-data "file://$(native_path "$HERE/user-data.sh")" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME-app},{$TAGS}]" \
                         "ResourceType=volume,Tags=[{Key=Name,Value=$NAME-disk},{$TAGS}]" \
    --query "Instances[0].InstanceId" --output text)
fi
log "Waiting for $ID to run"
$AWS ec2 start-instances --instance-ids "$ID" >/dev/null 2>&1 || true
$AWS ec2 wait instance-running --instance-ids "$ID"

# --- Elastic IP -----------------------------------------------------------------------
ALLOC=$($AWS ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME-ip" --query "Addresses[0].AllocationId" --output text)
if [ "$ALLOC" = "None" ]; then
  log "Allocating Elastic IP"
  ALLOC=$($AWS ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME-ip},{$TAGS}]" \
    --query AllocationId --output text)
fi
$AWS ec2 associate-address --allocation-id "$ALLOC" --instance-id "$ID" --allow-reassociation >/dev/null

log "Waiting for the instance to register with SSM (first boot installs Docker, ~3 min)"
for _ in $(seq 1 60); do
  online=$($AWS ssm describe-instance-information --filters "Key=InstanceIds,Values=$ID" \
    --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
  [ "$online" = "Online" ] && break
  sleep 10
done
[ "$online" = "Online" ] || die "The instance did not register with SSM in 10 minutes."

log "Ready: instance $ID, address http://$(public_ip)"
log "Next: deploy/aws/secrets.sh <env file>, then deploy/aws/deploy.sh"
