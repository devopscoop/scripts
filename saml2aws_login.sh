#!/usr/bin/env bash

while read -r line; do
  if [[ "$line" =~ ^Account: ]]; then
    account=$(echo $line | awk '{ print $2 }')
  fi
  if [[ "$line" =~ ^arn: ]]; then
    role="${line##*role/}"
    eval "saml2aws login -p ${account}_${role} --role ${line} --skip-prompt"
  fi
done < <(saml2aws list-roles --skip-prompt)
