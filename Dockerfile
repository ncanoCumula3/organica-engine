# Node 22, not 20. The Claude Code CLI requires >= 22.12.0; on Node 20 npm warns
# EBADENGINE and the install is not usable, which defeats the purpose of the machine.
FROM node:22-bookworm

# Mirror the macOS path layout so every hard-coded /Users/nico/... path in memories,
# tools and SuiteCloud projects works unchanged. It is also what makes Claude Code find
# past sessions: history is stored per working directory, in a folder named after that
# directory's absolute path, so the home path has to match the laptop exactly.
ENV HOME=/Users/nico
ENV DISPLAY=:0
ARG TARGETARCH
ARG DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- base system
#   default-jre-headless  SuiteCloud CLI needs Java 11+
#   expect                drives the SuiteCloud auth prompts (setup_auth.exp)
#   libreoffice           spreadsheet and document rendering (soffice)
#   tini                  proper PID 1 and signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
      default-jre-headless python3 python3-pip python3-venv python3-dev build-essential \
      git curl wget ca-certificates openssh-client tmux tini sudo less vim nano jq unzip zip \
      expect procps rsync file locales fonts-liberation fonts-dejavu \
      libreoffice-calc libreoffice-writer libreoffice-impress \
  && sed -i 's/# en_GB.UTF-8/en_GB.UTF-8/' /etc/locale.gen && locale-gen \
  && rm -rf /var/lib/apt/lists/*
ENV LANG=en_GB.UTF-8

# ---------------------------------------------------------------- the desktop
# A real X display, a light window manager, a VNC server and noVNC to reach it from
# mobile Safari. This is the piece that was missing: without somewhere for a browser
# window to appear, SuiteCloud OAuth cannot be completed and Selenium has no screen.
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc xterm x11-utils x11-xserver-utils dbus-x11 \
      xfce4 xfce4-terminal xfce4-panel xfce4-session thunar \
      novnc websockify nginx apache2-utils \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- Chrome
# Google Chrome stable on amd64; Chromium on arm64, where Google publishes no build.
# Chromedriver is matched to whichever one landed.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    if [ "$arch" = "amd64" ]; then \
      curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg; \
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list; \
      apt-get update && apt-get install -y --no-install-recommends google-chrome-stable; \
      ln -sf /usr/bin/google-chrome-stable /usr/local/bin/chrome; \
    else \
      apt-get update && apt-get install -y --no-install-recommends chromium chromium-driver; \
      ln -sf /usr/bin/chromium /usr/local/bin/chrome; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- Node tooling
# Installed as two steps, not one, and with output turned up. A combined silent install
# hung twice with no log line to say which package was responsible; separating them makes
# the next failure legible. CI=true and the yes flag stop any postinstall script waiting
# on a prompt that a build has no way to answer.
ENV CI=true npm_config_yes=true npm_config_fund=false npm_config_audit=false
RUN npm install -g --loglevel=http @anthropic-ai/claude-code \
 && node -e "console.log('claude-code installed on node', process.version)"
RUN npm install -g --loglevel=http --ignore-scripts @oracle/suitecloud-cli \
 && (suitecloud --version || echo 'suitecloud installed; version check deferred to runtime')

# ---------------------------------------------------------------- Python tooling
# The set actually used across the sessions: analysis, spreadsheets, plotting, browser
# automation, NetSuite REST and TBA signing, Postgres, imaging, PDF table extraction.
RUN pip3 install --no-cache-dir --break-system-packages \
      requests requests-oauthlib psycopg2-binary psycopg[binary] \
      pandas numpy openpyxl matplotlib pillow lxml pyyaml certifi \
      selenium webdriver-manager playwright pdfplumber boto3 \
      streamlit plotly google-api-python-client google-auth
# Playwright's own browser is not pre-downloaded: Chrome is already here and is what the
# sessions actually drive. If a Playwright script needs it:  playwright install chromium

# ---------------------------------------------------------------- GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y --no-install-recommends gh \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- ttyd
RUN ARCH=$(dpkg --print-architecture) \
  && case "$ARCH" in amd64) TTYD_ARCH=x86_64;; arm64) TTYD_ARCH=aarch64;; *) TTYD_ARCH=$ARCH;; esac \
  && curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${TTYD_ARCH}" -o /usr/local/bin/ttyd \
  && chmod +x /usr/local/bin/ttyd

# ---------------------------------------------------------------- user
RUN useradd -m -d /Users/nico -s /bin/bash nico \
  && echo 'nico ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/nico \
  && mkdir -p /Users/nico/.claude /Users/nico/.config /Users/nico/.suitecloud-sdk \
              /Users/nico/netsuite /Users/nico/claude /Users/nico/.ssh \
              /Users/nico/chrome-profile \
  && chown -R nico:nico /Users/nico

VOLUME /data

COPY entrypoint.sh        /usr/local/bin/entrypoint.sh
COPY bootstrap.sh         /usr/local/bin/bootstrap.sh
COPY restore_workspace.sh /usr/local/bin/restore_workspace.sh
COPY start_chrome.sh      /usr/local/bin/start_chrome.sh
COPY nscreds              /usr/local/bin/nscreds
COPY ns_login.py          /usr/local/bin/ns_login.py
COPY relink_git.sh        /usr/local/bin/relink_git.sh
COPY nginx.conf.template  /etc/nginx/nginx.conf.template
COPY phone/               /usr/share/claude-phone/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/bootstrap.sh \
             /usr/local/bin/restore_workspace.sh /usr/local/bin/start_chrome.sh \
             /usr/local/bin/nscreds /usr/local/bin/ns_login.py \
             /usr/local/bin/relink_git.sh

EXPOSE 10000
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
