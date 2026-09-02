#!/bin/bash
# Idempotent first-time setup. Runs at every container boot but only acts when
# state is missing. Safe to re-run.
set -e

cd "$HOME"

# Memory dir: where Claude Code stores user/feedback/project/reference notes.
# The path is derived from cwd: -Users-nico is what Claude Code uses when
# you start `claude` inside /Users/nico. Make sure the dir exists so the
# auto-memory system has somewhere to write.
mkdir -p "$HOME/.claude/projects/-Users-nico/memory"
mkdir -p "$HOME/.claude/projects/-Users-nico/tool-results"

# NetSuite credentials. The store lives on the persistent disk at ~/.netsuite/accounts.json
# and is the single place account tokens are kept. If the service environment carries a
# set of NS_* values and the store has no account of that name yet, fold them in once so a
# fresh container is usable without typing anything.
# ---- Claude Code: same account as the laptop -------------------------------
# On macOS the OAuth credentials sit in the login keychain; on Linux they are a file.
# CLAUDE_CREDENTIALS carries the same blob so this machine signs in as the same user
# rather than asking for a fresh login. The file is written 0600 and only if absent, so a
# token this machine has already refreshed for itself is never clobbered.
if [ -n "${CLAUDE_CREDENTIALS:-}" ] && [ ! -f "$HOME/.claude/.credentials.json" ]; then
  mkdir -p "$HOME/.claude"
  umask 077
  printf '%s' "$CLAUDE_CREDENTIALS" > "$HOME/.claude/.credentials.json"
  chmod 600 "$HOME/.claude/.credentials.json"
  echo ">>> Claude Code credentials installed from the service environment"
fi

# Skip the permission prompt, matching the laptop's own setting. A prompt per tool call is
# unusable from a phone. The machine is reachable only behind the terminal password, which
# is what makes this an acceptable trade rather than a reckless one.
SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"
python3 - "$SETTINGS" <<'PYEOF' || true
import json, os, sys
path = sys.argv[1]
try:
    d = json.load(open(path))
except Exception:
    d = {}
changed = False
if not d.get("skipDangerousModePermissionPrompt"):
    d["skipDangerousModePermissionPrompt"] = True; changed = True
if changed:
    json.dump(d, open(path, "w"), indent=2)
    print(">>> claude: permission prompt disabled for this machine")
PYEOF

# `claude` on its own runs without asking, which is the only workable mode from a phone.
if ! grep -q "alias claude=" "$HOME/.bashrc" 2>/dev/null; then
  echo "alias claude='claude --dangerously-skip-permissions'" >> "$HOME/.bashrc"
fi

mkdir -p "$HOME/.netsuite"
if [ -n "${NS_ACCOUNT_ID:-}" ] && [ -n "${NS_CONSUMER_KEY:-}" ]; then
  NAME="${NS_ACCOUNT_NAME:-default}"
  if ! nscreds show "$NAME" >/dev/null 2>&1; then
    echo ">>> seeding NetSuite account '$NAME' from the service environment"
    nscreds add "$NAME" --account-id "$NS_ACCOUNT_ID" --label "seeded from environment" >/dev/null
    nscreds set "$NAME" \
      "NS_CONSUMER_KEY=${NS_CONSUMER_KEY}" "NS_CONSUMER_SECRET=${NS_CONSUMER_SECRET:-}" \
      "NS_TOKEN_ID=${NS_TOKEN_ID:-}" "NS_TOKEN_SECRET=${NS_TOKEN_SECRET:-}" >/dev/null
  fi
fi

# Export the default account into every new shell, so the SuiteQL and RESTlet tools that
# read NS_* from the environment keep working with no per-shell setup.
BRC="$HOME/.bashrc"
if ! grep -q "nscreds env" "$BRC" 2>/dev/null; then
  {
    echo ""
    echo "# NetSuite: export the default account for the tools that read NS_* from the env."
    echo 'if command -v nscreds >/dev/null 2>&1 && [ -f "$HOME/.netsuite/accounts.json" ]; then'
    echo '  eval "$(nscreds env 2>/dev/null)" || true'
    echo "fi"
    echo "alias nsuse='nscreds use'"
  } >> "$BRC"
fi

# Restore the full workspace from the newest backup release: every session transcript,
# every memory, all settings, and every project directory with its tools. Idempotent, and
# a no-op once it has run. The old memory-seed below is only a fallback for the case where
# GH_TOKEN is not set yet.
if [ -x /usr/local/bin/restore_workspace.sh ]; then
  /usr/local/bin/restore_workspace.sh || true
fi

SEED="$HOME/claude/claude-iphone/memory-seed"
if [ -d "$SEED" ] && [ -z "$(ls -A "$HOME/.claude/projects/-Users-nico/memory" 2>/dev/null)" ]; then
  echo ">>> No backup restored; falling back to the committed memory seed"
  cp -n "$SEED"/*.md "$HOME/.claude/projects/-Users-nico/memory/" 2>/dev/null || true
fi

# Login state: print what's authenticated, what isn't.
echo ""
echo "================ claude-iphone status ================"
echo " Working dir:   $HOME"
echo " Disk usage:    $(df -h /data 2>/dev/null | tail -1 | awk '{print $3"/"$2" ("$5")"}' || echo 'no /data')"
echo ""

# Anthropic / Claude Code
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo " ✓ Anthropic API key set via env"
elif [ -f "$HOME/.claude/.credentials.json" ] || [ -f "$HOME/.claude/credentials.json" ] \
     || [ -f "$HOME/.claude.json" ]; then
  echo " ✓ Claude Code logged in (cached creds on disk)"
else
  echo " ✗ Claude Code NOT authenticated. Run:  claude login"
  echo "   (or set CLAUDE_CREDENTIALS on the service to reuse the laptop's account)"
fi

# GitHub
if gh auth status -h github.com >/dev/null 2>&1; then
  echo " ✓ GitHub CLI authenticated as $(gh api user -q .login 2>/dev/null)"
else
  echo " ✗ GitHub NOT authenticated. Run:        gh auth login"
fi

# SuiteCloud (Jerue)
if [ -f "$HOME/.suitecloud-sdk/credentials" ]; then
  AUTHIDS=$(grep -oE '\[[^]]+\]' "$HOME/.suitecloud-sdk/credentials" | tr -d '[]' | tr '\n' ' ')
  echo " ✓ SuiteCloud authids: $AUTHIDS"
else
  echo " ✗ SuiteCloud NOT authenticated. Run inside an SDF project:"
  echo "     suitecloud account:setup"
fi

# Helpful tools
[ -f "$HOME/claude/jerure/tools/.env" ]          && echo " ✓ jerure/tools/.env       (NS sandbox TBA)" || echo " ✗ jerure/tools/.env missing"
[ -f "$HOME/claude/jerure/tools/.jer-prod.env" ] && echo " ✓ jerure/tools/.jer-prod.env (NS prod TBA)"  || echo " ✗ jerure/tools/.jer-prod.env missing"

# Give the restored directories their git history back. The archive carries files but not
# .git, so without this every repository is loose files with nothing to push, and work done
# here could never reach the laptop.
if [ -x /usr/local/bin/relink_git.sh ]; then
  /usr/local/bin/relink_git.sh 2>&1 | sed 's/^/[git] /' || true
fi

# Bring Chrome up on the virtual display and leave it there, per the house rule that the
# test browser is launched once and attached to afterwards.
if [ -n "${DISPLAY:-}" ] && [ -x /usr/local/bin/start_chrome.sh ]; then
  /usr/local/bin/start_chrome.sh >/dev/null 2>&1 || true
fi

SESS=$(find "$HOME/.claude/projects" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
MEMS=$(find "$HOME/.claude/projects" -path '*/memory/*.md' 2>/dev/null | wc -l | tr -d ' ')
echo " Workspace:     $SESS session transcripts, $MEMS memories"
[ -d "$HOME/organica_engine" ] && echo " ✓ organica_engine"        || echo " ✗ organica_engine not restored"
[ -d "$HOME/oakmore-knit-pipeline" ] && echo " ✓ oakmore-knit-pipeline" || echo " ✗ oakmore-knit-pipeline not restored"
echo "======================================================"
if [ -f "$HOME/.netsuite/accounts.json" ]; then
  echo " ✓ NetSuite accounts: $(nscreds list 2>/dev/null | grep -cE '^[* ] [a-z]') stored (nscreds list)"
else
  echo " ✗ No NetSuite accounts yet.  nscreds add <name> --account-id 1234567"
fi
command -v chrome >/dev/null && curl -s --max-time 2 http://127.0.0.1:9222/json/version >/dev/null 2>&1 \
  && echo " ✓ Chrome live on :0, debug port 9222 (attach, never relaunch)" \
  || echo " ✗ Chrome not up. Run: start_chrome.sh"
echo "======================================================"
echo " /app/                  the phone launcher — Add to Home Screen from here"
echo " /                      this terminal"
echo " /vnc/                  the desktop, where browser windows appear"
echo ""
echo " suitecloud account:setup   then finish the login at /vnc/"
echo " claude --resume        pick up any past session"
echo " restore_workspace.sh --force   re-pull the newest backup"
echo " ~/.claude/backup_all.sh        push work back so the laptop sees it"
echo " tmux ls / ctrl-b d     sessions survive closing Safari"
echo ""
