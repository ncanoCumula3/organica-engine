# claude-iphone

A remote machine that is the same machine. Claude Code on a Render web service, reachable
from mobile Safari, holding every session transcript, every memory and every project
directory from the laptop. The laptop can be shut down.

## Why the sessions actually work

Claude Code stores history per working directory, in a folder named after that directory's
absolute path with the slashes turned into dashes. The container's home is `/Users/nico`,
the same path as the laptop, so those names match and `claude --resume` lists everything.
That is the whole trick, and it is why the home path in the Dockerfile must not change.

## How it stays in sync

On first boot the container pulls the newest `backup-*` release from `ncanoCumula3/jerue`
and unpacks it into `$HOME`. That asset is produced by `~/.claude/make_backup_zip.sh` on
the laptop and carries sessions, memories, settings and every project with its tools.

    restore_workspace.sh --force     pull the newest backup again
    ~/.claude/backup_all.sh          push work done here back, so the laptop sees it

Work flows both ways: the repos have their normal remotes inside the container, so a
commit made from the phone is a commit the laptop pulls.

## What you get

- **ttyd** web terminal at `https://claude-iphone-<hash>.onrender.com` (HTTPS, basic-auth gated)
- **tmux** session that survives browser reloads — close Safari, come back, you're still where you left off
- **Persistent disk** at `/data` — memories, SuiteCloud credentials, SDF projects, and Python tool envs all survive container restarts
- Pre-installed: `claude` (Claude Code CLI), `suitecloud` (SDF CLI), `gh` (GitHub CLI), Python 3 with `requests`/`requests-oauthlib`/`psycopg2-binary`, Java 11, git

## Deploy (one time)

1. **Push this branch** (already done if you're reading this on GitHub).

2. **Render → New + → Blueprint** → select `ncanoCumula3/jerue` → branch `claude-iphone` → **Apply**.

3. Set the env vars on the new service:

   | Key | Value | Required? |
   |---|---|---|
   | `TTYD_USER` | e.g. `nico` | yes (auth) |
   | `TTYD_PASSWORD` | a strong password | **yes** — without it the terminal is open to the internet |
   | `ANTHROPIC_API_KEY` | from console.anthropic.com | optional — skips `claude login` |
   | `GH_TOKEN` | a fine-grained GitHub PAT | optional — skips `gh auth login` |
   | `NS_ACCOUNT_ID` … `NS_TOKEN_SECRET` | TBA tokens | only if you'll run `jerure/tools/*.py` against NetSuite |

4. Wait for the first build (~5 min). Open the URL Render gives you.

## First-time setup inside the container

When you open the URL, you'll get a tmux session. The bootstrap banner tells you what's authenticated.

```bash
# Authenticate Claude Code (skip if you set ANTHROPIC_API_KEY):
claude login

# Authenticate GitHub:
gh auth login          # pick HTTPS, paste a PAT, say "yes" to git credential helper

# Clone the Jerue repo (and any others you work in):
mkdir -p ~/claude && cd ~/claude
gh repo clone ncanoCumula3/jerue
cd jerue
suitecloud account:setup    # browser OAuth — opens a URL you finish on your phone

# Bring NetSuite SDF projects:
mkdir -p ~/netsuite && cd ~/netsuite
gh repo clone ncanoCumula3/jerue netsuite-jerue   # or however you've structured it

# Start working with Claude:
cd ~
claude
```

Everything you do under `~/.claude/`, `~/.suitecloud-sdk/`, `~/.config/`, `~/.ssh/`, `~/netsuite/`, and `~/claude/` lands on the persistent disk and survives restarts.

## How memories work

The auto-memory system writes to `~/.claude/projects/-Users-nico/memory/`. The `memory-seed/` directory in this repo holds a snapshot of your laptop's memories at deploy time; on first boot, `bootstrap.sh` copies them into the persistent disk **only if no memories exist yet**. After that, the remote machine's memories evolve independently.

If you want to refresh from your laptop:

```bash
# On your iPhone shell:
rm -rf ~/.claude/projects/-Users-nico/memory
# Then re-deploy, OR scp/paste new memory files in.
```

## Manual memory sync (laptop → iPhone)

You can paste a memory file at any time:

```bash
cat > ~/.claude/projects/-Users-nico/memory/MEMORY.md <<'EOF'
...paste content...
EOF
```

Or use `gh` to copy via gist:

```bash
# On laptop:
gh gist create ~/.claude/projects/-Users-nico/memory/*.md -d "memory snapshot"
# On iPhone:
gh gist clone <id> /tmp/mem && cp /tmp/mem/* ~/.claude/projects/-Users-nico/memory/
```

## Cost

Render Standard plan: $25/month + $1/GB-mo for 10 GB disk = **~$26/month**. Stays running 24/7. Drop to Starter ($7/mo) if you don't need always-on and accept cold starts.

## Security notes

- The terminal **is** exposed to the public internet. `TTYD_PASSWORD` is the only thing between strangers and your shell. Pick a long random one.
- All NetSuite TBA tokens, GitHub PATs, and Anthropic keys live in Render's encrypted env vars — never committed to this branch.
- The persistent disk is encrypted at rest by Render.
- If you suspect compromise: rotate `TTYD_PASSWORD`, rotate all tokens, and `Restart Service` — that's it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Build fails on `npm install` | Bump `node:20-bookworm` to `node:22-bookworm` in `Dockerfile` |
| `claude` says "not authenticated" | Run `claude login` once; creds persist on `/data` |
| `suitecloud` can't find Java | Already installed; if missing, `sudo apt-get install -y default-jre-headless` |
| Memories not loading | Check `ls ~/.claude/projects/-Users-nico/memory/` — empty? Run `bash /usr/local/bin/bootstrap.sh` |
| Terminal disconnects on iPhone lock | Reconnect; tmux preserves state. Add the URL to home screen for app-like behavior |
