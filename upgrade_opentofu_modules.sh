#!/usr/bin/env bash

# Delete lock file, because OpenTofu currently has readonly access to it, so it won't update anything if it exists.
rm -rf .terraform.lock.hcl .terraform

# Comment out all module versions so `tofu init -upgrade` can pull the latest versions.
grep -rI --exclude-dir .git --exclude-dir .terraform -E '^[ ]+version[ ]+=' -l | xargs sed -Ei 's/^([ ]+)version /#\1version /'

# Upgrade everything!
tofu init -upgrade

echo -e "\nThese are the new module versions you should use in your *.tf files:\n"
jq -r '.Modules[] | "\(.Source) \(.Version)"' .terraform/modules/modules.json | sort -u

echo -e "\nThere are the *.tf files that need to be manually edited. Find the version above, add it to the file, then uncomment the version line.\n"
git diff HEAD ./*.tf
