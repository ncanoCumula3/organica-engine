#!/usr/bin/env python3
"""Sign Chrome into NetSuite on the virtual display, once, so it stays signed in.

The laptop never types NetSuite credentials: they are saved in Chrome and the session is
just there. The remote machine starts with an empty profile, so it needs signing in once.
After that the profile lives on the persistent disk and behaves exactly like the laptop.

Credentials come from the credentials store, never from the command line, so they do not
land in shell history or in a session transcript:

    nscreds set jer-sb1 ui_email=you@example.com ui_password='...'
    ns_login.py jer-sb1

    ns_login.py jer-sb1 --check     only report whether the session is already good

Two-factor prompts are not automated. When one appears the script says so and leaves the
browser sitting on it, for you to finish at /vnc/ from the phone. That is a one-time step
per account.
"""
import argparse
import json
import os
import sys
import time

STORE = os.path.expanduser("~/.netsuite/accounts.json")


def account(name):
    if not os.path.exists(STORE):
        sys.exit(f"no credentials store at {STORE}. Run: nscreds add {name} --account-id ...")
    doc = json.load(open(STORE))
    name = name or doc.get("default")
    a = doc.get("accounts", {}).get(name or "")
    if not a:
        sys.exit(f"no account named {name!r}. Run: nscreds list")
    return name, a


def driver(debug_port):
    """Attach to the long-lived Chrome rather than starting a second one."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    o.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
    return webdriver.Chrome(options=o)


def logged_in(d) -> bool:
    """effects: True when the current page is an authenticated NetSuite page."""
    url = d.current_url.lower()
    if "login" in url or "/pages/customerlogin" in url:
        return False
    body = ""
    try:
        body = d.find_element("tag name", "body").text.lower()
    except Exception:
        pass
    return "app.netsuite.com" in url and "password" not in body[:400]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", nargs="?", help="account name in the credentials store")
    p.add_argument("--check", action="store_true", help="report state, change nothing")
    p.add_argument("--debug-port", default=os.environ.get("CHROME_DEBUG_PORT", "9222"))
    args = p.parse_args()

    name, a = account(args.name)
    acct = a.get("NS_ACCOUNT_ID", "")
    if not acct:
        sys.exit(f"{name} has no NS_ACCOUNT_ID")
    host = acct.lower().replace("_", "-")
    home = f"https://{host}.app.netsuite.com/app/center/card.nl"

    try:
        d = driver(args.debug_port)
    except Exception as exc:
        sys.exit(f"cannot attach to Chrome on port {args.debug_port}: {exc}\n"
                 f"Start it first:  start_chrome.sh")

    d.switch_to.new_window("tab")
    d.get(home)
    time.sleep(6)

    if logged_in(d):
        print(f"  {name}: already signed in ({d.current_url[:70]})")
        return 0
    if args.check:
        print(f"  {name}: NOT signed in")
        return 1

    email, pw = a.get("ui_email"), a.get("ui_password")
    if not (email and pw):
        print(f"  {name}: not signed in, and no ui_email / ui_password stored.")
        print(f"  Either finish the sign-in yourself at /vnc/, or store them:")
        print(f"    nscreds set {name} ui_email=you@example.com ui_password='...'")
        return 2

    from selenium.webdriver.common.by import By
    try:
        for by, sel in ((By.ID, "email"), (By.NAME, "email"),
                        (By.CSS_SELECTOR, "input[type=email]")):
            f = d.find_elements(by, sel)
            if f:
                f[0].clear(); f[0].send_keys(email); break
        else:
            print("  could not find the email field; finish it at /vnc/"); return 2

        for by, sel in ((By.ID, "password"), (By.NAME, "password"),
                        (By.CSS_SELECTOR, "input[type=password]")):
            f = d.find_elements(by, sel)
            if f:
                f[0].clear(); f[0].send_keys(pw); break
        else:
            print("  could not find the password field; finish it at /vnc/"); return 2

        for by, sel in ((By.ID, "submitButton"), (By.CSS_SELECTOR, "button[type=submit]"),
                        (By.CSS_SELECTOR, "input[type=submit]")):
            b = d.find_elements(by, sel)
            if b:
                b[0].click(); break
        time.sleep(9)
    except Exception as exc:
        print(f"  sign-in attempt failed: {exc}")
        print("  finish it at /vnc/ instead"); return 2

    if logged_in(d):
        print(f"  {name}: signed in. Chrome keeps this on the persistent disk, so it")
        print(f"  survives restarts the way the laptop does.")
        return 0

    body = ""
    try:
        body = d.find_element("tag name", "body").text.lower()
    except Exception:
        pass
    if any(w in body for w in ("verification", "two-factor", "security code", "authenticator")):
        print(f"  {name}: credentials accepted, two-factor is waiting.")
        print(f"  Open /vnc/ on the phone and finish it. One time only.")
        return 3
    print(f"  {name}: not signed in, and no 2FA prompt detected. Look at /vnc/.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
