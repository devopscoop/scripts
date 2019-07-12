#!/bin/bash

# Based on https://github.com/hashicorp/terraform/issues/12877#issuecomment-311649591

# Architectural choices:
#
# * One Terraform backend per region to ensure that global services always have
#   a local Terraform backend for maximum responsiveness.
#
# * All Terraform configurations for this AWS account use their regional
#   backend. Multiple Terraform configurations are separated by backend key name.

set -euo pipefail

if [[ -z $AWS_DEFAULT_REGION ]]; then
  cat <<EOF >&2

ERROR: Please set the AWS_DEFAULT_REGION environment variable. For example:

export AWS_DEFAULT_REGION=us-east-1
   
EOF
  exit
fi

aws_account_id="$(aws sts get-caller-identity --query Account --output text)"
dynamodb_table="terraform-${AWS_DEFAULT_REGION}"
project_name="${PWD##*/}"
s3_bucket_name="terraform-${aws_account_id}-${AWS_DEFAULT_REGION}"

if [[ $AWS_DEFAULT_REGION != 'us-east-1' ]]; then
  aws s3api create-bucket \
    --bucket "${s3_bucket_name}" \
    --create-bucket-configuration LocationConstraint="${AWS_DEFAULT_REGION}" \
    --region "${AWS_DEFAULT_REGION}"
else
  aws s3api create-bucket \
    --bucket "${s3_bucket_name}"
fi

aws s3api put-bucket-versioning \
  --bucket "${s3_bucket_name}" \
  --versioning-configuration Status=Enabled

dynamodb_exists=$(aws dynamodb list-tables --output json | jq -r '.TableNames[] | contains("terraform-us-east-1")')

if ! $dynamodb_exists; then
  aws dynamodb create-table \
    --attribute-definitions 'AttributeName=LockID,AttributeType=S' \
    --key-schema 'AttributeName=LockID,KeyType=HASH' \
    --provisioned-throughput 'ReadCapacityUnits=1,WriteCapacityUnits=1' \
    --region "${AWS_DEFAULT_REGION}" \
    --table-name "${dynamodb_table}"
fi

cat <<EOF > backend.tf
terraform {
  backend "s3" {
    bucket = "${s3_bucket_name}"
    encrypt = "true"
    key = "${project_name}"
    dynamodb_table = "${dynamodb_table}"
    region = "${AWS_DEFAULT_REGION}"
  }
}
EOF

terraform init
