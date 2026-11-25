#!/usr/bin/env bash
# Pulls a bounded slice of the Kubernetes docs for two releases into corpus/.
#
#   corpus/<version>/concepts/...        from content/en/docs/concepts
#   corpus/<version>/tasks/...           from content/en/docs/tasks
#   corpus/<version>/releases/version-skew-policy.md
#   corpus/_feature_gates/<version>/*.md  (metadata only, not counted as pages;
#                                          1.31 pages read gate maturity from here)
#
# The commit SHA of each branch is written to corpus/MANIFEST.json, so the exact
# snapshot can be fetched again later. Re-running replaces corpus/<version>/.
set -euo pipefail

REPO="https://github.com/kubernetes/website.git"
VERSIONS=("1.27" "1.31")
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS="$ROOT/corpus"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

entries=()
for v in "${VERSIONS[@]}"; do
  echo "Fetching release-$v ..."
  git clone -q --depth 1 --filter=blob:none --sparse -b "release-$v" "$REPO" "$WORK/$v"
  git -C "$WORK/$v" sparse-checkout set \
    content/en/docs/concepts \
    content/en/docs/tasks \
    content/en/releases \
    content/en/docs/reference/command-line-tools-reference/feature-gates

  sha="$(git -C "$WORK/$v" rev-parse HEAD)"
  dest="$CORPUS/$v"
  rm -rf "$dest"
  mkdir -p "$dest/releases"
  cp -r "$WORK/$v/content/en/docs/concepts" "$dest/"
  cp -r "$WORK/$v/content/en/docs/tasks" "$dest/"
  cp "$WORK/$v/content/en/releases/version-skew-policy.md" "$dest/releases/"

  gates_src="$WORK/$v/content/en/docs/reference/command-line-tools-reference/feature-gates"
  rm -rf "$CORPUS/_feature_gates/$v"
  if [ -d "$gates_src" ]; then
    mkdir -p "$CORPUS/_feature_gates/$v"
    cp "$gates_src"/*.md "$CORPUS/_feature_gates/$v/"
  fi

  # Keep markdown only. Images and example YAML aren't part of the text corpus.
  find "$dest" -type f ! -name '*.md' -delete
  find "$dest" -type d -empty -delete

  pages="$(find "$dest" -name '*.md' | wc -l)"
  echo "  $pages pages, commit $sha"
  entries+=("    {\"version\": \"$v\", \"branch\": \"release-$v\", \"commit\": \"$sha\", \"pages\": $pages}")
done

{
  echo "{"
  echo "  \"source\": \"$REPO\","
  echo "  \"fetched_on_utc\": \"$(date -u +%Y-%m-%d)\","
  echo "  \"paths\": [\"content/en/docs/concepts\", \"content/en/docs/tasks\", \"content/en/releases/version-skew-policy.md\"],"
  echo "  \"versions\": ["
  (IFS=$'\n'; echo "${entries[*]}" | sed '$!s/$/,/')
  echo "  ]"
  echo "}"
} > "$CORPUS/MANIFEST.json"

echo "Wrote $CORPUS/MANIFEST.json"
