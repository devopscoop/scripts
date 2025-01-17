#!/bin/bash

if [[ -z $SAML2AWS_USERNAME || -z $SAML2AWS_PASSWORD ]]; then
cat <<EOF>&2

ERROR: Missing credentials. Run this script like this:

  SAML2AWS_USERNAME=your_Okta_username SAML2AWS_PASSWORD=your_Okta_password $0

EOF
  exit 1
fi

# Reasoning for saml2aws options:
#  --cache-saml allows us to login once and share the token, instead of having to login once per role.
#  --idp-provider sets the provider so we don't have to choose it from a list.
#  --mfa sets mfa so we don't have to choose it from a list.
#  --session-duration ensures that we only have to saml2aws login once every 12 hours (43200 seconds), which is the maximum duration allowed by AWS.
#  --skip-prompt accepts all of these settings non-interactively instead of making us press Enter on each line.
#  --url is the url. Come on. Do I gotta explain everything?
saml2aws configure \
  --cache-saml \
  --idp-provider Okta \
  --mfa DUO \
  --session-duration 43200 \
  --skip-prompt \
  --url https://dfinity.okta.com/home/amazon_aws/0oaakgpu6dUVPYM9y357/272

while read -r line; do
  if [[ -n $line ]]; then
    echo "$line" | grep -q '^Account:' && account=$(echo "$line" | awk '{ print $2 }') && continue
    echo "$line" | grep -q '^arn:' && arn="$line"
    role=$(echo "$arn" | cut -d / -f 2)
    aws --profile ${account}_${role} configure set credential_process "saml2aws login --credential-process --role ${arn} --profile saml"
  fi
done < <(saml2aws list-roles --skip-prompt 2>/dev/null)
