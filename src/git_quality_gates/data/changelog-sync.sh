#!/bin/sh
# Append a Conventional-Commit summary to CHANGELOG.md's [Unreleased] section.
# Called by the post-commit hook, but runnable by hand:
#   sh changelog-sync.sh                       # sync from HEAD's commit subject
#   sh changelog-sync.sh --subject "feat: x"   # sync from an explicit subject
#   sh changelog-sync.sh --selftest            # run the built-in check
#
# Type -> Keep a Changelog heading:  feat -> Added; fix -> Fixed;
# perf/refactor/revert -> Changed; security -> Security.
# Noise types (docs/chore/style/test/ci/build) are ignored.
# Idempotent: an entry already present under [Unreleased] is not duplicated.
set -u

FILE="CHANGELOG.md"
SUBJECT=""
selftest=0
while [ $# -gt 0 ]; do
  case "$1" in
    --file)     FILE="$2"; shift 2 ;;
    --subject)  SUBJECT="$2"; shift 2 ;;
    --selftest) selftest=1; shift ;;
    *) echo "usage: $0 [--file F] [--subject S] [--selftest]" >&2; exit 2 ;;
  esac
done

# insert <file> <commit-subject>: edits <file> in place if the subject is a
# feat/fix/perf conventional commit and the entry is not already recorded.
insert() {
  f="$1"; subject="$2"
  [ -f "$f" ] || return 0
  type=$(printf '%s' "$subject" | sed -nE 's/^([a-z]+)(\([^)]*\))?!?:.*/\1/p')
  desc=$(printf '%s' "$subject"  | sed  -E 's/^[a-z]+(\([^)]*\))?!?:[[:space:]]*//')
  [ -n "$type" ] || return 0
  case "$type" in
    feat)     head="Added" ;;
    fix)      head="Fixed" ;;
    perf)     head="Changed" ;;
    refactor) head="Changed" ;;
    revert)   head="Changed" ;;
    security) head="Security" ;;
    *) return 0 ;;
  esac
  entry="- $desc"
  grep -qF -e "$entry" "$f" && return 0
  # Insert as the first bullet under "### <head>" inside [Unreleased], keeping the
  # markdownlint-clean "### head\n\n- item" shape (blank line after the heading).
  awk -v h="$head" -v e="$entry" '
    function flush(){ if (in_u && !done){ print "### " h; print ""; print e; print ""; done=1 } }
    /^## \[Unreleased\]/ { print; in_u=1; next }
    {
      if (skipblank) { skipblank=0; if ($0 == "") next }  # drop the blank line under the heading; we re-added it
      if (in_u && $0 ~ /^## /)  { flush(); in_u=0 }        # reached the next release section
      if (in_u && $0 == "### " h) { print; print ""; print e; done=1; skipblank=1; next }
      print
    }
    END { flush() }
  ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}

if [ "$selftest" = "1" ]; then
  tmp=$(mktemp)
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n\n- existing\n\n## [1.0.0] - 2020-01-01\n' > "$tmp"
  insert "$tmp" "feat(cache): add entry expiry"
  insert "$tmp" "fix: bounded copy in parser"
  insert "$tmp" "refactor: split the parser module"  # refactor -> Changed
  insert "$tmp" "security: pin the trusted root"         # security -> Security
  insert "$tmp" "chore: noise"                        # ignored type
  grep -qF -e "- add entry expiry"        "$tmp" || { echo "FAIL: feat not added"; exit 1; }
  grep -qF -e "- bounded copy in parser" "$tmp" || { echo "FAIL: fix not added"; exit 1; }
  grep -qF -e "### Fixed"              "$tmp" || { echo "FAIL: Fixed heading not created"; exit 1; }
  grep -qF -e "- split the parser module" "$tmp" || { echo "FAIL: refactor not added"; exit 1; }
  grep -qF -e "### Security"           "$tmp" || { echo "FAIL: Security heading not created"; exit 1; }
  grep -qF -e "- pin the trusted root"    "$tmp" || { echo "FAIL: security not added"; exit 1; }
  grep -qF -e "noise"                  "$tmp" && { echo "FAIL: ignored type leaked in"; exit 1; }
  insert "$tmp" "feat(cache): add entry expiry"       # re-run: must stay idempotent
  n=$(grep -cF -e "- add entry expiry" "$tmp")
  [ "$n" = "1" ] || { echo "FAIL: not idempotent (count=$n)"; exit 1; }
  rm -f "$tmp"
  echo "changelog-sync selftest: OK"
  exit 0
fi

[ -n "$SUBJECT" ] || SUBJECT=$(git log -1 --format=%s 2>/dev/null) || exit 0
insert "$FILE" "$SUBJECT"
