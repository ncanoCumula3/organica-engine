#!/usr/bin/env python3
"""Organica from the shell: drives the app's own Chat terminal headlessly, so an orchestrator
(a person or an agent) runs the same commands the page offers and reads the replies as text.
Runs on the machine that hosts the container, or anywhere with ORGA_URL pointing at it
(through an SSH tunnel: ORGA_URL=http://127.0.0.1:8501). Needs playwright with chromium.

  orga.py "/status"                         one command
  orga.py "/load demo" "/run" "/case price_power"      several, one session, in order
  orga.py "upload data /data/luna/x.xlsx"   a file into the Data page (Data-room file uploader)
  orga.py "upload extracts /data/dwh/MART_SALES/FCT_SALES_LEADS.csv" ...   Data analysis extracts
  orga.py "page Audit"                      open a page and print its text
  orga.py "shot /tmp/x.png"                 screenshot the current page
  orga.py "ask <question>"                  same as a plain line in the terminal
Everything else is sent to the Chat terminal verbatim (commands start with /). Prints the
assistant's reply text. The admin login is read from ~/organica_run/.env on this machine."""
import sys, os, re, time, json
from playwright.sync_api import sync_playwright
URL=os.environ.get("ORGA_URL","http://127.0.0.1:8501"); TIMEOUT=int(os.environ.get("ORGA_TIMEOUT","240"))
# login: ORGA_USER / ORGA_PW in the environment, else the admin entry of ORGANICA_USERS in the
# container env file next to the deployment (~/organica_run/.env on a client machine)
USER=os.environ.get("ORGA_USER","admin"); PW=os.environ.get("ORGA_PW")
if not PW:
    envf=os.path.expanduser(os.environ.get("ORGA_ENV","~/organica_run/.env"))
    env=dict(l.split("=",1) for l in open(envf).read().splitlines() if "=" in l)
    PW=[u for u in env["ORGANICA_USERS"].split(",") if u.startswith(USER+":")][0].split(":")[1]
def settle(page, t=1.5):
    """wait until Streamlit stops running"""
    time.sleep(t); end=time.time()+TIMEOUT
    while time.time()<end:
        running = page.locator('[data-testid="stStatusWidget"]').count() or page.locator('text=Running').count()
        if not running: return
        time.sleep(1)
def main_text(page, n=6000):
    """Streamlit has no <main>; the page body is the app view container."""
    for sel in ('[data-testid="stAppViewContainer"]', '[data-testid="stMain"]', "body"):
        if page.locator(sel).count(): return page.locator(sel).first.inner_text()[:n]
    return ""
def goto_page(page, name):
    page.get_by_text(name, exact=True).first.click(); settle(page, 2)
def msgs(page): return page.locator('[data-testid="stChatMessage"]')
def send(page, text):
    before=msgs(page).count()
    box=page.get_by_placeholder(re.compile("A command such as"))
    box.fill(text); box.press("Enter")
    end=time.time()+TIMEOUT
    while time.time()<end:
        time.sleep(1)
        n=msgs(page).count()
        if n>=before+2 and not page.locator('[data-testid="stStatusWidget"]').count(): break
    settle(page, 1)
    out=msgs(page).nth(msgs(page).count()-1).inner_text()
    return out
def upload(page, where, path):
    goto_page(page, "Data" if where=="data" else "Data analysis")
    label = "Data-room file" if where=="data" else "Source extracts"
    inp=page.locator(f'[data-testid="stFileUploader"]:has-text("{label}") input[type=file]').first
    inp.set_input_files(path); settle(page, 3)
    return main_text(page, 1500)
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1400,"height":1000})
    pg.goto(URL, wait_until="domcontentloaded"); settle(pg, 4)
    pg.locator('input[aria-label="User"]').fill(USER); pg.locator('input[aria-label="Password"]').fill(PW)
    pg.get_by_role("button", name="Sign in").click(); settle(pg, 4)
    assert "signed in as" in pg.inner_text("body"), "login failed"
    on_terminal=False
    for raw in sys.argv[1:]:
        a=raw.strip(); print(f"\n$ {a}")
        if a.startswith("upload "):
            _, where, path = a.split(" ",2); print(upload(pg, where, path)); on_terminal=False
        elif a.startswith("page "):
            goto_page(pg, a[5:]); print(main_text(pg)); on_terminal=False
        elif a.startswith("shot "):
            pg.screenshot(path=a[5:], full_page=True); print("saved", a[5:])
        else:
            if not on_terminal: goto_page(pg, "Chat terminal"); on_terminal=True
            print(send(pg, a[4:] if a.startswith("ask ") else a))
    b.close()
