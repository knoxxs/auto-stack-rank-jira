#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugins_file="$repo_root/.tool-plugins"

if ! command -v asdf >/dev/null 2>&1; then
  echo "asdf is not installed or not on PATH" >&2
  exit 1
fi

if [[ ! -f "$plugins_file" ]]; then
  echo "Missing $plugins_file" >&2
  exit 1
fi

while read -r name url; do
  [[ -z "${name:-}" ]] && continue

  if asdf plugin list | grep -qx "$name"; then
    continue
  fi

  asdf plugin add "$name" "$url"
done < "$plugins_file"

asdf install
