#!/bin/sh
# Install the git-quality-gates hooks into the current repository.
#
#     sh install-hooks.sh              install, refusing to replace a hook this tool did not write
#     sh install-hooks.sh --force      replace it, keeping the old one as <hook>.orig
#     sh install-hooks.sh --uninstall  remove the hooks this tool wrote, restoring any .orig
#
# Hooks are copied into the repository's hooks directory (core.hooksPath when set,
# otherwise .git/hooks). Each hook carries the marker line below so a later run can
# tell its own files from anyone else's.
set -eu

marker="managed by git-quality-gates"
hooks="pre-commit commit-msg prepare-commit-msg pre-push post-commit"
force=0
uninstall=0
for arg in "$@"; do
  case "$arg" in
    --force) force=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "usage: sh install-hooks.sh [--force|--uninstall]" >&2; exit 2 ;;
  esac
done

src=$(cd "$(dirname "$0")" && pwd)/hooks
[ -d "$src" ] || { echo "missing hook sources in $src" >&2; exit 1; }
git rev-parse --show-toplevel >/dev/null 2>&1 || { echo "not inside a git repository" >&2; exit 1; }

dest=$(git config --get core.hooksPath || true)
if [ -z "$dest" ]; then
  dest=$(git rev-parse --git-path hooks)
fi
mkdir -p "$dest"

for name in $hooks; do
  target="$dest/$name"
  if [ "$uninstall" -eq 1 ]; then
    if [ -f "$target" ] && grep -q "$marker" "$target"; then
      rm -f "$target"
      [ -f "$target.orig" ] && mv "$target.orig" "$target"
      echo "removed $name"
    fi
    continue
  fi
  if [ -f "$target" ] && ! grep -q "$marker" "$target"; then
    if [ "$force" -ne 1 ]; then
      echo "skipped $name: a hook not written by this tool is already there (use --force)" >&2
      continue
    fi
    cp "$target" "$target.orig"
  fi
  cp "$src/$name" "$target"
  chmod +x "$target"
  echo "installed $name"
done

if [ "$uninstall" -eq 0 ]; then
  echo "Hooks are in $dest. Bypass a gate for one commit with GQG_SKIP=<gate> (logged)."
fi
