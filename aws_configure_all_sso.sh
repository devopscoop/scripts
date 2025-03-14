#!/usr/bin/env bash

# https://vaneyckt.io/posts/safer_bash_scripts_with_set_euxo_pipefail/
# Not using "-x" because we aren't debugging.
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  cat <<EOF

ERROR: You must specify your start URL prefix and region like this:

$0 start_url_prefix aws_region

Example:

$0 mycompany us-west-2

EOF
  exit 1
fi

export org_name="${1}"
export AWS_DEFAULT_REGION="${2}"

# It would be cool to do this non-interactively, but that's not currently
# possible. Until this bug is fixed, we're using echo and pipe as a workaround:
# https://github.com/aws/aws-cli/issues/7835#issuecomment-2051991772
echo "${org_name}
https://${org_name}.awsapps.com/start
${AWS_DEFAULT_REGION}
sso:account:access" | \
aws configure sso-session

aws sso login --sso-session "${org_name}"

export latest_sso_file="$(ls -1t "${HOME}/.aws/sso/cache" | head -n 1)"
export access_token="$(jq -r .accessToken "${HOME}/.aws/sso/cache/${latest_sso_file}")"

account_list_json="$(aws sso list-accounts --access-token "${access_token}")"

while read -r account_id; do
  account_name="$(echo "${account_list_json}" | jq -r ".accountList[] | select(.accountId == \"${account_id}\") | .accountName")"
  role_list_json="$(aws sso list-account-roles --access-token "${access_token}" --account-id "${account_id}")"
  while read -r role_name; do

    # Replacing spaces in profile names with '\ ' because Terraform can't handle quoted AWS_PROFILE names.
    # https://github.com/hashicorp/terraform/issues/35091
    profile_name="$(echo "${org_name}_${account_name}_${role_name}" | sed 's/ /\\ /g')"

    aws configure set "profile.${profile_name}.sso_session" "${org_name}"
    aws configure set "profile.${profile_name}.sso_account_id" "${account_id}"
    aws configure set "profile.${profile_name}.sso_role_name" "${role_name}"
    aws configure set "profile.${profile_name}.region" "${AWS_DEFAULT_REGION}"
    echo "Added ${profile_name}"
  done < <(echo "$role_list_json" | jq -r '.roleList[].roleName')
done < <(echo "$account_list_json" | jq -r '.accountList[].accountId')
