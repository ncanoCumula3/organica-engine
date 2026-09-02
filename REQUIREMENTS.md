# What the remote machine has to do

Taken from the 139 session transcripts on the laptop, not from guesswork. Counts are
occurrences across every session.

## The two things that broke it last time

**A browser has to actually open.** `suitecloud account:setup` (372 uses) authenticates by
opening a browser at NetSuite and completing OAuth there. `setup_auth.exp` (340 uses) is an
expect script that drives that prompt but still needs the browser to appear and be
finished by a human. A headless container has nowhere to put that window, so SDF auth
cannot complete and every `project:deploy` (776) and `file:upload` (688) after it fails.

**Browser automation is not incidental, it is a third of the testing.** selenium 1,392 ·
webdriver 1,405 · chrome 1,419 · chromedriver 738 · playwright 896. The house testing rule
is a real Chrome, driven by Selenium, on its own `--user-data-dir`, launched once with
`--remote-debugging-port=9222` and attached to on later runs rather than restarted.

Both needs are answered by the same thing: a real X display with a real Chrome on it,
reachable from the phone.

## Requirements

| Need | Evidence | Provided by |
|---|---|---|
| A visible browser for OAuth | `account:setup` 372, `setup_auth.exp` 340 | Xvfb + fluxbox + x11vnc + noVNC, reachable at `/vnc/` |
| Chrome for Selenium, persistent, attachable | selenium 1,392, `--remote-debugging-port` 109, `--user-data-dir` 93 | Google Chrome stable + chromedriver, started on display `:0` and left running |
| Playwright | 896 | `playwright` with its chromium bundle |
| SuiteCloud CLI + Java | suitecloud 2,789 | `@oracle/suitecloud-cli`, `default-jre-headless` |
| expect, to drive the SDF prompts | 4,800 | `expect` |
| SuiteQL and RESTlet calls | SuiteQL 7,220, restlet 6,678 | Python + `requests`, `requests-oauthlib`. No browser needed for these |
| Python, heavily | 9,192 `python3` calls | 3.11 with pandas, numpy, openpyxl, matplotlib, selenium, pillow, pdfplumber, psycopg2, boto3, streamlit |
| Node | node 188, npx 157 | Node 20 |
| Spreadsheet and document rendering | `soffice` 32 | LibreOffice headless |
| Persistent terminal across reloads | tmux throughout | tmux under ttyd |
| Git and GitHub | git 1,322, gh 355 | git, `gh` |

## Access from the phone

Render exposes one port, so nginx sits on it and routes:

- `/` the terminal (ttyd → tmux). This is where Claude Code runs.
- `/vnc/` the desktop (noVNC → x11vnc → Xvfb). This is where the browser window appears.

Both behind the same basic-auth credentials, so the desktop is never open to the internet.

## How SDF auth works here

1. In the terminal: `cd ~/netsuite/acct-XXXX && suitecloud account:setup`
2. It opens Chrome on the virtual display.
3. Switch Safari to `/vnc/`, complete the NetSuite login and 2FA there.
4. Back to `/`, the CLI has its token. `project:deploy` and `file:upload` work from then on.

The token lands in `~/.suitecloud-sdk`, which is on the persistent disk, so this is a
once-per-account job rather than once per container.

Where an account has TBA tokens already, `suitecloud account:savetoken` skips the browser
entirely and is the better path for anything scripted.

## NetSuite credentials

Two paths, both covered, neither needing anything typed twice.

**Token auth** is the dominant one: SuiteQL 7,220 uses and RESTlets 6,678, none of which
open a browser. All of it reads `NS_*` from the environment. Those values now live in one
file, `~/.netsuite/accounts.json`, mode 600, on the persistent disk. `nscreds` manages it
and every new shell exports the default account automatically, so the existing tools run
unchanged.

    nscreds list                      every account, secrets masked
    nscreds import <path/.env> --as jer-prod    fold in an existing env file
    nscreds use jer-sb1               switch the default
    nscreds check                     which accounts are complete, and the file mode

The file can be edited at any time and takes effect in the next shell. It is gitignored
and is not part of any backup archive, because the archive is built on the laptop.

**Browser login** is for the NetSuite UI and for the OAuth step of
`suitecloud account:setup`. Chrome's profile directory is on the persistent disk, so once
you have signed in once through `/vnc/`, Chrome keeps the session and the saved password
exactly as it does on the laptop. An email and password can also be stored per account as
a fallback for when that session has expired.
