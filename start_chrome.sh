#!/bin/bash
# Start one long-lived Chrome on the virtual display, and leave it running.
#
# The house rule is that the test browser is never closed: Chrome is launched once with a
# fixed profile directory and a remote debugging port, and later runs attach to it rather
# than starting a second instance. That is also what makes SuiteCloud OAuth workable, since
# the window is already there when the CLI asks the desktop to open a URL.
#
# --password-store=basic matters more than it looks. On Linux, Chrome keeps saved passwords
# and cookies in the system keyring, and a container has no keyring daemon. Without this
# flag Chrome quietly declines to save anything, so a sign-in would have to be repeated
# after every restart. With it, credentials go into the profile directory, which is on the
# persistent disk, so "save password" behaves the way it does on the laptop.
set -u
PROFILE="${CHROME_PROFILE:-$HOME/chrome-profile}"
PORT="${CHROME_DEBUG_PORT:-9222}"
mkdir -p "$PROFILE"

if curl -s --max-time 2 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
  echo ">>> chrome already up on port $PORT — attach, do not relaunch"
  exit 0
fi

echo ">>> starting chrome on display $DISPLAY, debug port $PORT"
nohup chrome \
  --user-data-dir="$PROFILE" \
  --remote-debugging-port="$PORT" \
  --remote-allow-origins='*' \
  --no-first-run --no-default-browser-check \
  --password-store=basic \
  --disable-dev-shm-usage --disable-gpu --window-size=1280,900 \
  "${1:-about:blank}" >"$HOME/.chrome.log" 2>&1 &

for _ in $(seq 1 30); do
  curl -s --max-time 1 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1 && \
    { echo ">>> chrome ready"; exit 0; }
  sleep 1
done
echo ">>> chrome did not report ready; see $HOME/.chrome.log"
