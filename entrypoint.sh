#!/bin/bash
# Container entrypoint: put state on the persistent disk, bring up the desktop, then serve
# the terminal and the desktop through one port.
set -e

# Everything that must survive a container restart. The project directories are here so
# work done from the phone is not lost when Render recycles the container.
PERSIST=".claude .config .suitecloud-sdk .ssh .cache .netsuite chrome-profile netsuite claude Stuff
         mindgroup-kb organica_engine oakmore-knit-pipeline oakmore-billing kgs_analysis
         oa_migration pvms-site tools"

if [ ! -f /data/.seeded ]; then
  echo ">>> First boot: seeding the persistent disk"
  for d in $PERSIST; do
    if [ -d "/Users/nico/$d" ] && [ ! -d "/data/$d" ]; then mv "/Users/nico/$d" "/data/$d"; fi
  done
  touch /data/.seeded
fi

for d in $PERSIST; do
  mkdir -p "/data/$d"
  if [ ! -L "/Users/nico/$d" ]; then
    rm -rf "/Users/nico/$d"
    ln -sf "/data/$d" "/Users/nico/$d"
  fi
done
chown -R nico:nico /Users/nico /data 2>/dev/null || true

# ---------------------------------------------------------------- the desktop
# Xvfb gives a screen with nothing attached to it; fluxbox gives windows something to be
# managed by; x11vnc exports the screen; websockify wraps it for the browser. Without this
# stack there is nowhere for a browser window to appear, which is what stopped SuiteCloud
# OAuth working before.
echo ">>> starting the virtual display"
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 2>/dev/null || true
Xvfb :0 -screen 0 ${SCREEN_GEOMETRY:-1280x800x16} -nolisten tcp >/tmp/xvfb.log 2>&1 &
for _ in $(seq 1 30); do xdpyinfo -display :0 >/dev/null 2>&1 && break; sleep 0.5; done

# A desktop session, not just a window manager: a panel, a file manager and a menu, so
# it behaves like a machine rather than a bare X root window.
sudo -u nico env DISPLAY=:0 HOME=/Users/nico XDG_CURRENT_DESKTOP=XFCE \
     dbus-launch --exit-with-session startxfce4 >/tmp/xfce.log 2>&1 &
# The desktop needs its own password, because the websocket cannot be covered by the
# terminal's basic auth. Same password as the terminal by default, so there is only one to
# remember; VNC_PASSWORD overrides it. Truncated to 8 characters, which is all the VNC
# protocol carries.
VNC_PW="${VNC_PASSWORD:-$TTYD_PASSWORD}"
mkdir -p /tmp/vnc
x11vnc -storepasswd "$(printf '%.8s' "$VNC_PW")" /tmp/vnc/passwd >/dev/null 2>&1
x11vnc -display :0 -forever -shared -rfbauth /tmp/vnc/passwd -quiet -rfbport 5900 \
       -noxdamage -nolookup -threads -defer 30 -wait 30 >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/novnc.log 2>&1 &

# noVNC's landing page asks which client to use; go straight to the desktop instead.
ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html 2>/dev/null || true

# ---------------------------------------------------------------- auth
: "${TTYD_USER:=nico}"
if [ -z "${TTYD_PASSWORD:-}" ]; then
  echo "!! TTYD_PASSWORD is not set. Refusing to expose a terminal and a desktop"
  echo "!! to the internet without a password. Set it in the service environment."
  exit 1
fi
htpasswd -bc /tmp/htpasswd "$TTYD_USER" "$TTYD_PASSWORD" >/dev/null 2>&1
chmod 644 /tmp/htpasswd

# ---------------------------------------------------------------- bootstrap
# Deliberately in the background. The first boot restores a ~450MB workspace archive,
# which took six minutes, and running it before nginx meant the port was not bound in
# time and the platform failed the deploy even though the container was healthy. The
# health endpoint has to answer within seconds; the restore can finish behind it.
(
  sudo -u nico --preserve-env=ANTHROPIC_API_KEY,GH_TOKEN,BACKUP_REPO,DISPLAY,CLAUDE_CREDENTIALS,RESTORE_ON_BOOT \
       /usr/local/bin/bootstrap.sh 2>&1 | sed 's/^/[bootstrap] /'
  echo "[bootstrap] finished"
  touch /tmp/.bootstrap-done
) &

# ---------------------------------------------------------------- serve
# ttyd on a private port; nginx owns the public one and routes to ttyd and noVNC.
ttyd -p 7681 -i 127.0.0.1 -W \
     -t 'titleFixed=claude-iphone' -t 'fontSize=14' \
     sudo -u nico --preserve-env=ANTHROPIC_API_KEY,GH_TOKEN,BACKUP_REPO,DISPLAY \
          -i tmux new-session -A -s main >/tmp/ttyd.log 2>&1 &

sed "s/__PORT__/${PORT:-10000}/" /etc/nginx/nginx.conf.template > /tmp/nginx.conf
echo ">>> terminal at /   ·   desktop at /vnc/   ·   listening on ${PORT:-10000}"
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
