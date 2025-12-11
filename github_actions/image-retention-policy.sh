#!/usr/bin/env bash

# This script will decimate your bloated ghcr.io container package registry. I
# can't believe that GitHub doesn't have any image retention settings yet. I
# guess just because you're Big Tech doesn't mean you're Good at Tech...
#
# Specifically, this will scan your repo, find containers with tags like:
# "buildcache", "dev-*", and "prod-*", keep the latest 10 containers for each
# of those tags, and DELETE ALL THE OTHER CONTAINERS!!!
#
# To use this script, you need set these variables:
#
# export GITHUB_TOKEN=REDACTED
# export org=your_github_org_name
# export package_name=your_package_name
#
# Your GITHUB_TOKEN should be a classic token with read:packages and write:packages. See:
# https://docs.github.com/en/rest/packages/packages?apiVersion=2022-11-28#list-packages-for-an-organization

# https://vaneyckt.io/posts/safer_bash_scripts_with_set_euxo_pipefail/
set -Eeuo pipefail

buildcache_keep=()
dev_keep=()
dry_run=${dry_run:-true}
keep_limit=10
kept_ids=()
prod_keep=()

# Get all versions (paginated). Newest come first by default.
versions_json=$(gh api --paginate "/orgs/${org}/packages/container/${package_name}/versions?per_page=100")

# Build a list of versions with id, created_at, and tags (flattened)
# tags may be under .metadata.container.tags or .metadata.docker.tag depending on type.
versions=$(echo "$versions_json" | jq -r '
  .[] | {
    id,
    created_at,
    tags: (
      ( .metadata.container.tags // [] )
      + ( .metadata.docker.tag // [] )
    )
  } | @base64
')

# Iterate newest to oldest
for v in $versions; do
  obj=$(echo "$v" | base64 -d)
  id=$(echo "$obj" | jq -r '.id')
  #created=$(echo "$obj" | jq -r '.created_at')

  # Dedupe ids (in case of pagination oddities)
  if printf '%s\n' "${kept_ids[@]:-}" | grep -qx "$id"; then
    continue
  fi

  tags=$(echo "$obj" | jq -r '.tags[]?' || true)

  has_buildcache=false
  has_dev=false
  has_prod=false

  for t in $tags; do
    if [[ "$t" =~ ^prod-.* ]]; then
      has_prod=true
    fi
    if [[ "$t" =~ ^dev-.* ]]; then
      has_dev=true
    fi
    if [[ "$t" =~ ^buildcache$ ]]; then
      has_buildcache=true
    fi
  done

  if $has_prod && ((${#prod_keep[@]} < keep_limit)); then
    prod_keep+=("$id")
    kept_ids+=("$id")
    continue
  fi

  if $has_dev && ((${#dev_keep[@]} < keep_limit)); then
    dev_keep+=("$id")
    kept_ids+=("$id")
    continue
  fi

  if $has_buildcache && ((${#buildcache_keep[@]} < keep_limit)); then
    buildcache_keep+=("$id")
    kept_ids+=("$id")
    continue
  fi
done

echo "Keeping cache ids: ${buildcache_keep[*]:-}"
echo "Keeping dev ids: ${dev_keep[*]:-}"
echo "Keeping prod ids: ${prod_keep[*]:-}"

# Build space-separated list of ids to keep
keep_set=$(printf '%s\n' "${kept_ids[@]:-}" | sort -u)

# Now delete every other version id
delete_ids=()
while read -r v; do
  [ -z "$v" ] && continue
  obj=$(echo "$v" | base64 -d)
  id=$(echo "$obj" | jq -r '.id')
  if ! printf '%s\n' $keep_set | grep -qx "$id"; then
    delete_ids+=("$id")
  fi
done <<< "$versions"

echo "Deleting ${#delete_ids[@]} versions"

for id in "${delete_ids[@]}"; do
  echo "Deleting version id $id"
  if [[ "$dry_run" == "false" ]]; then

    # TODO: This doesn't actually work correctly yet. It doesn't check to see which tags a particular version is being used by, so what happens is that your tags remain, but when you try to pull the images, you get "manifest unknown" errors. The fix is to check each version id for tags, and don't delete any versions if they are being used by tags you want to keep. I don't know how to do this yet. Something like this:
    #
    # # Get version details before deleting
    # version_tags=$(gh api "/orgs/${org}/packages/container/${package_name}/versions/${id}" --jq '.metadata.container.tags | join(", ")')
    # echo "This version has tags: ${version_tags}"
    # echo "Deleting this will remove ALL these tags"
    #
    # gh api \
    #   --method DELETE \
    #   "/orgs/${org}/packages/container/${package_name}/versions/${id}" || \
    #   echo "Failed to delete $id (possibly already deleted)"

  fi
done

if [[ "$dry_run" == "true" ]]; then
    echo "WARNING: To actually delete all of these packages, set the environment variable dry_run=false. It would be extremely unwise to do this without checking the \"Keeping ids\" in the output first. This script WILL DELETE ALL YOUR PACKAGES if they don't match the very specific tagging scheme of \"buildcache\", \"dev-*\", or \"prod-*\"."
fi
