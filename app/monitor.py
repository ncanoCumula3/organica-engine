"""Organica scheduled monitor — clear launcher (Streamlit/PyArmor pattern: imports obfuscated logic).
Re-runs every journey on the configured dataset and alerts on CRITICAL breaches.
Run by a Render cron job:  PYTHONPATH=. python app/monitor.py
Env: GROQ_API_KEY (optional, for AI), ALERT_WEBHOOK (optional Slack/webhook URL), MONITOR_DATA (csv path).
"""
import os, sys, json, urllib.request, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import analyses as A, journeys as J, ai
try:
    import store as S, portfolio as PF
except Exception:
    S = PF = None

def _build_R(nd):
    R = {"Revenue quality": A.revenue_quality(nd)}
    ec = A.economics(nd, A.DEFAULTS); R["Unit economics & margin"] = ec
    R["Pricing"] = A.pricing(nd, A.DEFAULTS)
    R["Scenario & stress"] = A.scenario(ec["econ"], A.DEFAULTS)
    R["Self-validation"] = A.validation(ec["econ"], A.DEFAULTS)
    R["Benchmark"] = A.benchmark(R); R["Valuation"] = A.valuation(R)
    return R

def _single():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.environ.get("MONITOR_DATA", os.path.join(root, "examples", "data", "customers.csv"))
    df = pd.read_csv(src)
    m = ai.detect_columns(df)
    nd = A.normalize(df, m["revenue"], m.get("volume"), m.get("tier"), m.get("revenue_is_monthly", True), m.get("customer"))
    R = _build_R(nd); alerts, watch = [], []
    for k in J.JOURNEYS:
        for f in J.run_journey(k, nd, A.DEFAULTS, R)["issues"]:
            (alerts if f["severity"] == "critical" else watch).append((res_label(k, f), f["title"], f["observed"], f["recommendation"]))
    return alerts, watch

def res_label(k, f):
    return J.JOURNEYS[k]["title"]

def _portfolio():
    """Run every journey across every saved portfolio company; label alerts by company."""
    alerts, watch = [], []
    for nm in S.list_companies():
        df, ts, fin = S.load_company(nm)
        if df is None: continue
        try: s = PF.company_status(df, A.DEFAULTS)
        except Exception as e: print(f"  [skip] {nm}: {e}"); continue
        for f in s["issues"]:
            (alerts if f["severity"] == "critical" else watch).append((nm, f["title"], f["observed"], f["recommendation"]))
    return alerts, watch

def run():
    portfolio = bool(S and PF and S.list_companies())
    alerts, watch = (_portfolio() if portfolio else _single())
    stamp = datetime.datetime.utcnow().isoformat(timespec="minutes")
    scope = f"{len(S.list_companies())} companies" if portfolio else "single dataset"
    head = f"Organica monitor · {stamp}Z · {scope} · {len(alerts)} critical / {len(watch)} watch"
    print(head)
    for j, t, o, rec in alerts: print(f"  [CRITICAL] [{j}] {t} ({o}) -> {rec}")
    for j, t, o, rec in watch:  print(f"  [watch]    [{j}] {t} ({o})")
    hook = os.environ.get("ALERT_WEBHOOK")
    if hook and alerts:
        text = head + "\n" + "\n".join(f"• [{j}] {t} ({o}) -> {rec}" for j, t, o, rec in alerts)
        try:
            req = urllib.request.Request(hook, data=json.dumps({"text": text}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "Organica-monitor/1.0"})
            urllib.request.urlopen(req, timeout=15); print("alert sent")
        except Exception as e:
            print("alert failed:", e)
    return alerts, watch

if __name__ == "__main__":
    run()
