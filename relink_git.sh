#!/bin/bash
# Give the restored working directories their git history back.
#
# The workspace archive deliberately excludes .git, which keeps it small but leaves every
# directory as loose files: no branch, no remote, nothing to push. That is fine for reading
# and fatal for working, because work done here could never get back to the laptop.
#
# For each directory with a known remote, this clones the repository beside it, moves the
# .git directory in, and resets the index against HEAD. Restored files that differ from the
# remote then show up as ordinary modifications, ready to commit, rather than being lost.
#
#   relink_git.sh            link anything not already a repository
#   relink_git.sh --force    re-link even where a .git already exists
#
# Safe to re-run. It never touches working files.
set -uo pipefail

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# directory:remote. Kept here rather than guessed, so a wrong remote cannot be invented.
REPOS=(
  "$HOME/.claude:ncanoCumula3/claude-home"
  "$HOME/claude:ncanoCumula3/claude-workspace"
  "$HOME/netsuite:ncanoCumula3/netsuite"
  "$HOME/Stuff/jerure:ncanoCumula3/jerue"
  "$HOME/Stuff/claude-iphone:ncanoCumula3/claude-iphone"
  "$HOME/nexus_audit:ncanoCumula3/nexus-audit"
  "$HOME/mindgroup-kb:ncanoCumula3/mindgroup-kb"
  "$HOME/oakmore-knit-pipeline:ncanoCumula3/oakmore-knit-pipeline"
  "$HOME/oakmore-billing:ncanoCumula3/oakmore-billing"
  "$HOME/organica_engine:nMindGroup/organica-engine"
)

if [ -z "${GH_TOKEN:-}" ] && ! gh auth status >/dev/null 2>&1; then
  echo ">>> no GitHub credentials; cannot fetch history. Set GH_TOKEN."
  exit 1
fi

# So later pushes authenticate too, rather than prompting for a username on a machine
# with no keyboard attached to the git process.
gh auth setup-git >/dev/null 2>&1 || true
export GIT_TERMINAL_PROMPT=0

linked=0; skipped=0; failed=0
for entry in "${REPOS[@]}"; do
  dir="${entry%%:*}"; slug="${entry#*:}"
  [ -d "$dir" ] || continue
  if [ -d "$dir/.git" ] && [ "$FORCE" -eq 0 ]; then
    skipped=$((skipped+1)); continue
  fi

  tmp=$(mktemp -d)
  # The token goes in the URL for the clone only, and the remote is rewritten to the clean
  # URL afterwards, so it never ends up written into .git/config.
  url="https://github.com/$slug.git"
  # Repositories live under two GitHub accounts, so pick the token that matches the owner
  # rather than assuming one works everywhere. That mismatch is what made organica-engine
  # the single repository that would not clone.
  owner="${slug%%/*}"
  tok="${GH_TOKEN:-}"
  case "$owner" in
    nMindGroup) tok="${GH_TOKEN_NMINDGROUP:-$tok}" ;;
  esac
  auth_url="$url"
  [ -n "$tok" ] && auth_url="https://x-access-token:${tok}@github.com/$slug.git"
  if ! git clone -q "$auth_url" "$tmp/r" 2>/dev/null; then
    echo "  ! $slug — clone failed (no access from this account?)"
    rm -rf "$tmp"; failed=$((failed+1)); continue
  fi
  rm -rf "$dir/.git"
  mv "$tmp/r/.git" "$dir/.git"
  rm -rf "$tmp"

  # Point the index at HEAD without touching the files that were restored. Anything that
  # differs from the remote now reads as a normal uncommitted change.
  git -C "$dir" remote set-url origin "$url" 2>/dev/null || true
  git -C "$dir" reset -q >/dev/null 2>&1 || true
  branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  changes=$(git -C "$dir" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  printf "  linked %-26s %-34s branch=%-12s uncommitted=%s\n" \
         "$(basename "$dir")" "$slug" "$branch" "$changes"
  linked=$((linked+1))
done

echo ">>> linked $linked, already had history $skipped, failed $failed"
[ "$failed" -gt 0 ] && echo ">>> a failure usually means this machine's GitHub account cannot see that repository"
exit 0
