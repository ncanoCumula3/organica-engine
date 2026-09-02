#!/bin/bash
# Put this machine on the private network, and expose RDP and SSH over it.
#
# This is the piece that lets native iPhone apps in. The hosting platform publishes a
# single HTTP port, so Microsoft Remote Desktop and an SSH client have nothing to connect
# to. Tailscale gives the container a private address the phone can reach directly, and
# the desktop and shell are served over that rather than over the internet.
#
# A container has no /dev/net/tun and no NET_ADMIN, so tailscaled runs in userspace
# networking mode. That is a supported configuration; `tailscale serve` still forwards TCP
# to services on localhost, which is all that is needed here.
set -uo pipefail
say() { echo ">>> tailnet: $*"; }

[ -n "${TS_AUTHKEY:-}" ] || { say "no TS_AUTHKEY set; skipping. Browser access still works."; exit 0; }
command -v tailscale >/dev/null || { say "tailscale is not installed"; exit 0; }

mkdir -p /data/tailscale
tailscaled --state=/data/tailscale/tailscaled.state \
           --socket=/var/run/tailscale/tailscaled.sock \
           --tun=userspace-networking >/tmp/tailscaled.log 2>&1 &

for _ in $(seq 1 30); do
  tailscale --socket=/var/run/tailscale/tailscaled.sock status >/dev/null 2>&1 && break
  sleep 1
done

tailscale --socket=/var/run/tailscale/tailscaled.sock up \
  --authkey "$TS_AUTHKEY" \
  --hostname "${TS_HOSTNAME:-workstation}" \
  --accept-routes >/dev/null 2>&1 \
  && say "joined as ${TS_HOSTNAME:-workstation}" \
  || { say "could not join; see /tmp/tailscaled.log"; exit 0; }

# Forward the two ports the phone apps need. Both listen on loopback only, so they are
# reachable over the private network and from nowhere else.
tailscale --socket=/var/run/tailscale/tailscaled.sock serve --bg --tcp 3389 tcp://127.0.0.1:3389 >/dev/null 2>&1 \
  && say "rdp on 3389" || say "rdp forward failed"
tailscale --socket=/var/run/tailscale/tailscaled.sock serve --bg --tcp 2222 tcp://127.0.0.1:22 >/dev/null 2>&1 \
  && say "ssh on 2222" || say "ssh forward failed"

IP=$(tailscale --socket=/var/run/tailscale/tailscaled.sock ip -4 2>/dev/null | head -1)
say "private address: ${IP:-unknown}"
