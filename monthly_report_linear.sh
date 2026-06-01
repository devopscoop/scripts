#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<EOF

Generates a CSV-formatted list of Linear issues that were assigned to you and completed the previous month.

This script is useful for freelancers. You can copy/paste the output into an invoice for your client.

It prompts for the year and month (defaults to previous month). Requires LINEAR_API_KEY env var or interactive input.

Example:

Enter your Linear API key: lin_api_a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9
Year [2026]:
Month [05]:

User: Jane Doe
Closed in 2026-05: 2

"Identifier","Title"
"ABC-123","Fix login bug"
"ABC-456","Update docs"

EOF
  exit 0
fi

LINEAR_API_KEY="${LINEAR_API_KEY:-}"
API_URL="https://api.linear.app/graphql"

if [ -z "$LINEAR_API_KEY" ]; then
  read -r -p "Enter your Linear API key: " LINEAR_API_KEY
fi

DEFAULT_YEAR=$(date +%Y)
DEFAULT_MONTH=$(printf "%02d" "$(($(date +%-m) - 1))")
if [ "$DEFAULT_MONTH" = "00" ]; then
  DEFAULT_MONTH=12
  DEFAULT_YEAR=$((DEFAULT_YEAR - 1))
fi

read -r -p "Year [$DEFAULT_YEAR]: " YEAR
YEAR=${YEAR:-$DEFAULT_YEAR}
read -r -p "Month [$DEFAULT_MONTH]: " MONTH
MONTH=${MONTH:-$DEFAULT_MONTH}

MONTH=$(printf "%02d" "$MONTH")
if ! [ "$MONTH" -ge 1 ] 2>/dev/null || ! [ "$MONTH" -le 12 ] 2>/dev/null; then
  echo "Invalid month"; exit 1
fi
START_DATE="${YEAR}-${MONTH}-01T00:00:00.000Z"

# Compute first day of next month for the upper bound
if [ "$MONTH" = "12" ]; then
  NEXT_YEAR=$((YEAR + 1))
  NEXT_MONTH="01"
else
  NEXT_YEAR="$YEAR"
  NEXT_MONTH=$(printf "%02d" $((10#$MONTH + 1)))
fi
END_DATE="${NEXT_YEAR}-${NEXT_MONTH}-01T00:00:00.000Z"

query() {
  cat <<'EOF'
query ($after: String, $startDate: DateTimeOrDuration!) {
  viewer {
    id
    name
  }
  issues(
    first: 50
    after: $after
    filter: {
      completedAt: { gte: $startDate }
      assignee: { isMe: { eq: true } }
    }
  ) {
    nodes {
      identifier
      title
      completedAt
      url
      team { name }
      state { name }
    }
    pageInfo { hasNextPage endCursor }
  }
}
EOF
}

all_issues=""
has_next=true
after=null

while [ "$has_next" = true ]; do
  if [ "$after" = "null" ]; then
    vars=$(jq -n --arg s "$START_DATE" '{after: null, startDate: $s}')
  else
    vars=$(jq -n --arg s "$START_DATE" --arg a "${after//\"/}" '{after: $a, startDate: $s}')
  fi

  response=$(curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: $LINEAR_API_KEY" \
    -d "$(jq -n --arg q "$(query)" --argjson v "$vars" '{query: $q, variables: $v}')")

  errors=$(echo "$response" | jq -r '.errors // empty')
  if [ -n "$errors" ]; then
    echo "API Error: $errors" >&2
    exit 1
  fi

  viewer_name=$(echo "$response" | jq -r '.data.viewer.name // "Unknown"')

  issues=$(echo "$response" | jq -r '.data.issues.nodes // []')
  has_next=$(echo "$response" | jq -r '.data.issues.pageInfo.hasNextPage')
  end_cursor=$(echo "$response" | jq -r '.data.issues.pageInfo.endCursor // null')

  filtered=$(echo "$issues" | jq -c --arg start "$START_DATE" --arg end "$END_DATE" '
    [.[] | select(
      (.completedAt != null) and
      (.completedAt >= $start) and
      (.completedAt < $end)
    )]
  ')

  if [ -z "$all_issues" ]; then
    all_issues="$filtered"
  else
    all_issues=$(echo "$all_issues" "$filtered" | jq -s 'add')
  fi

  if [ "$has_next" = "true" ] && [ "$end_cursor" != "null" ]; then
    after="\"$end_cursor\""
  else
    has_next=false
  fi
done

count=$(echo "$all_issues" | jq 'length')

echo ""
echo "User: $viewer_name"
echo "Closed in $YEAR-$MONTH: $count"
echo ""

if [ "$count" -gt 0 ]; then
  echo '"Identifier","Title"'
  echo "$all_issues" | jq -r '.[] | [.identifier, .title] | @csv'
fi
