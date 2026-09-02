#!/bin/bash
# Pull the newest workspace backup from GitHub Releases and unpack it into $HOME.
#
# This is what makes the remote machine the same machine: the release asset carries every
# session transcript, every memory, all settings, and every project working directory with
# its tools. The container's home is /Users/nico, the same absolute path as the laptop, so
# Claude Code's per-directory session slugs resolve without renaming anything.
#
#   restore_workspace.sh            restore if the workspace looks empty
#   restore_workspace.sh --force    restore over whatever is there
#
# Needs GH_TOKEN with read access to the release repository.
set -uo pipefail

REPO="${BACKUP_REPO:-ncanoCumula3/jerue}"
MARKER="$HOME/.workspace-restored"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

log() { echo ">>> restore: $*"; }

# The laptop can ask for a pull by setting RESTORE_ON_BOOT on the service:
#   force      pull, without overwriting anything changed here
#   overwrite  pull, and let the archive win
case "${RESTORE_ON_BOOT:-}" in
  overwrite) FORCE=1; OVERWRITE=1 ;;
  force)     FORCE=1 ;;
esac

if [ -f "$MARKER" ] && [ "$FORCE" -eq 0 ]; then
  log "already restored on $(cat "$MARKER" 2>/dev/null). --force to redo."
  exit 0
fi

if [ -z "${GH_TOKEN:-}" ]; then
  log "GH_TOKEN is not set, so the backup cannot be fetched. Skipping."
  log "Set GH_TOKEN in the service environment, then run: restore_workspace.sh --force"
  exit 0
fi

API="https://api.github.com/repos/$REPO/releases"
log "looking for the newest backup release in $REPO"

# Newest release whose tag starts with backup-, and its first asset.
read -r TAG ASSET_ID ASSET_NAME <<<"$(
  curl -fsSL -H "Authorization: Bearer $GH_TOKEN" \
       -H "Accept: application/vnd.github+json" "$API?per_page=30" |
  python3 -c '
import json,sys
rel = [r for r in json.load(sys.stdin) if r["tag_name"].startswith("backup-") and r["assets"]]
if not rel:
    sys.exit(1)
r = sorted(rel, key=lambda x: x["tag_name"], reverse=True)[0]
a = r["assets"][0]
print(r["tag_name"], a["id"], a["name"])
' 2>/dev/null)"

if [ -z "${TAG:-}" ]; then
  log "no backup release found. Skipping."
  exit 0
fi
log "found $TAG -> $ASSET_NAME"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "downloading (this is a few hundred MB, once)"
if ! curl -fsSL -H "Authorization: Bearer $GH_TOKEN" \
        -H "Accept: application/octet-stream" \
        -o "$TMP/w.zip" "$API/assets/$ASSET_ID"; then
  log "download failed. Leaving the workspace as it is."
  exit 0
fi
log "downloaded $(du -h "$TMP/w.zip" | cut -f1)"

# Unpack into HOME. -n never clobbers, so a --force restore adds what is missing and
# leaves anything worked on here alone. Use -o only when you truly want the backup to win.
UNZIP_FLAGS="-n"
[ "$FORCE" -eq 1 ] && [ "${OVERWRITE:-0}" = "1" ] && UNZIP_FLAGS="-o"
log "unpacking into $HOME with $UNZIP_FLAGS"
(cd "$HOME" && unzip -q $UNZIP_FLAGS "$TMP/w.zip") || log "unzip reported problems, continuing"

# Session slugs are the working-directory path with / replaced by -. They only resolve if
# home matches. It does here, but if the image is ever rebuilt under a different home this
# is what would need to change, so check it out loud rather than silently.
if [ "$HOME" != "/Users/nico" ]; then
  log "WARNING: home is $HOME, not /Users/nico. Past sessions will not be found."
  log "         Rename the folders under ~/.claude/projects to match this path."
fi

date '+%Y-%m-%d %H:%M' > "$MARKER"
SESS=$(find "$HOME/.claude/projects" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
MEMS=$(find "$HOME/.claude/projects" -path '*/memory/*.md' 2>/dev/null | wc -l | tr -d ' ')
log "done. $SESS session transcripts, $MEMS memories."
log "resume a past session with:  claude --resume"
