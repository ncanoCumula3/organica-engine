"""Organica UI. In the deploy build this module is obfuscated; the clear launcher app.py
imports it and calls render() on every Streamlit rerun (PyArmor forbids exec'ing an obfuscated
entry, but importing an obfuscated module + calling a function is fine).
"""
import os, sys, datetime
import pandas as pd, numpy as np, streamlit as st
import plotly.express as px, plotly.graph_objects as go
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyses as A, store as S, gdrive as G, xls_export as X, auth as AU, cases as C, ai as AI, journeys as J, boardpack as BP, icmemo as IM, docs as DOC, netsuite as NS, provenance as PV, icdeck as ID, portfolio as PF, connectors as CX, comps as CM
import dataroom as DR
import credit as CR, icpaper as IPR, holdmonitor as HM, creditrisk as CXR, trace as TR, lenderaudit as LAU
import honesty as HON, trustcopy as TC
import datamap as DM
import datamap_run as DMR
import terminal as TERM
import session_view as SV

ACCENT="#2C5560"; INK="#1A1A1A"; MUTE="#7A7A75"; CLAY="#9C6B4F"; SAGE="#5E7C6E"; LINE="#E6E3DD"
TEAL=ACCENT  # back-compat for helpers
OUT=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"out"); os.makedirs(OUT, exist_ok=True)
st.set_page_config(page_title="Organica", layout="wide")
PLT=dict(template="plotly_white", font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=13),
         margin=dict(l=10,r=10,t=44,b=10), title_font=dict(size=15, color=INK))
ss=st.session_state

# ---------------- helpers ----------------
def autoload(raw):
    # A new dataset is a new run, so the honesty list starts empty. The reading recorded with
    # the engagement is replayed if it still fits the data, which is what makes two runs in
    # separate processes agree; otherwise it is read fresh and recorded.
    HON.reset()
    m=AI.detect_columns(raw, recorded=S.load_mapping())
    S.save_mapping(m)
    ss["raw"]=raw; ss["mapping"]=m; ss["is_demo"]=False
    ss["df"]=A.normalize(raw, m["revenue"], m.get("volume"), m.get("tier"), m.get("revenue_is_monthly",True), m.get("customer"))
    S.save_table("customers", ss["df"]); return m

def load_demo():
    """Load the Verexa sample book, its reporting series and its financials.

    One function because two surfaces load it: the Data page button and the terminal's
    /load demo. Two copies of this drifted apart once already — the terminal loaded the
    book without the time-series, so retention was measured on one route and assumed on
    the other from the same nominal dataset.
    """
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    autoload(pd.read_csv(os.path.join(root,"examples","data","customers.csv")))
    ss["is_demo"]=True
    for key,fn in (("ts","monthly.csv"),("fin","financials.csv")):
        try: ss[key]=pd.read_csv(os.path.join(root,"examples","data",fn))
        except Exception: pass
    ss.pop("results",None)
    return ss["df"]

def show_mapping(raw):
    m=ss.get("mapping",{})
    st.success(f"Loaded {len(ss['df'])} rows · ARR {getattr(A,'CCY','€')}{ss['df'].revenue.sum()/1e6:.2f}m · "
               f"columns recognised by {m.get('_by','?')} ({AI.public_name(m.get('_model')) or '?'})")
    st.caption(f"revenue → {m.get('revenue')} ({'monthly ×12' if m.get('revenue_is_monthly') else 'annual'}) · "
               f"volume → {m.get('volume')} · tier → {m.get('tier')} · customer → {m.get('customer')}")
    with st.expander("Adjust columns (optional — the AI already mapped these)"):
        cols=list(raw.columns)
        rev=st.selectbox("Revenue",cols,index=cols.index(m['revenue']) if m.get('revenue') in cols else 0)
        mon=st.checkbox("monthly (×12)",bool(m.get('revenue_is_monthly',True)))
        vol=st.selectbox("Volume",["(none)"]+cols,index=(cols.index(m['volume'])+1) if m.get('volume') in cols else 0)
        tier=st.selectbox("Tier",["(none)"]+cols,index=(cols.index(m['tier'])+1) if m.get('tier') in cols else 0)
        if st.button("Re-apply"):
            ss["df"]=A.normalize(raw,rev,None if vol=="(none)" else vol,None if tier=="(none)" else tier,mon,m.get("customer"))
            S.save_table("customers",ss["df"]); st.rerun()

def run_all(df):
    a=ss["assump"]; res={}
    res["Revenue quality"]=A.revenue_quality(df)
    ec=A.economics(df,a); res["Unit economics & margin"]=ec
    res["Pricing"]=A.pricing(df,a)
    res["Scenario & stress"]=A.scenario(ec["econ"],a)
    res["Self-validation"]=A.validation(ec["econ"],a)
    if ss.get("ts") is not None:
        try: res["Retention"]=A.retention(ss["ts"])
        except Exception: pass
    res["Benchmark"]=A.benchmark(res,a,comps=ss.get("comps"))
    res["Valuation"]=A.valuation(res,a,comps=ss.get("comps"))
    res["QoE"]=A.qoe(res,a)
    res["Returns (LBO/DCF)"]=A.returns(res,a)
    res["Value creation"]=A.value_creation(res,a,df)
    try: res["Deliverability"]=A.deliverability(res,a)
    except Exception: pass
    try:
        _c=1-ec["econ"]["direct"]/ec["econ"]["rev"]; res["Accounts"]=A.accounts(df, ss.get("ts"), a, _c)
    except Exception: pass
    if ss.get("fin") is not None:
        try: res["Financials"]=A.financials(ss["fin"])
        except Exception: pass
    res["Inconsistencies"]=A.inconsistencies(res)
    return res

def _pinned_terms():
    """Single source of truth for the facility.

    The IC paper used to size the facility off TODAY's run-rate EBITDA while monitoring
    sized it off the approval-month book, so the two disagreed by EUR0.5m (27.9 against
    28.4) and a credit committee would ask why the same facility has two numbers. A drawn
    facility has one amount: it is sized ONCE on the approval-date book and every view
    shares it.
    """
    t=ss["terms"]
    if t.get("quantum"): return t
    try:
        if ss.get("ts") is not None and ss.get("df") is not None:
            mos=HM.months(ss["ts"]); appr=ss.get("appr_month") or mos[0]
            t.update(HM.approval_terms(ss["ts"], ss["df"], appr, ss["assump"], t))
            ss["appr_month"]=appr; ss["facility_basis"]=f"sized on the {appr} book and held there since"
        elif ss.get("df") is not None:
            R=ss.get("results") or run_all(ss["df"])
            t.update(CR.pin_quantum(R, t))
            ss["facility_basis"]="sized on the loaded book; no reporting series supplied"
    except Exception:
        pass
    return t

def _risk_pack(R, a, terms):
    """Monte-Carlo, Bayesian and coherence over the credit ratios. Cached: the simulation is
    40k draws and the Bayesian pass re-runs the stack at every reporting month."""
    key=f"{R['Revenue quality']['kpis']['ARR']}|{R['Unit economics & margin']['kpis']['Fully-loaded margin']}|{terms.get('quantum')}|{terms.get('margin')}|{terms.get('cov_icr')}|{terms.get('cov_leverage')}"
    cache=ss.setdefault("_riskcache", {})
    if key in cache: return cache[key]
    out={}
    try:
        out["mc"]=CXR.monte_carlo(R, a, terms, horizon_years=1.0)
    except Exception:
        return None
    try:
        if ss.get("ts") is not None:
            mos=HM.months(ss["ts"])
            out["bayes"]=CXR.bayesian(ss["ts"], ss["df"], mos, a, terms, 12, R_for_terms=R)
    except Exception:
        pass
    try:
        out["coherence"]=CXR.coherence(R, a, terms, out.get("mc"), out.get("bayes"))
    except Exception:
        pass
    cache[key]=out
    return out

def _dispatch_webhook(finding, brief):
    """POST a remediation brief to ALERT_WEBHOOK (Slack/automation/agent runner). True if sent."""
    hook=os.environ.get("ALERT_WEBHOOK")
    if not hook: return False
    import urllib.request, json
    text=(f"Organica remediation · {finding['title']} · {finding['metric']}={finding['observed']} "
          f"(threshold {finding['threshold']})\n\n{brief[:1600]}")
    try:
        req=urllib.request.Request(hook, data=json.dumps({"text":text}).encode(),
            headers={"Content-Type":"application/json","User-Agent":"Organica/1.0"})
        urllib.request.urlopen(req, timeout=15); return True
    except Exception: return False

def _fig(fig,k):
    fig.update_layout(**PLT); st.plotly_chart(fig,use_container_width=True,key=k)

def chart_for(name, R, suffix=""):
    k=f"ch_{name}_{suffix}"
    if name=="Revenue quality":
        bt=R[name]["series"]["by_tier"]; _fig(px.bar(x=bt.index.astype(str),y=bt.values,labels={"x":"","y":"ARR €"},
            title="ARR by tier",color_discrete_sequence=[ACCENT]),k)
    elif name=="Unit economics & margin":
        stk=R[name]["series"]["stack"]; _fig(px.bar(x=stk.index,y=stk.values,title="Cost stack → EBITDA",
            labels={"x":"","y":"€"},color_discrete_sequence=[ACCENT]),k)
    elif name=="Pricing":
        pr=R[name]["series"]; fig=go.Figure(go.Bar(x=pr["realised"].index.astype(str),y=pr["realised"].values,marker_color=ACCENT))
        fig.add_hline(y=pr["floor"],line_color=CLAY,annotation_text="peer floor"); fig.update_layout(title="Realised price vs peer floor",yaxis_title="€"); _fig(fig,k)
    elif name=="Scenario & stress":
        sm=R[name]["series"]["matrix"]; _fig(px.bar(x=sm.index,y=sm.values,labels={"x":"","y":"EBITDA €m"},
            title="Scenario matrix (EBITDA)",color=sm.index,color_discrete_sequence=[CLAY,ACCENT,SAGE]),k)
    elif name=="Self-validation":
        mc=R[name]["series"]["mc_margin"]; pt=R[name]["series"]["point"]
        fig=px.histogram(x=mc,nbins=60,title="Margin — probabilistic distribution",labels={"x":"Fully-loaded margin %"},color_discrete_sequence=[ACCENT])
        fig.add_vline(x=pt,line_color=CLAY,annotation_text="point estimate"); _fig(fig,k)
    elif name=="Retention":
        br=R[name]["series"]["bridge"]
        _fig(px.bar(x=br.index.astype(str),y=br.values,title="ARR bridge (€m, annualised)",labels={"x":"","y":"€m"},color_discrete_sequence=[ACCENT]),k)
    elif name=="Quality of earnings":
        br=R[name]["series"]["bridge"]
        _fig(px.bar(x=br.index.astype(str),y=br.values,title="QoE bridge (€)",labels={"x":"","y":"€"},color_discrete_sequence=[ACCENT]),k)
    elif name=="Value creation":
        s=R[name]["series"].get("bridge")
        if s is not None and len(s): _fig(px.bar(x=s.index.astype(str),y=s.values,title="Value-creation EV bridge (€m)",labels={"x":"","y":"€m"},color_discrete_sequence=[SAGE]),k)
    elif name=="Financials":
        s=R[name]["series"]["margin"]
        _fig(px.line(x=s.index.astype(str),y=s.values,title="EBITDA margin trend %",labels={"x":"","y":"%"},color_discrete_sequence=[ACCENT]),k)
    elif name=="Deliverability":
        d=R[name]["series"]["decomp"]; cmap={"Base drift":ACCENT,"Cost programme":SAGE,"Enablers (gated)":CLAY,"Pricing (residual)":"#B23A48"}
        fig=go.Figure()
        for lv in d.columns: fig.add_bar(name=lv,x=list(d.index),y=d[lv].values,marker_color=cmap.get(lv,MUTE))
        fig.update_layout(barmode="stack",title="Annual EBITDA step, by lever (€m)",yaxis_title="€m",legend_title=""); _fig(fig,k)

def render_step(name, R, i):
    res=R[name]; cols=st.columns(max(len(res["kpis"]),1))
    for c,(kk,vv) in zip(cols,res["kpis"].items()): c.metric(kk,vv)
    chart_for(name,R,suffix=f"route{i}")
    for tn,td in res.get("tables",{}).items(): st.dataframe(td,use_container_width=True)

def trace_block(expanded=True, key=""):
    """The click-through, wherever the discrepancy is shown.

    It existed on exactly one screen, so a marker clicked anywhere else did nothing. It is
    now one function called from every place the reconciliation appears.
    """
    if ss.get("df") is None or ss.get("ts") is None:
        st.caption("Load the sample book to trace the reconciliation to its sources.")
        return
    try:
        mm=TR.arr_mismatch(ss["df"], ss["ts"])
    except Exception as e:
        st.warning(f"Could not open the source: {e}")
        return
    c=st.columns(3)
    c[0].metric("Customer book", f"€{mm['book']['value']/1e6:.2f}m", f"{mm['book']['rows']:,} rows")
    c[1].metric(f"Reporting series at {mm['series']['month']}", f"€{mm['series']['value']/1e6:.2f}m",
                f"{mm['series']['rows']:,} live customers")
    c[2].metric("Difference", f"€{mm['gap']/1e6:.2f}m", f"{mm['pct']:.1f}% of the book")
    st.markdown("**What explains the difference**")
    st.dataframe(mm["explain"],use_container_width=True,hide_index=True)
    st.caption(f"Every euro of the €{abs(mm['gap']):,.0f} difference is accounted for: the three "
               f"reasons above sum to it, within €{abs(mm['residual']):,.0f} of rounding.")
    t1,t2,t3=st.tabs(["In the book, not live in the series","In both, at a different value",
                      "Every customer, both sources"])
    with t1: st.dataframe(mm["only_book"],use_container_width=True,hide_index=True)
    with t2: st.dataframe(mm["moved"],use_container_width=True,hide_index=True)
    with t3:
        st.dataframe(mm["full"],use_container_width=True,hide_index=True,height=300)
        st.download_button("⬇ Download the full row-by-row comparison (CSV)",
                           mm["full"].to_csv(index=False),"organica_arr_reconciliation.csv",
                           "text/csv",key=f"dl_full_{key}")
    st.markdown("**The two sources themselves**")
    st.dataframe(TR.sources(book=ss["df"], ts=ss.get("ts"), fin=ss.get("fin")),
                 use_container_width=True,hide_index=True)
    sc1,sc2=st.columns(2)
    sc1.download_button("⬇ Customer book (CSV)", ss["df"].to_csv(index=False),
                        "organica_customer_book.csv","text/csv",key=f"dl_book_{key}")
    sc2.download_button("⬇ Reporting series (CSV)", ss["ts"].to_csv(index=False),
                        "organica_reporting_series.csv","text/csv",key=f"dl_ts_{key}")

def currency_note():
    """Say out loud that the currency is assumed. Every figure carries a euro sign whatever the
    source data was, and a reader had no way to tell an assumption from a fact."""
    ccy = getattr(A, "CURRENCY", "EUR")
    if getattr(A, "CURRENCY_ASSUMED", False):
        st.caption(f"Amounts are shown in {ccy}. No currency is carried in "
                   f"the source data, so this is an assumption, not a detection — set "
                   f"ORGANICA_CURRENCY to change it.")
        HON.note("Currency", HON.ASSUMED, f"every amount is shown in {ccy}",
                 "no currency is carried in the source data, so this is set rather than read")
    else:
        HON.drop("Currency")


def basis_note():
    """Record which period length the working-capital figures were measured on."""
    ts = ss.get("ts")
    fin = ss.get("fin")
    src = fin if fin is not None else ts
    if src is None or "period" not in getattr(src, "columns", []):
        return
    periods = sorted(set(src["period"].astype(str)))
    days, ppy, label = A.period_basis(periods)
    known = any(c.isdigit() for c in "".join(periods[:1])) and label
    HON.note("Length of a reporting period", HON.READING,
             f"read the periods as {label}s ({days:g} days, {ppy} a year) from labels such as "
             f"{periods[0] if periods else 'n/a'}",
             "the length is read off the period labels rather than stated by the source; days "
             "sales outstanding, the cash conversion cycle and annualised revenue all scale with it")


def room_note():
    """Record what the data room contained that the pack does not rest on."""
    r = ss.get("room")
    if not r:
        return
    if not r.get("unread"):
        HON.drop("Files in the data room that were not read")
        return
    HON.note("Files in the data room that were not read", HON.SKIPPED,
             f"read {r['parsed']} of {r['data_files']} data files in {r['name']}; "
             f"{len(r['unread'])} file(s) contributed nothing",
             "not readable as tables (images, scans, documents without ruled tables): "
             + ", ".join(r["unread"][:6]) + (" and others" if len(r["unread"]) > 6 else ""))


def trust_copy(key="run", compact=False):
    """What an IC may rely on this pack for, next to the pack rather than in an appendix.

    Built from the run: the basis reads the actual sources, period labels, currency and column
    reading, and the limits come from the honesty register, so none of it can go stale. Call
    currency_note, basis_note and room_note first so the register is populated.
    """
    src, per, mp = [], None, ss.get("mapping")
    if ss.get("df") is not None: src.append(f"customer book, {len(ss['df']):,} rows")
    if ss.get("ts") is not None: src.append(f"reporting series, {len(ss['ts']):,} rows")
    if ss.get("fin") is not None: src.append(f"financials, {len(ss['fin']):,} rows")
    if ss.get("room"): src.append(f"data room {ss['room']['name']}, {ss['room']['parsed']} file(s) read")
    base = ss.get("fin") if ss.get("fin") is not None else ss.get("ts")
    if base is not None and "period" in getattr(base, "columns", []):
        per = A.period_basis(sorted(set(base["period"].astype(str))))
    blocks = TC.block(sources=src, periods=per, currency=getattr(A, "CURRENCY", None),
                      currency_assumed=getattr(A, "CURRENCY_ASSUMED", True),
                      mapping=mp, draws=CXR.PRIORS.get("n"))
    with st.expander("What this pack is, and what you may rely on it for", expanded=False):
        for head, rows in blocks.items():
            if not rows:
                continue
            st.markdown(f"**{head}**")
            for label, line in rows:
                st.markdown(f"<div style='margin:0 0 6px 0'><span style='color:{MUTE}'>"
                            f"{label}.</span> {line}</div>", unsafe_allow_html=True)
        st.caption("Nothing here is a self-assessment by the software. Every percentage in "
                   "this pack is the probability of an outcome.")
        flat = "\n".join(f"{h}\n" + "\n".join(f"  {a}: {b}" for a, b in rows)
                         for h, rows in blocks.items() if rows)
        st.download_button("⬇ Basis of preparation (text)", flat,
                           "organica_basis_of_preparation.txt", "text/plain", key=f"dl_tc_{key}")


def honesty_panel(key="run"):
    """Everything this run could not verify, in one list.

    These were all declared already, each next to the figure it affected. A reader had to go
    and find them. This is the same content in one place.
    """
    df = HON.frame()
    if not len(df):
        return
    with st.expander(f"What in this pack is not a measurement ({len(df)})", expanded=False):
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("Every row is an assumption, a reading or a gap, not a number taken from the "
                   "source. Nothing else in the pack is in this position.")
        st.download_button("⬇ This list (CSV)", df.to_csv(index=False),
                           "organica_honesty_register.csv", "text/csv", key=f"dl_hon_{key}")


def source_register():
    """What was loaded and what each source drives. The first answer to 'where is this from'."""
    try:
        reg=TR.sources(book=ss.get("df"), ts=ss.get("ts"), fin=ss.get("fin"),
                       raw=ss.get("raw"), mapping=ss.get("mapping"))
        if len(reg):
            st.markdown("**Sources loaded**")
            st.dataframe(reg,use_container_width=True,hide_index=True)
            st.caption("Every figure in the pack resolves to one of these. The IC paper, section 16, "
                       "traces the reconciliation flag down to the individual customers.")
    except Exception:
        pass

def validation_view(df):
    source_register()
    currency_note()
    basis_note()
    room_note()
    honesty_panel("data")
    trust_copy("data")
    if ss.get("ts") is not None:
        with st.expander("Open the source — trace the reconciliation to the underlying rows"):
            trace_block(key="data")
    st.markdown("**Reconciliation** — these tie directly to the analyses")
    c=st.columns(4)
    c[0].metric("Rows (customers)", f"{len(df):,}")
    c[1].metric("ARR (Σ revenue)", f"€{df.revenue.sum()/1e6:.2f}m")
    c[2].metric("Total volume", f"{df.volume.sum():,.0f}")
    c[3].metric("Avg ACV", f"€{df.revenue.sum()/max(len(df),1)/1e3:.1f}k")
    bt=df.groupby("tier",observed=True).agg(customers=("customer","size"),arr=("revenue","sum")).reset_index()
    bt["ARR €m"]=(bt["arr"]/1e6).round(2); bt=bt[["tier","customers","ARR €m"]]
    cc=st.columns(2)
    cc[0].caption("ARR by tier (Σ)"); cc[0].dataframe(bt,use_container_width=True,hide_index=True)
    cc[1].caption("Per-customer (annualised revenue shown)")
    show=df.copy(); show["revenue €/yr"]=show["revenue"].round(0)
    cc[1].dataframe(show[["customer","revenue €/yr","volume","tier"]],use_container_width=True,hide_index=True,height=260)
    st.download_button("Download dataset (CSV)", df.assign(revenue_per_year=df.revenue.round(0)).to_csv(index=False),
                       "organica_dataset.csv","text/csv")

# ---------------- chat terminal ----------------
def _term_model():
    """The Organica version the terminal will use. Chosen in the interface, never hardcoded.

    Only versions verified against this deployment are offered. Set on the ai module too,
    so a choice made here is the choice the rest of the product uses in the same session.
    """
    opts=[m for m,_ in AI.available()]
    ss.setdefault("model", AI.MODEL if AI.MODEL in opts else opts[0])
    if ss["model"] not in opts: ss["model"]=opts[0]
    AI.set_model(ss["model"])
    return ss["model"]

def _term_basis(rows):
    """Render a 'what this was built from' block under an artefact."""
    st.markdown(f"<div style='border-left:2px solid {LINE};padding:2px 0 2px 12px;margin:6px 0 2px 0'>"
                + "".join(f"<div style='font-size:12px;color:{MUTE};margin-bottom:2px'>"
                          f"<b style='color:{INK};font-weight:500'>{k}.</b> {v}</div>"
                          for k,v in rows) + "</div>", unsafe_allow_html=True)

def _term_sources():
    return TERM.source_lines(df=ss.get("df"), ts=ss.get("ts"), fin=ss.get("fin"),
                             room=ss.get("room"),
                             extracts={k:{"rows":v["rows"],"cols":v["df"].shape[1]}
                                       for k,v in _dm_files().items()})

def _term_render(blocks, turn):
    for i,(kind,val) in enumerate(blocks):
        k=f"tb{turn}_{i}"
        if kind=="md": st.markdown(val)
        elif kind=="caption": st.caption(val)
        elif kind=="error": st.error(val)
        elif kind=="warn": st.warning(val)
        elif kind=="basis": _term_basis(val)
        elif kind=="kpis":
            cols=st.columns(max(len(val),1))
            for c,(kk,vv) in zip(cols,val.items()): c.metric(kk,str(vv))
        elif kind=="frame":
            lab,fr=val
            if lab: st.caption(lab)
            st.dataframe(fr,use_container_width=True,hide_index=True)
        elif kind=="chart":
            try: chart_for(val, ss.get("results") or {}, suffix=f"term{turn}_{i}")
            except Exception: pass
        elif kind=="download":
            lab,data,fname,mime=val
            st.download_button(lab,data,fname,mime,key=k)

def _term_results():
    R=run_all(ss["df"]); ss["results"]=R; return R

def _term_exec(text, model):
    """effects: (blocks, stream) for one typed line.

    stream, when not None, is (messages, context) and the caller streams the model's answer
    into the transcript. Every branch delegates: nothing is computed here that the pages do
    not already compute, which is the point — the terminal is a second way in, not a second
    implementation.
    """
    p=TERM.parse(text); cmd,arg=p["cmd"],p["arg"]
    if not p["known"]:
        s=TERM.suggest(cmd)
        return [("error", f"`/{cmd}` is not a command."
                 + (f" Did you mean `/{s}`?" if s else "") + " Type `/help` for the list.")], None
    sp=TERM.spec(cmd)
    if cmd=="ask":
        sp=dict(sp, needs="")
    if sp["needs"]=="book" and ss.get("df") is None:
        return [("warn","No book is loaded, so there is nothing to compute. Run `/load demo` "
                        "for the synthetic Verexa book, or load a file on Connect data / Data.")], None
    if sp["needs"]=="extracts" and len(_dm_files())<1:
        return [("warn","No source extracts are loaded. Load them on Data analysis → Sources, "
                        "or its 'Load sample extracts' button, then run `/checks` again.")], None

    if cmd=="help":
        return [("md","**Commands.** Anything that is not a command is treated as a question "
                      "and answered from the computed analytics."),
                ("frame",("",TERM.help_frame())),
                ("md","**How a figure is labelled**"),
                ("frame",("",TERM.evidence_frame()))], None

    if cmd=="models":
        rows=[]
        for rel,blurb in AI.available():
            ok,used,detail=AI.ping(rel)
            rows.append({"Version":rel,"Available":"yes" if ok else "NO",
                         "Checked just now":detail,"Best for":blurb})
        blocks=[("md","**Organica versions published on this deployment.** Each row is a live "
                      "call made just now, not a list read off a page."),
                ("frame",("",pd.DataFrame(rows)))]
        if AI.MODEL_WARNING: blocks.append(("warn",AI.MODEL_WARNING))
        pub,total,note=AI.coverage()
        blocks.append(("caption",note))
        return blocks, None

    if cmd=="status":
        src=_term_sources()
        blocks=[("md","**What is loaded**"),
                ("basis",TERM.built_from(artefact="Session status", sources=src,
                                         mapping=ss.get("mapping"),
                                         assumptions=TERM.assumption_line(ss.get("assump")),
                                         model=model))]
        try:
            reg=TR.sources(book=ss.get("df"), ts=ss.get("ts"), fin=ss.get("fin"),
                           raw=ss.get("raw"), mapping=ss.get("mapping"))
            if len(reg): blocks.append(("frame",("Source register",reg)))
        except Exception: pass
        hf=HON.frame()
        if len(hf): blocks.append(("frame",(f"What in this run is not a measurement ({len(hf)})",hf)))
        err=AI.last_error()
        if err: blocks.append(("error",f"Last model failure at {err['when']} on {err['model']}: {err['what']}"))
        else: blocks.append(("caption","No model call has failed in this session."))
        return blocks, None

    if cmd=="load":
        if TERM.match_name(arg,["demo","sample","verexa"]) is None:
            return [("error","`/load` takes `demo`. Any other dataset arrives through "
                             "Connect data or Data, where the file and its reading are recorded.")], None
        df=load_demo()
        return [("md",f"**Verexa sample book loaded.** {len(df):,} customers, "
                      f"{A.CCY}{df.revenue.sum()/1e6:.2f}m annualised revenue."),
                ("basis",TERM.built_from(artefact="Loaded dataset", sources=_term_sources(),
                                         mapping=ss.get("mapping"),
                                         assumptions=TERM.assumption_line(ss.get("assump")),
                                         model=None,
                                         extra=[("Nature","Synthetic and de-referenced. Verexa "
                                                 "is an invented company; no client data is "
                                                 "shipped with the product.")]))], None

    if cmd=="clear":
        ss["term"]=[]
        return [("caption","Transcript cleared.")], None

    if cmd=="mapping":
        files=_dm_files(); nulls=DM.basis(ss.get("dm_nulls"))
        dm=ss.get("dm_results")
        if dm and dm.get("checks"):
            res=dm; basis=("as computed on the Data analysis page, with the column choices "
                           "made there")
        else:
            res=DMR.assess(files, nulls)
            ss["dm_results"]=res
            basis=("computed here with defaulted column choices; open Data analysis to "
                   "choose the keys, the hierarchy and the dimensions yourself")
        ch=res.get("checks") or {}
        blocks=[("md",f"**The whole data-mapping analysis, over {len(files)} extract(s).**"),
                ("caption","Every figure below is counted on the declared null basis, before "
                           "anything is mapped. No model produced any of them."),
                ("frame",("What was read", pd.DataFrame(
                    [{"Extract":k,"Rows":v.get("rows"),"Columns":len(v.get("columns",[])),
                      "How it was read":v.get("how_it_was_read")}
                     for k,v in (res.get("extracts") or {}).items()])))]
        if "reconcile" in ch:
            r=ch["reconcile"]
            blocks += [("md","**Key reconciliation**"),("kpis",r["kpis"]),
                       ("caption",r["summary"])]
            if len(r["table"]): blocks.append(("frame",("Orphans and duplicates",r["table"].head(60))))
        if "collisions" in ch:
            pairs,detail=ch["collisions"]
            nc=int((pairs["Verdict"]=="collision").sum()) if len(pairs) else 0
            blocks += [("md","**Identifier collisions across every dimension pair**"),
                       ("kpis",{"Pairs tested":f"{len(pairs):,}","Pairs colliding":f"{nc:,}",
                                "Colliding values":f"{int(pairs['Colliding'].sum()) if len(pairs) else 0:,}"}),
                       ("frame",("Every unordered pair",pairs))]
            pt=ch.get("prefix_remedy")
            if pt:
                blocks.append(("caption",f"Measured remedy: a per-dimension prefix takes the "
                                         f"collisions from {pt['before']:,} to {pt['after']:,}. "
                                         f"The legacy identifiers do not change; only the "
                                         f"target-side convention does."))
        if "hierarchy" in ch:
            h=ch["hierarchy"]
            blocks += [("md","**Hierarchy — does each child roll up to exactly one parent**"),
                       ("kpis",h["kpis"]),("caption",h["summary"])]
            if len(h["table"]): blocks.append(("frame",("Every violation, named",h["table"].head(60))))
        if "duplicates" in ch:
            dd=ch["duplicates"]
            blocks.append(("md","**Does one dimension duplicate another**"))
            if dd is not None and len(dd):
                blocks += [("frame",("Pairs holding the same or nearly the same members",dd)),
                           ("caption","The evidence is set equality over the member keys, never "
                                      "the labels. Building both into a target model double "
                                      "counts the same members in any rollup that uses both.")]
            else:
                blocks.append(("caption","No pair of dimension values carries the same member set."))
        if "population" in ch:
            blocks += [("md","**Population reconciliation**"),
                       ("frame",("Source = mapped + unmapped + excluded",ch["population"]))]
        if res.get("findings"):
            blocks += [("md","**Findings register**"),
                       ("frame",("",DM.register(res["findings"])))]
        blocks.append(("basis",TERM.built_from(artefact="Data-mapping analysis",
                                               sources=_term_sources(), model=None,
                                               extra=[("Null basis", ", ".join(res.get("nulls") or [])),
                                                      ("Basis", basis),
                                                      ("Column choices", "; ".join(
                                                          f"{k}: {v}" for k,v in (res.get("choices") or {}).items())),
                                                      ("Method","Set arithmetic on the extracts "
                                                       "as read. No mapping, no model, no "
                                                       "assumption.")])))
        data=SV.data_summary(df=ss.get("df"), ts=ss.get("ts"), fin=ss.get("fin"),
                             extracts=files or None, dm=res, mapping=ss.get("mapping"),
                             nulls=nulls)
        ctx=TERM.ask_context(analyses=None, data=data)
        msgs=TERM.prompt(TERM.REGISTER_REQUEST, ctx, learned=S.load_feedback())
        return blocks, (msgs, ctx)

    if cmd=="checks":
        files=_dm_files(); names=list(files)
        nulls=DM.basis(ss.get("dm_nulls"))
        dm=ss.get("dm_results")
        if dm and dm.get("checks"):
            # The page has run in this session, so its numbers are the numbers. Quoting a
            # second, separately-computed set here is how two screens end up disagreeing
            # about the same extract.
            ch=dm["checks"]
            pairs=[(dm.get("choices",{}).get("reconcile","the chosen keys"), ch["reconcile"])] \
                  if "reconcile" in ch else []
            dups=ch.get("duplicates")
            hier=ch["hierarchy"]["table"] if "hierarchy" in ch else None
            coll=ch["collisions"][1] if "collisions" in ch else None
            source="as computed on the Data analysis page, with the column choices made there"
        else:
            pairs=[]; dups=None; hier=None; coll=None
            try:
                sets={}
                for n in names:
                    df=files[n]["df"]; prof=DM.profile(df,nulls)
                    kc=DM.key_candidates(prof) or DM.identifier_candidates(df,prof,nulls)
                    key=kc[0] if kc else df.columns[0]
                    for c in df.columns:
                        if c==key: continue
                        if 1 < df[c].nunique() <= max(12,len(df)//5):
                            sets.update(DM.member_sets(df,c,key,nulls,prefix=f"{c}: "))
                dups=DM.duplicate_dimensions(sets)
            except Exception as e:
                pairs.append(("duplicate-dimension scan", {"summary":f"did not run: {e}"}))
            if len(names)>=2:
                try:
                    a_,b_=files[names[0]]["df"],files[names[1]]["df"]
                    pa=DM.profile(a_,nulls); pb=DM.profile(b_,nulls)
                    ka=(DM.key_candidates(pa) or DM.identifier_candidates(a_,pa,nulls) or list(a_.columns))[0]
                    kb=(DM.key_candidates(pb) or DM.identifier_candidates(b_,pb,nulls) or list(b_.columns))[0]
                    pairs.append((f"{names[0]} {ka} against {names[1]} {kb}",
                                  DM.reconcile(a_,b_,ka,kb,nulls,label_a=names[0],label_b=names[1])))
                except Exception as e:
                    pairs.append(("reconciliation",{"summary":f"did not run: {e}"}))
            source=("computed here with default column choices; open Data analysis to choose "
                    "the keys and dimensions yourself")
        find=TERM.check_findings(pairs,dups,hier,coll)
        blocks=[("md",f"**Data-analysis checks over {len(names)} extract(s).**"),
                ("frame",("Findings",find)),
                ("basis",TERM.built_from(artefact="Data-analysis findings register",
                                         sources=_term_sources(), model=None,
                                         extra=[("Null basis", ss.get("dm_nulls") or
                                                 ", ".join(x for x in DM.NULL_TOKENS if x)),
                                                ("Basis", source),
                                                ("Method","Set arithmetic on the extracts as "
                                                 "read. No mapping, no model, no assumption.")]))]
        if dups is not None and len(dups):
            blocks.insert(2,("frame",("Dimensions holding the same member set",dups)))
            blocks.insert(3,("caption","Two dimensions carrying the same members are one dimension "
                             "under two names. The evidence is set equality on the member sets, "
                             "not similarity of the labels — which is why a label pair with nothing "
                             "in common is still caught. Building both into a target model "
                             "double counts the rollup."))
        blocks.append(("caption","The full page, with every table and the export workbook, is "
                                 "Data analysis."))
        return blocks, None

    if cmd=="run":
        R=_term_results()
        blocks=[("md",f"**Ran {len(R)} analyses over the loaded book.**")]
        for name in R:
            blocks.append(("md",f"**{name}**"))
            blocks.append(("kpis",R[name].get("kpis",{})))
        blocks.append(("basis",TERM.built_from(artefact="Full analysis stack",
                                               sources=_term_sources(), mapping=ss.get("mapping"),
                                               assumptions=TERM.assumption_line(ss["assump"]),
                                               model=None,
                                               extra=[("Evidence","Revenue and customer counts are "
                                                       f"{TERM.OBSERVED}; margins, concentration and "
                                                       f"bridges are {TERM.CALCULATED}; simulation, "
                                                       f"valuation and returns are {TERM.INFERRED} "
                                                       "because they rest on the assumptions above.")])))
        return blocks, None

    if cmd=="analysis":
        R=_term_results()
        name=TERM.match_name(arg,list(R))
        if name is None:
            return [("error",f"No analysis called `{arg}`."),
                    ("frame",("Available",pd.DataFrame({"Analysis":list(R)})))], None
        res=R[name]
        blocks=[("md",f"**{name}**"),("kpis",res.get("kpis",{})),("chart",name)]
        for tn,td in res.get("tables",{}).items():
            blocks.append(("frame",(tn,td)))
        blocks.append(("basis",TERM.built_from(artefact=f"Analysis · {name}",
                                               sources=_term_sources(), mapping=ss.get("mapping"),
                                               assumptions=TERM.assumption_line(ss["assump"]),
                                               model=None)))
        return blocks, None

    if cmd in ("case","case-doc"):
        R=_term_results(); keys=list(C.CASES)
        titles={C.CASES[k]["title"]:k for k in keys}
        key=TERM.match_name(arg,keys) or titles.get(TERM.match_name(arg,list(titles)) or "")
        if key is None:
            return [("error",f"No business case called `{arg}`."),
                    ("frame",("Cases",pd.DataFrame([{"Key":k,"Case":C.CASES[k]['title'],
                                                     "Audience":C.CASES[k]['audience']} for k in keys])))], None
        case=C.CASES[key]; ctx=C.build_context(R)
        read=case["read"](ss["df"], ss["assump"], R)
        if cmd=="case":
            blocks=[("md",f"**{case['title']}** — {case['question']}"),
                    ("md",f"### {read['verdict']}"),
                    ("md",read["headline"]),
                    ("md","\n".join(f"- {b}" for b in read.get("bullets",[]))),
                    ("frame",("The route this case runs",
                              pd.DataFrame({"Step":range(1,len(case["route"])+1),
                                            "Analysis":case["route"]}))),
                    ("basis",TERM.built_from(artefact=f"Business case · {case['title']}",
                                             sources=_term_sources(), mapping=ss.get("mapping"),
                                             assumptions=TERM.assumption_line(ss["assump"]),
                                             model=None,
                                             extra=[("Verdict basis","The deterministic read of "
                                                     "the route above. No model wrote it, and it "
                                                     f"is a {TERM.JUDGEMENT.lower()} over "
                                                     f"{TERM.CALCULATED.lower()} figures.")]))]
            return blocks, None
        return ([("md",f"**{case['title']}** — written up as a business case."),
                 ("basis",TERM.built_from(artefact=f"Business case document · {case['title']}",
                                          sources=_term_sources(), mapping=ss.get("mapping"),
                                          assumptions=TERM.assumption_line(ss["assump"]),
                                          model=model, ai_written=True))],
                (TERM.case_doc_prompt(case, ctx, read), ctx))

    if cmd=="journey":
        R=_term_results(); keys=list(J.JOURNEYS)
        key=TERM.match_name(arg,keys)
        if key is None:
            return [("error",f"No journey called `{arg}`."),
                    ("frame",("Journeys",pd.DataFrame([{"Key":k,"Journey":J.JOURNEYS[k]['title'],
                                                        "Audience":J.JOURNEYS[k]['audience']}
                                                       for k in keys])))], None
        res=J.run_journey(key, ss["df"], ss["assump"], R)
        fr=pd.DataFrame([{"Severity":f["severity"],"Finding":f["title"],"Metric":f["metric"],
                          "Observed":f["observed"],"Threshold":f["threshold"],
                          "What it means":f["insight"]} for f in res["findings"]])
        stamp=datetime.date.today().isoformat(); comp=ss.get("company","Verexa Software")
        blocks=[("md",f"**{res['journey']['title']}** — {res['verdict']}"),
                ("kpis",{"Critical":res["crit"],"Warnings":res["warn"],
                         "Checks run":len(res["findings"])}),
                ("frame",("Every gate, and how it was decided",fr)),
                ("download",("⬇ Journey report (Markdown)",
                             J.journey_report_md(res,comp,stamp),
                             "Organica_journey.md","text/markdown")),
                ("basis",TERM.built_from(artefact=f"Journey · {res['journey']['title']}",
                                         sources=_term_sources(), mapping=ss.get("mapping"),
                                         assumptions=TERM.assumption_line(ss["assump"]),
                                         model=None,
                                         extra=[("Gates",f"{len(res['findings'])} threshold gates "
                                                 "over the computed results. The thresholds are "
                                                 f"{TERM.JUDGEMENT.lower()}; what they test is "
                                                 f"{TERM.CALCULATED.lower()}.")]))]
        return blocks, None

    if cmd=="icpaper":
        R=_term_results(); a=ss["assump"]; t=_pinned_terms()
        stamp=datetime.date.today().isoformat(); comp=ss.get("company","Verexa Software")
        secs=IPR.build(R, df=ss["df"], a=a, terms=t, company=comp, stamp=stamp,
                       journeys_mod=J, prov_mod=PV, risk=_risk_pack(R,a,t))
        cov=IPR.coverage(secs)
        reg=pd.DataFrame([(s["n"],s["title"],s["source"]) for s in secs],
                         columns=["#","Section","Source"])
        return [("md","**IC paper assembled.**"),
                ("kpis",{"Sections":cov["total"],"From the data room":cov["engine"],
                         "From the terms":cov["terms"],"Deal team":cov["dealteam"]}),
                ("caption",cov["summary"]),
                ("frame",("Section register",reg)),
                ("download",("⬇ IC paper (PDF)",IPR.build_pdf(secs,comp,stamp,cov),
                             "Organica_IC_paper.pdf","application/pdf")),
                ("download",("⬇ IC paper (Markdown)",IPR.build_md(secs,comp,stamp,cov),
                             "Organica_IC_paper.md","text/markdown")),
                ("basis",TERM.built_from(artefact="IC paper", sources=_term_sources(),
                                         mapping=ss.get("mapping"),
                                         assumptions=TERM.assumption_line(a), model=None,
                                         extra=[("Empty by design",
                                                 f"{cov['dealteam']} section(s) a data room cannot "
                                                 "answer are left empty rather than drafted. "
                                                 "Nothing on this paper was written by a model.")]))], None

    if cmd=="export":
        R=ss.get("results") or _term_results(); a=ss["assump"]
        stamp=datetime.date.today().isoformat(); comp=ss.get("company","Verexa Software")
        which=TERM.match_name(arg,["xls","board","memo","deck","icpaper"])
        if which is None:
            return [("error","`/export` takes one of: xls, board, memo, deck, icpaper.")], None
        try:
            if which=="xls":
                path=os.path.join(OUT,"Organica_pack.xlsx"); X.build_pack(path,R,assumptions=a)
                data=open(path,"rb").read()
                dl=("⬇ XLS pack",data,"Organica_pack.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                note="Includes the provenance sheet and the live tie-out formulas."
            elif which=="board":
                dl=("⬇ Board pack (PDF)",BP.build_pdf(R,comp,stamp),
                    "Organica_board_pack.pdf","application/pdf"); note="Cover, KPIs, benchmark, valuation, scenarios, validation."
            elif which=="memo":
                dl=("⬇ IC memo (Markdown)",IM.build_md(R,comp,stamp),
                    "Organica_IC_memo.md","text/markdown"); note="Seven sections, assembled from the computed results."
            elif which=="deck":
                dl=("⬇ IC deck (PPTX)",ID.build_pptx(R,comp,stamp),
                    "Organica_IC_deck.pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                note="Branded slides off the same results."
            else:
                t=_pinned_terms()
                secs=IPR.build(R, df=ss["df"], a=a, terms=t, company=comp, stamp=stamp,
                               journeys_mod=J, prov_mod=PV, risk=_risk_pack(R,a,t))
                dl=("⬇ IC paper (PDF)",IPR.build_pdf(secs,comp,stamp,IPR.coverage(secs)),
                    "Organica_IC_paper.pdf","application/pdf"); note="The committee template."
        except Exception as e:
            return [("error","That export could not be built. "+AI.user_message(e,""))], None
        return [("md",f"**{dl[0][2:]} built.**"),("caption",note),("download",dl),
                ("basis",TERM.built_from(artefact=dl[2], sources=_term_sources(),
                                         mapping=ss.get("mapping"),
                                         assumptions=TERM.assumption_line(a), model=None))], None

    # /ask, and every line that is not a command.
    #
    # The question is answered from whatever the session holds, not only from a customer
    # book: "how many cost centres have no parent" is a question about two extracts on the
    # Data analysis page and has nothing to do with revenue. The data summary is a
    # SUMMARY — column shapes, counts and the engine's own check results — never rows, and
    # never the values of a column that looks like a person or an identifier.
    analyses=None
    if ss.get("df") is not None:
        try: analyses=C.build_context(_term_results())
        except Exception: analyses=None
    data=SV.data_summary(df=ss.get("df"), ts=ss.get("ts"), fin=ss.get("fin"),
                           extracts=_dm_files() or None, dm=ss.get("dm_results"),
                           mapping=ss.get("mapping"), nulls=DM.basis(ss.get("dm_nulls")))
    ctx=TERM.ask_context(analyses=analyses, data=data)
    if not analyses and not _dm_files():
        return [("warn","Nothing is loaded, so there is nothing to answer from. Run "
                        "`/load demo`, or load a file on Connect data, Data or Data analysis.")], None
    learned=S.load_feedback()
    msgs=TERM.prompt(arg, ctx, history=[{"role":m["role"],"content":m.get("text","")}
                                        for m in ss.get("term",[]) if m.get("text")],
                     learned=learned)
    return [], (msgs, ctx)

def chat_terminal_page():
    st.title("Chat terminal")
    st.markdown(f"<div style='color:{MUTE};margin-top:-8px;margin-bottom:14px'>"
                f"<b>The Chat terminal builds things; Ask answers questions.</b> "
                f"One command surface over the whole product: run an analysis, take a business case to a verdict, "
                f"assemble the IC paper, run the data checks, build an export — from a typed line, "
                f"using the same code the pages use. Every artefact says what it was built from, "
                f"and a model writes prose, never a measurement. Type <code>/help</code>.</div>",
                unsafe_allow_html=True)
    model=_term_model()
    ss.setdefault("term",[])

    c1,c2,c3=st.columns([0.42,0.32,0.26])
    opts=[m for m,_ in AI.available()]
    pick=c1.selectbox("Organica version", opts, index=opts.index(model), key="term_model_pick")
    if pick!=model:
        ss["model"]=pick; AI.set_model(pick); st.rerun()
    c2.caption(dict(AI.available())[model])
    if c3.button("Check this version now", use_container_width=True):
        ss["term_ping"]=AI.ping(model)
    if ss.get("term_ping"):
        ok,used,detail=ss["term_ping"]
        (st.success if ok else st.error)(f"{used} {detail}")

    if not AI.configured():
        st.error("Organica is not configured on this deployment. Commands that compute still "
                 "run; anything that needs reasoning will say so rather than fall back silently.")
    elif AI.MODEL_WARNING:
        st.warning(AI.MODEL_WARNING)
    err=AI.last_error()
    if err:
        st.warning(f"Last failure at {err['when']} · {err['what']}")

    st.caption(f"{len(AI.available())} versions published · in use: {model} · "
               f"{'a book is loaded' if ss.get('df') is not None else 'no book loaded — try /load demo'}")
    st.divider()

    if not ss["term"]:
        # What a new user sees instead of an empty box. The prompt is shown in full and is
        # selectable, so clicking the button and pasting the text do the same thing.
        st.markdown(f"<div style='color:{INK};font-weight:500;margin-bottom:6px'>"
                    f"Start here</div>", unsafe_allow_html=True)
        for i,stt in enumerate(TERM.STARTERS):
            with st.container(border=True):
                st.markdown(f"**{stt['title']}**")
                st.caption(stt["note"])
                st.code(stt["prompt"], language=None)
                if st.button("Run this", key=f"starter{i}", type="primary" if i==0 else "secondary"):
                    ss["term_send"]=stt["prompt"]; st.rerun()
        st.caption("Or type anything. A line that is not a command is answered from the "
                   "loaded data, and `/help` lists every command.")

    for ti,turn in enumerate(ss["term"]):
        with st.chat_message(turn["role"]):
            if turn.get("text"): st.markdown(turn["text"])
            _term_render(turn.get("blocks",[]), ti)
            if turn.get("caveat"): st.caption(turn["caveat"])
            if turn.get("digest") is not None:
                with st.expander("The figures this answer was given"):
                    st.dataframe(turn["digest"],use_container_width=True,hide_index=True)

    q=st.chat_input("A command such as /run, /case price_power, /icpaper — or a question in plain English")
    if not q and ss.get("term_send"):
        q=ss.pop("term_send")
    if q:
        ss["term"].append({"role":"user","text":q,"blocks":[]})
        with st.chat_message("user"): st.markdown(q)
        ti=len(ss["term"])
        with st.chat_message("assistant"):
            try:
                blocks,stream=_term_exec(q, model)
            except Exception as e:
                # Everything a command can raise is funnelled through one neutralising
                # call, so an unanticipated failure cannot put an internal detail on a
                # screen that a prospect is watching.
                blocks,stream=[("error","That command did not complete. "+AI.user_message(e, ""))],None
            _term_render(blocks,ti)
            turn={"role":"assistant","text":"","blocks":blocks}
            if stream is not None:
                msgs,ctx=stream
                if not AI.configured():
                    msg=("Organica is not configured on this deployment, so this answer cannot "
                         "be written. The computed results above are unaffected: they need no "
                         "reasoning service.")
                    st.error(msg); turn["blocks"]=blocks+[("error",msg)]
                else:
                    try:
                        text=st.write_stream(AI.stream(msgs, model=model, timeout=90))
                        turn["text"]=AI._clean(text if isinstance(text,str) else "".join(text))
                        turn["caveat"]=TERM.ai_caveat(model)
                        turn["digest"]=TERM.context_digest(ctx)
                        st.caption(turn["caveat"])
                        with st.expander("The figures this answer was given"):
                            st.dataframe(turn["digest"],use_container_width=True,hide_index=True)
                    except Exception as e:
                        # Neutral by construction: ai raises Unavailable and nothing else
                        # crosses this boundary, so no status code, host or supplier can be
                        # rendered here even when the failure is one nobody anticipated.
                        msg=AI.user_message(e)
                        st.error(msg+" Nothing was substituted for it — choose another version "
                                     "above and send the line again.")
                        turn["blocks"]=blocks+[("error",msg)]
        ss["term"].append(turn)

# ---------------- data analysis ----------------
def _dm_files():
    """The extracts loaded on this page. Kept separate from the customer book: these are
    source-system extracts being checked against each other, not a dataset to analyse."""
    return ss.setdefault("dm_files", {})

def _dm_add(name, data, sheet=None):
    df,note=DM.read_table(data,name,sheet=sheet)
    label=name if sheet in (None,"") else f"{name} · {sheet}"
    _dm_files()[label]={"df":df,"note":note,"rows":len(df)}
    return label

def _dm_pick(label, key, default_cols, caption=None):
    """A column chooser over one loaded extract. Returns the column name."""
    cols=list(_dm_files()[label]["df"].columns)
    idx=next((cols.index(c) for c in default_cols if c in cols),0)
    return st.selectbox(caption or "Column", cols, index=idx, key=key)

def data_analysis_page():
    st.title("Data analysis")
    st.markdown(f"<div style='color:{MUTE};margin-top:-8px;margin-bottom:14px'>Two or more source extracts, "
                f"measured and reconciled against each other <b>before</b> anything is mapped or migrated. "
                f"Every figure on this page is counted on a declared null basis, and every finding says what "
                f"was measured and whether it is observed or inferred.</div>", unsafe_allow_html=True)

    # The null basis is the one assumption on this page that silently moves numbers, so it sits
    # at the top of it, in writing, and is editable — not buried in the code.
    with st.expander("Null basis — what counts as no value", expanded=not _dm_files()):
        st.caption("A German extract writes \"no value\" as an empty cell, as n.a., as na or as a bare dash, "
                   "and a reader that only honours the empty cell counts the other three as data. Every "
                   "populated, distinct and reconciled count on this page uses the basis below.")
        ss.setdefault("dm_nulls", ", ".join(x for x in DM.NULL_TOKENS if x))
        ss["dm_nulls"]=st.text_input("Tokens that mean no value (comma separated; a blank cell is always included)",
                                     ss["dm_nulls"], key="dm_nulls_in")
    nulls=DM.basis(ss["dm_nulls"])
    find=[]   # the findings register, built from the checks that actually ran

    t_src,t_prof,t_chk,t_out=st.tabs(["Sources","Profile","Checks","Findings & export"])

    # ---- sources -----------------------------------------------------------------
    with t_src:
        ups=st.file_uploader("Source extracts — CSV or Excel (German headers, semicolon delimiters "
                             "and leading zeros are handled)", type=["csv","xlsx","xls","xlsm"],
                             accept_multiple_files=True, key="dm_up")
        if ups:
            for up in ups:
                data=up.getvalue()
                if up.name.lower().endswith((".xlsx",".xls",".xlsm")):
                    sheets=DM.excel_sheets(data)
                    for sh in (sheets or [None]):
                        lbl=f"{up.name} · {sh}" if sh else up.name
                        if lbl not in _dm_files(): _dm_add(up.name,data,sheet=sh)
                elif up.name not in _dm_files():
                    _dm_add(up.name,data)
        c1,c2=st.columns([1,1])
        if c1.button("Load sample extracts", key="dm_sample"):
            for n,b in DM.sample_extracts(): _dm_add(n,b)
            st.rerun()
        if c2.button("Clear all", key="dm_clear"):
            ss["dm_files"]={}; st.rerun()
        st.caption("The sample pair is synthetic and generated in code — no client data. It is built to "
                   "carry one of each defect this page looks for.")
        if _dm_files():
            st.divider()
            st.markdown(f"**{len(_dm_files())} extract(s) loaded**")
            for k,v in _dm_files().items():
                st.markdown(f"- `{k}` — {v['rows']:,} rows × {v['df'].shape[1]} columns · {v['note']}")
            st.dataframe(pd.DataFrame([{"Extract":k,"Rows":v["rows"],"Columns":v["df"].shape[1],
                                        "How it was read":v["note"]} for k,v in _dm_files().items()]),
                         use_container_width=True, hide_index=True)

    files=_dm_files()
    if not files:
        with t_prof: st.info("Load at least one extract on the Sources tab.")
        with t_chk: st.info("Load at least two extracts on the Sources tab.")
        with t_out: st.info("Nothing measured yet.")
        return
    names=list(files)

    # ---- profile -----------------------------------------------------------------
    profiles={}
    with t_prof:
        for i,n in enumerate(names):
            df=files[n]["df"]; prof=DM.profile(df,nulls); profiles[n]=prof
            st.markdown(f"**{n}** — {len(df):,} rows × {df.shape[1]} columns")
            st.caption(files[n]["note"])
            st.dataframe(prof,use_container_width=True,hide_index=True)
            hits=DM.null_hits(df,nulls)
            kc=DM.key_candidates(prof)
            # Stated, not only tabulated. The table is the evidence; this is the measurement,
            # and it is the part that survives being read quickly.
            st.markdown(
                f"Observed. {df.shape[1]} columns over {len(df):,} rows. "
                f"**{int(prof['No value'].sum()):,} cells carry no value** on the declared basis, "
                f"**{int(prof['Leading zeros'].sum()):,} values are zero-padded** and survive because "
                f"the extract was read as text, and "
                + (f"**{len(kc)} column(s) could serve as the key** ({', '.join(kc)})." if kc
                   else "**no column is populated and distinct on every row**, so this extract has "
                        "no natural key."))
            if len(hits):
                with st.expander(f"Null basis — the {int(hits['Rows'].sum()):,} cells it changed in this extract"):
                    st.dataframe(hits,use_container_width=True,hide_index=True)
                    st.caption("Observed. Each of these cells is counted as no value above, and would be "
                               "counted as data on a blank-cell-only basis.")
            with st.expander("First rows as read"):
                st.dataframe(df.head(10),use_container_width=True,hide_index=True)
            if i<len(names)-1: st.divider()
        for n in names:
            p=profiles[n]
            lz=int(p["Leading zeros"].sum())
            if lz:
                find.append(DM.finding(
                    f"{n} carries zero-padded identifiers",
                    DM.OBSERVED, f"{lz:,} values across {int((p['Leading zeros']>0).sum())} column(s) "
                                 f"begin with a zero; the extract was read entirely as text so they survive",
                    "A reader that infers types turns 001 into 1, and the key stops joining to the "
                    "system that kept the zeros"))
            nv=int(p["No value"].sum())
            if nv:
                find.append(DM.finding(
                    f"{n} has {nv:,} cells with no value",
                    DM.CALCULATED, f"counted on the declared basis ({', '.join(sorted(x for x in nulls if x))} "
                                   f"and blank) over {len(files[n]['df']):,} rows",
                    "On a blank-cell-only basis these count as populated, which overstates coverage"))

    # ---- checks ------------------------------------------------------------------
    # results and picked are recorded into session state at the end of this block. The
    # terminal answers questions about these checks by reading what the page computed,
    # not by recomputing them: recomputing with different default column choices would
    # give a second, slightly different answer to the same question.
    results={}; picked={}
    with t_chk:
        st.markdown("###### 1 · Reconcile two extracts on a key")
        st.caption("Rows only in the first, only in the second, in both, and the duplicate keys that "
                   "make a row count disagree with a distinct count.")
        if len(names)<2:
            st.info("Two extracts are needed. Load another on the Sources tab.")
        else:
            rc=st.columns(4)
            la=rc[0].selectbox("First extract",names,index=0,key="dm_ra")
            ka=rc[1].selectbox("Key",list(files[la]["df"].columns),
                               index=_idx(files[la]["df"].columns,_dm_ids(la,profiles,nulls)),key="dm_ka")
            lb=rc[2].selectbox("Second extract",names,index=min(1,len(names)-1),key="dm_rb")
            kb=rc[3].selectbox("Key ",list(files[lb]["df"].columns),
                               index=_idx(files[lb]["df"].columns,_dm_ids(lb,profiles,nulls)),key="dm_kb")
            r=DM.reconcile(files[la]["df"],files[lb]["df"],ka,kb,nulls,_short(la),_short(lb))
            results["reconcile"]=r; picked["reconcile"]=f"{la}.{ka} against {lb}.{kb}"
            k=st.columns(len(r["kpis"]))
            for col,(kk,vv) in zip(k,r["kpis"].items()): col.metric(kk,vv)
            st.markdown(f"<div style='color:{INK}'>{r['summary']}</div>",unsafe_allow_html=True)
            if len(r["table"]): st.dataframe(r["table"],use_container_width=True,hide_index=True,height=260)
            if r["truncated"]: st.caption("Listing truncated; the counts above are complete.")
            find.append(DM.finding(
                ("The two extracts hold the same key set" if r["identical"]
                 else f"{la} and {lb} do not hold the same key set"),
                DM.CALCULATED,
                f"set comparison of {ka} against {kb}: {r['counts']['both']:,} in both, "
                f"{r['counts']['only_a']:,} only in the first, {r['counts']['only_b']:,} only in the second",
                ("Nothing follows; the join is total both ways" if r["identical"]
                 else "Every value on one side only is an orphan, and an inner join silently drops it")))

        st.divider()
        st.markdown("###### 2 · Identifier collisions across every pair of dimensions")
        st.caption("Target systems normally require an identifier to be unique ACROSS dimensions, not only "
                   "within one. Legacy keys from separate systems are short numerics starting at 1, so they "
                   "overlap almost completely. Every unordered pair is tested, not the ones anyone thought to check.")
        opts=[f"{n} · {c}" for n in names for c in files[n]["df"].columns]
        default=[f"{n} · {_dm_ids(n,profiles,nulls)[0]}" for n in names
                 if _dm_ids(n,profiles,nulls)] or opts[:2]
        chosen=st.multiselect("Identifier columns to test against each other",opts,default,key="dm_coll")
        if len(chosen)>=2:
            dims={}
            for c in chosen:
                # rsplit, not split: an Excel extract's own label carries " · <sheet>", so
                # splitting from the left takes the sheet name as the column.
                n,col=c.rsplit(" · ",1); dims[c]=DM.values(files[n]["df"][col],nulls)
            pairs,detail=DM.collisions(dims); results["collisions"]=(pairs,detail)
            picked["collisions"]=", ".join(chosen)
            nc=int((pairs["Verdict"]=="collision").sum())
            m=st.columns(3)
            m[0].metric("Pairs tested",f"{len(pairs):,}")
            m[1].metric("Pairs colliding",f"{nc:,}")
            m[2].metric("Colliding values",f"{int(pairs['Colliding'].sum()):,}")
            st.markdown(f"<div style='color:{INK}'>"
                        + (f"No identifier is shared across any of the {len(pairs)} pairs tested."
                           if not nc else
                           f"<b>{nc} of {len(pairs)} pairs collide</b>, on "
                           f"{int(pairs['Colliding'].sum()):,} identifier values in total. Measured by "
                           f"set intersection over every unordered pair, not over the pairs anyone "
                           f"thought to check.")
                        + "</div>", unsafe_allow_html=True)
            st.write("")
            st.dataframe(pairs,use_container_width=True,hide_index=True)
            if len(detail):
                with st.expander(f"The {len(detail):,} colliding values"):
                    st.dataframe(detail,use_container_width=True,hide_index=True,height=280)
                pt=DM.prefix_test(dims,{c:c.rsplit(" · ",1)[1][:3].upper() for c in dims})
                results["prefix_remedy"]=pt
                st.caption(f"Measured remedy: prefixing each dimension's target identifier takes the "
                           f"collisions from {pt['before']:,} to {pt['after']:,}. Legacy identifiers are "
                           f"unchanged in the source systems; only the target-side convention moves.")
                find.append(DM.finding(
                    f"{nc} of {len(pairs)} dimension pairs share identifier values",
                    DM.CALCULATED,
                    f"set intersection over every unordered pair: {int(pairs['Colliding'].sum()):,} "
                    f"colliding values; a per-dimension prefix removes {pt['before']-pt['after']:,} "
                    f"of them and leaves {pt['after']:,}",
                    "A cross-dimension uniqueness rule rejects the load, and it fails at load time rather "
                    "than in any single extract"))
            else:
                find.append(DM.finding("No identifier collides across the tested dimensions",DM.CALCULATED,
                    f"{len(pairs)} unordered pairs tested by set intersection, 0 shared values",
                    "Nothing follows"))
        else:
            st.info("Pick at least two identifier columns.")

        st.divider()
        st.markdown("###### 3 · Hierarchy — does the child roll up to exactly one parent")
        hc=st.columns(4)
        hl=hc[0].selectbox("Extract",names,index=min(1,len(names)-1),key="dm_hf")
        hcol=list(files[hl]["df"].columns)
        ch=hc[1].selectbox("Child",hcol,index=_idx(hcol,_dm_ids(hl,profiles,nulls)),key="dm_hc")
        pa=hc[2].selectbox("Parent",hcol,index=min(2,len(hcol)-1),key="dm_hp")
        dom_opts=["(not supplied)"]+[f"{n} · {c}" for n in names for c in files[n]["df"].columns]
        # A parent column normally carries the same name as the key of the extract it points at,
        # so offer that pairing by default. Without it the dangling-parent test never runs and
        # the page reports "not run" on the check most likely to find something.
        dom_def=_idx(dom_opts,[f"{n} · {pa}" for n in names if n!=hl and pa in files[n]["df"].columns])
        dom_sel=hc[3].selectbox("Parent dimension",dom_opts,index=dom_def,key="dm_hd")
        domain=None
        if dom_sel!="(not supplied)":
            dn,dc=dom_sel.rsplit(" · ",1); domain=DM.keyset(files[dn]["df"][dc],nulls)
        h=DM.hierarchy(files[hl]["df"],ch,pa,nulls,domain=domain); results["hierarchy"]=h
        picked["hierarchy"]=(f"{hl}: child {ch} to parent {pa}"
                             + (f", parent dimension {dom_sel}" if domain is not None
                                else ", no parent dimension supplied"))
        k=st.columns(len(h["kpis"]))
        for col,(kk,vv) in zip(k,h["kpis"].items()): col.metric(kk,vv)
        st.markdown(f"<div style='color:{INK}'>{h['summary']}</div>",unsafe_allow_html=True)
        if len(h["table"]): st.dataframe(h["table"],use_container_width=True,hide_index=True,height=240)
        find.append(DM.finding(
            (f"{ch} rolls up cleanly to {pa}" if not len(h["table"])
             else f"{ch} does not roll up cleanly to {pa}"),
            DM.CALCULATED,
            f"{h['counts']['children']:,} distinct children: {h['counts']['multi']:,} with more than one "
            f"parent, {h['counts']['noparent']:,} with none, {h['counts']['self']:,} self-parented, "
            + (f"{h['counts']['dangling']:,} parent values absent from the parent dimension"
               if domain is not None else "dangling parents not tested, no parent dimension supplied"),
            ("Nothing follows" if not len(h["table"])
             else "A rollup built on this does not balance, and the variance appears in the target "
                  "system rather than here")))

        st.divider()
        st.markdown("###### 4 · Does one dimension duplicate another")
        st.caption("Two dimensions holding the same members are one dimension wearing two names. The "
                   "evidence is set equality over the member keys, never the labels — the case this was "
                   "built from had a region and a segment with nothing in common in their names and "
                   "exactly the same eight sites.")
        dc=st.columns(2)
        dl=dc[0].selectbox("Extract ",names,index=0,key="dm_df")
        dcols=list(files[dl]["df"].columns)
        mem=dc[1].selectbox("Member key",dcols,index=_idx(dcols,_dm_ids(dl,profiles,nulls)),key="dm_dm")
        cand=[c for c in dcols if c!=mem]
        pre=[c for c in cand if 2<=int(profiles[dl].loc[profiles[dl].Column==c,"Distinct"].iloc[0])<=max(2,len(files[dl]["df"])//3)]
        dims_sel=st.multiselect("Classifying columns to compare",cand,pre[:4],key="dm_dd")
        if len(dims_sel)>=2:
            sets={}
            for c in dims_sel: sets.update(DM.member_sets(files[dl]["df"],c,mem,nulls,prefix=f"{c}: "))
            dd=DM.duplicate_dimensions(sets); results["duplicates"]=dd
            picked["duplicates"]=f"{dl}: member key {mem}, dimensions {', '.join(dims_sel)}"
            m=st.columns(2)
            m[0].metric("Dimension values compared",f"{len(sets):,}")
            m[1].metric("Duplicate or near-duplicate pairs",f"{len(dd):,}")
            if len(dd):
                top=dd.iloc[0]
                st.markdown(f"<div style='color:{INK}'><b>{top['Dimension A']}</b> and "
                            f"<b>{top['Dimension B']}</b> carry an <b>identical member set</b> — "
                            f"{int(top['Shared'])} shared members out of {int(top['Members in A'])} "
                            f"and {int(top['Members in B'])}, proven by {top['Evidence']} over "
                            f"{mem}. The labels have nothing in common; the populations are the same."
                            + (f" {len(dd)-1} further pair(s) below." if len(dd)>1 else "")
                            + "</div>", unsafe_allow_html=True)
                st.write("")
                st.dataframe(dd,use_container_width=True,hide_index=True)
                find.append(DM.finding(
                    f"{top['Dimension A']} and {top['Dimension B']} are the same population",
                    DM.CALCULATED,
                    f"{top['Evidence']} over {mem}: {int(top['Shared'])} shared members, "
                    f"{int(top['Members in A'])} against {int(top['Members in B'])}"
                    + (f"; {len(dd)-1} further pair(s) in the table" if len(dd)>1 else ""),
                    "Building both into the target model double counts the same members in any rollup "
                    "that uses both"))
            else:
                st.caption("No pair of dimension values carries the same member set.")
                find.append(DM.finding("No dimension duplicates another",DM.CALCULATED,
                    f"{len(sets)} dimension values compared pairwise by member set over {mem}; "
                    f"no equality, containment or overlap above 80%","Nothing follows"))
        else:
            st.info("Pick at least two classifying columns.")

        st.divider()
        st.markdown("###### 5 · Population reconciliation")
        st.caption("SOURCE = MAPPED + UNMAPPED + EXCLUDED. Anything the three buckets do not account for "
                   "is named as unexplained rather than absorbed: it is the count of rows that left the "
                   "source and cannot be said where they went.")
        rows=[]
        for n in names:
            c=st.columns([3,1,1,1])
            c[0].markdown(f"<div style='padding-top:32px;color:{INK}'>{n} — {files[n]['rows']:,} rows</div>",
                          unsafe_allow_html=True)
            mp=c[1].number_input("Mapped",0,10**7,files[n]["rows"],key=f"dm_pm_{n}")
            um=c[2].number_input("Unmapped",0,10**7,0,key=f"dm_pu_{n}")
            ex=c[3].number_input("Excluded",0,10**7,0,key=f"dm_pe_{n}")
            rows.append({"Dimension":n,"Source":files[n]["rows"],"Mapped":mp,"Unmapped":um,"Excluded":ex})
        pop=DM.population(rows); results["population"]=pop
        bad=pop[pop["Unexplained"]!=0]
        st.markdown(f"<div style='color:{INK}'>"
                    + ("All extracts reconcile: source equals mapped plus unmapped plus excluded, "
                       "residual zero on every line."
                       if not len(bad) else
                       f"<b>{len(bad)} of {len(pop)} extract(s) do not reconcile.</b> Unexplained: "
                       + ", ".join(f"{r['Dimension']} {r['Unexplained']:,}" for _,r in bad.iterrows())
                       + ". That residual is rows whose disposition is unknown.")
                    + "</div>", unsafe_allow_html=True)
        st.write("")
        st.dataframe(pop,use_container_width=True,hide_index=True)
        find.append(DM.finding(
            ("Every extract reconciles source to mapped plus unmapped plus excluded" if not len(bad)
             else f"{len(bad)} extract(s) do not reconcile"),
            DM.CALCULATED,
            "; ".join(f"{r['Dimension']}: {r['Source']:,} source against "
                      f"{r['Mapped']+r['Unmapped']+r['Excluded']:,} accounted, residual {r['Unexplained']:,}"
                      for _,r in pop.iterrows()),
            ("Nothing follows" if not len(bad)
             else "The residual is rows whose disposition is unknown, and it has to be named before the "
                  "population can be signed off")))

    # What the page measured, kept where the terminal can read it. Same numbers, same
    # column choices, one source: a figure quoted in the chat is the figure on this page.
    ss["dm_results"]={"checks":results,"choices":picked,"findings":find,
                      "nulls":sorted(x for x in nulls if x),
                      "extracts":{n:{"rows":int(len(files[n]["df"])),
                                     "columns":[str(c) for c in files[n]["df"].columns],
                                     "how_it_was_read":files[n]["note"]} for n in names}}

    # ---- findings & export --------------------------------------------------------
    with t_out:
        st.markdown("###### Findings")
        st.caption("Each line states what was measured and on what basis. Observed is read off the file, "
                   "Calculated is arithmetic over what was read, Inferred is an interpretation that still "
                   "needs confirming.")
        reg=DM.register(find)
        ecol={DM.OBSERVED:SAGE, DM.CALCULATED:ACCENT, DM.INFERRED:CLAY}
        for f in find:
            st.markdown(
                f"<div style='margin-bottom:12px'>"
                f"<span style='display:inline-block;padding:2px 9px;border-radius:2px;"
                f"background:{ecol.get(f['Evidence'],MUTE)};color:#fff;font-weight:600;font-size:10px;"
                f"letter-spacing:.08em'>{f['Evidence'].upper()}</span> "
                f"<span style='font-size:15px;color:{INK}'>&nbsp;{f['Finding']}</span><br>"
                f"<span style='color:{MUTE};font-size:13px'>Measured — {f['What was measured']}.<br>"
                f"Consequence — {f['Consequence if unaddressed']}.</span></div>",
                unsafe_allow_html=True)
        st.dataframe(reg,use_container_width=True,hide_index=True)
        st.divider()
        st.markdown("###### Export")
        sheets=[("Findings",reg),("Sources",pd.DataFrame(
            [{"Extract":k,"Rows":v["rows"],"Columns":v["df"].shape[1],"How it was read":v["note"]}
             for k,v in files.items()])),
            ("Null basis",pd.DataFrame([{"Token":t or "(blank)"} for t in sorted(nulls)]))]
        for n in names:
            sheets.append((f"Profile {_short(n)}",profiles[n]))
        if "reconcile" in results:
            sheets.append(("Reconciliation",results["reconcile"]["table"]))
        if "collisions" in results:
            sheets.append(("Collision pairs",results["collisions"][0]))
            sheets.append(("Collision values",results["collisions"][1]))
        if "hierarchy" in results:
            sheets.append(("Hierarchy",results["hierarchy"]["table"]))
        if "duplicates" in results:
            sheets.append(("Duplicate dimensions",results["duplicates"]))
        if "population" in results:
            sheets.append(("Population",results["population"]))
        st.download_button("⬇ Data analysis pack (XLSX)",DM.build_workbook(sheets),
                           "Organica_data_analysis.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary",key="dm_dl")
        st.caption("One sheet per extract profile, one per check, plus the findings and the null basis the "
                   "counts were taken on. A check that found nothing ships an empty sheet rather than no "
                   "sheet, so a missing check cannot read as a passing one.")

def _dm_ids(label, profiles, nulls):
    """The identifier columns of one extract, best first — ranked, not required to be perfect."""
    return DM.identifier_candidates(_dm_files()[label]["df"], profiles[label], nulls)

def _short(s):
    """A label short enough for a metric caption. The extension carries no information once
    the read note has said how the file was parsed, and a truncated one reads as a typo."""
    s=str(s).rsplit("/",1)[-1]
    for ext in (".csv",".xlsx",".xlsm",".xls"):
        s=s.replace(ext,"")
    return s[:30]

def _idx(cols, prefer):
    cols=list(cols)
    return next((cols.index(c) for c in (prefer or []) if c in cols),0)

# ---------------- per-run entrypoint ----------------
def render():
    ss.setdefault("raw", None); ss.setdefault("df", None); ss.setdefault("svc", None); ss.setdefault("files", [])
    ss.setdefault("assump", {**A.DEFAULTS}); ss.setdefault("user", None); ss.setdefault("mapping", {}); ss.setdefault("case", None); ss.setdefault("ts", None); ss.setdefault("chat", []); ss.setdefault("fin", None); ss.setdefault("term", [])
    # The model chosen in the terminal is the model the whole product uses for this session:
    # a picker that only governs one page would let two screens answer from two models and
    # give no way to tell which.
    ss.setdefault("model", AI.MODEL)
    AI.set_model(ss["model"])
    if "comps" not in ss:
        try: ss["comps"]=CM.reference(); ss["comps_label"]="reference public-SaaS set"
        except Exception: ss["comps"]=None; ss["comps_label"]=""

    AU.require_login(ss)   # gate the whole app (no DB; users from ORGANICA_USERS env)

    st.markdown(f"""<style>
.block-container{{padding-top:3rem;padding-bottom:4rem;max-width:1180px}}
h1,h2,h3,h4{{color:{INK};font-weight:600;letter-spacing:-.01em}}
h1{{font-weight:300;letter-spacing:.01em}}
[data-testid=stMetricValue]{{color:{INK};font-weight:500}}
[data-testid=stMetricLabel]{{color:{MUTE};text-transform:uppercase;letter-spacing:.06em;font-size:11px}}
section[data-testid=stSidebar]{{background:#F7F6F2;border-right:1px solid {LINE}}}
hr{{border-color:{LINE}}}
.stButton button{{border:1px solid {LINE};border-radius:2px;font-weight:500}}
</style>""", unsafe_allow_html=True)

    st.sidebar.markdown(f"<div style='font-size:20px;font-weight:600;color:{INK};letter-spacing:.02em'>Organica</div>"
                        f"<div style='color:{MUTE};font-size:11px;letter-spacing:.12em;margin-top:2px'>DECISION INTELLIGENCE</div>"
                        f"<div style='height:18px'></div>", unsafe_allow_html=True)
    # Three groups, by what the page is FOR rather than by the order the pages were built.
    #
    #   Data analysis   getting a source in, measuring it, and asking it questions.
    #                   Connect data and Data are how a source arrives, Data analysis is
    #                   the measurement of it, and Ask sits with them because it is an
    #                   open question about the data rather than a step toward a verdict.
    #   PE evaluations  the investment work: look at it, analyse it, decide, write the
    #                   paper, audit it. Audit, Journeys and Portfolio join it for an
    #                   admin because each produces an investment VIEW over the results.
    #   Tools           the surfaces you work THROUGH rather than stages of the work: the
    #                   terminal, the deliverability screen, monitoring, and taking it
    #                   away. Monitoring is here because it is not a step in reaching a
    #                   decision; it is what runs afterwards, on a schedule, over a
    #                   decision already taken. It remains ungated: the product promises
    #                   monitoring to everyone, and gating it told every viewer the product
    #                   monitors and then gave no way to reach it.
    #
    # Ask and Chat terminal are the two conversational surfaces and must not read as
    # duplicates. The navigation carries no captions at all — it is item names under three
    # group headings and nothing else — so the distinction is made where there is room to
    # make it properly: the opening sentence of each page says which is which. Ask answers
    # questions, the terminal builds things.
    admin=ss.get("role")=="admin"
    GROUPS=[("Data analysis", ["Connect data","Data","Data analysis","Ask"]),
            ("PE evaluations", ["Dashboard","Analyses","Business cases","IC paper"]
                               + (["Audit","Journeys","Portfolio"] if admin else [])),
            ("Tools", ["Chat terminal","Deliverability","Monitoring","Export"])]
    ALL=[p for _,ps in GROUPS for p in ps]
    ss.setdefault("page","Connect data")
    if ss["page"] not in ALL: ss["page"]=ALL[0]

    def _nav_key(g): return "nav_"+g.lower().replace(" ","_")

    def _nav_pick(g):
        # One selection across three widgets: the group that was clicked owns the page and
        # the other two are cleared, so the sidebar can never show two pages as current.
        v=ss.get(_nav_key(g))
        if v:
            ss["page"]=v
            for og,_ in GROUPS:
                if og!=g: ss[_nav_key(og)]=None

    for g,pages in GROUPS:
        # Re-derived from ss["page"] on every run rather than left to the widget, so a page
        # reached from anywhere else in the app still shows as the current one here.
        ss[_nav_key(g)]=ss["page"] if ss["page"] in pages else None
    for g,pages in GROUPS:
        st.sidebar.markdown(f"<div style='color:{MUTE};font-size:10px;letter-spacing:.10em;"
                            f"font-weight:600;margin:10px 0 -4px 2px'>{g.upper()}</div>",
                            unsafe_allow_html=True)
        # The group's own accessible label has to differ from the page names inside it, or
        # the Data analysis group and the Data analysis page are the same string twice and
        # a screen reader reads the group as one of its own options.
        st.sidebar.radio(f"{g} pages", pages, key=_nav_key(g), label_visibility="collapsed",
                         on_change=_nav_pick, args=(g,))
    page=ss["page"]
    # The strapline used to read DATA · UNDERSTAND · DECIDE · MONITOR, a four-stage
    # sequence the navigation no longer shows. It ended on MONITOR, and with Monitoring
    # under Tools that reads as a promise the groups do not keep. It now has one word per
    # group, in the order they appear: measure the data, evaluate the investment, operate
    # on it — the terminal, the deliverability screen, the monitoring run, the export.
    st.sidebar.markdown(f"<div style='color:{MUTE};font-size:10px;letter-spacing:.08em;"
                        f"margin:8px 0 2px 2px'>MEASURE · EVALUATE · OPERATE</div>",
                        unsafe_allow_html=True)
    st.sidebar.divider(); AU.sidebar_signout(ss)
    with st.sidebar.expander("Assumptions"):
        a=ss["assump"]
        a["loaded_fte"]=st.number_input("Loaded €/FTE",50_000,250_000,a["loaded_fte"],5_000)
        a["unit_rate"]=st.number_input("Unit cost €/unit/yr",0.0,5.0,float(a["unit_rate"]),0.01)
        a["egress_pct"]=st.slider("Egress % of revenue",0.0,0.10,a["egress_pct"],0.005)
        a["peer_floor"]=st.number_input("Peer price floor €",0,500_000,a["peer_floor"],1_000)
        a["mc_n"]=st.select_slider("Probabilistic draws",[20_000,50_000,100_000,200_000],a["mc_n"])
    ss.setdefault("terms",{**CR.TERMS})
    with st.sidebar.expander("Facility terms"):
        t=ss["terms"]
        st.caption("Deal-team input. Not inferred from the data room — every credit figure moves with these.")
        t["facility"]=st.selectbox("Instrument",["Unitranche","Senior term loan","Second lien","Holdco PIK"],
                                   index=["Unitranche","Senior term loan","Second lien","Holdco PIK"].index(t.get("facility","Unitranche")))
        q=st.number_input("Quantum drawn €m (0 = size it off leverage)", 0.0, 500.0,
                          float((t.get("quantum") or 0)/1e6), 0.5)
        t["quantum"]=q*1e6 if q>0 else None
        t["opening_leverage"]=st.number_input("Opening leverage ×",0.0,10.0,float(t["opening_leverage"]),0.25)
        t["base_rate"]=st.number_input("Base rate %",0.0,15.0,float(100*t["base_rate"]),0.05)/100
        t["margin"]=st.number_input("Margin %",0.0,15.0,float(100*t["margin"]),0.05)/100
        t["tenor"]=st.number_input("Tenor (years)",1,12,int(t["tenor"]))
        t["amort_pct"]=st.number_input("Amortisation % p.a.",0.0,20.0,float(100*t["amort_pct"]),0.5)/100
        t["cash_sweep"]=st.slider("Cash sweep %",0.0,1.0,float(t["cash_sweep"]),0.05)
        t["cash_balance"]=st.number_input("Cash €m",0.0,200.0,float(t["cash_balance"]/1e6),0.5)*1e6
        t["rcf_undrawn"]=st.number_input("Undrawn RCF €m",0.0,200.0,float(t["rcf_undrawn"]/1e6),0.5)*1e6
        st.caption("Covenants")
        t["cov_leverage"]=st.number_input("Leverage covenant ≤ ×",0.0,12.0,float(t["cov_leverage"]),0.25)
        t["cov_icr"]=st.number_input("Interest cover ≥ ×",0.0,12.0,float(t["cov_icr"]),0.25)
        t["cov_dscr"]=st.number_input("DSCR ≥ ×",0.0,6.0,float(t["cov_dscr"]),0.05)
        t["cov_min_liquidity"]=st.number_input("Minimum liquidity €m",0.0,100.0,float(t["cov_min_liquidity"]/1e6),0.5)*1e6

    if page=="Business cases":
        st.title("Business cases")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px;margin-bottom:14px'>Start from the decision, not a blank chat. "
                    f"Pick the call you're making and Organica runs a <b>fixed analytical route</b> to a verdict "
                    f"(Go / Conditional / Caution / Hold) with the evidence underneath — defensible and repeatable. "
                    f"<i>Open-ended exploration lives in Ask Organica.</i></div>",unsafe_allow_html=True)
        ALL=dict(C.CASES)
        for q in S.load_questions():
            ALL[f"custom::{q['title']}"]=C.make_custom(q["title"], q["question"], q["route"] or list(A.MENU))
        with st.expander("＋ Add your own question", expanded=not S.load_questions()):
            with st.form("add_question", clear_on_submit=True):
                ql=st.text_input("Your decision question", placeholder="e.g. Can we cut churn without losing margin?")
                t=st.text_input("Short title (optional)", placeholder="leave blank to use the question")
                route=st.multiselect("Analyses to run (optional — leave empty and the AI picks)", list(A.MENU), [])
                submitted=st.form_submit_button("Add question", type="primary")
            if submitted:
                if not ql.strip():
                    st.warning("Type a question first.")
                else:
                    title=(t.strip() or ql.strip())[:48]
                    chosen=route or AI.route_question(ql, list(A.MENU))
                    items=[x for x in S.load_questions() if x["title"]!=title]
                    items.append(dict(title=title, question=ql.strip(), route=chosen)); S.save_questions(items)
                    ss["case"]=f"custom::{title}"; st.rerun()
        if ss["df"] is None:
            st.info("Load data first — Connect data, or Data → Demo to try it now."); st.stop()
        df=ss["df"]; a=ss["assump"]; keys=list(ALL)
        for r0 in range(0,len(keys),4):
            cols=st.columns(4)
            for col,kk in zip(cols,keys[r0:r0+4]):
                if col.button(ALL[kk]['title'],key=f"case_{kk}",use_container_width=True): ss["case"]=kk
        sel=ss.get("case") if ss.get("case") in ALL else keys[0]; cc=ALL[sel]
        st.divider()
        hc1,hc2=st.columns([6,1]); hc1.subheader(cc['title'])
        if cc.get("custom") and hc2.button("Remove"):
            S.save_questions([x for x in S.load_questions() if f"custom::{x['title']}"!=sel]); ss["case"]=None; st.rerun()
        st.markdown(f"<div style='color:{MUTE};margin-top:-6px'>{cc['audience']} — {cc['question']}</div>",unsafe_allow_html=True)
        st.write("")
        R=run_all(df)
        # grounded analysis, cached per case+dataset+assumptions so it isn't re-called each rerun
        akey=f"{sel}|{R['Revenue quality']['kpis']['ARR']}|{R['Unit economics & margin']['kpis']['Fully-loaded margin']}"
        cache=ss.setdefault("_ans",{})
        if akey not in cache:
            with st.spinner("Analysing the question against the data…"):
                cache[akey]=C.intelligent_answer(cc,df,a,R)
        out=cache[akey]; vc=C.verdict_color(out["verdict"])
        st.markdown(f"<span style='display:inline-block;padding:3px 12px;border-radius:2px;background:{vc};color:#fff;"
                    f"font-weight:600;font-size:11px;letter-spacing:.08em'>{out['verdict'].upper()}</span> "
                    f"<span style='font-size:17px;color:{INK}'>&nbsp;{out['headline']}</span>",unsafe_allow_html=True)
        if out.get("_ai"): st.caption("grounded analysis of this question over the computed analytics · AI")
        st.write("")
        for b in out.get("bullets",[]): st.markdown(f"- {b}")
        if out.get("risk"): st.markdown(f"<div style='color:{CLAY};margin-top:8px'><b>Key risk</b> — {out['risk']}</div>",unsafe_allow_html=True)
        if out.get("action"): st.markdown(f"<div style='color:{ACCENT};margin-top:2px'><b>Next step</b> — {out['action']}</div>",unsafe_allow_html=True)
        st.divider(); st.markdown(f"**Evidence — route** · {' → '.join(cc['route'])}")
        for i,name in enumerate(cc["route"],1):
            st.markdown(f"###### {i}. {name}"); render_step(name,R,i); st.write("")
        ss["results"]=R

    elif page=="Connect data":
        st.title("Connect a data source")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>NetSuite · Salesforce · SAP · Microsoft Dynamics 365 · "
                    f"QuickBooks · Google Drive · or any file — the AI recognises the columns automatically, no mapping wizard. "
                    f"Below: Google Drive (service-account key); the ERP/CRM connectors are further down.</div>",unsafe_allow_html=True)
        st.markdown(f"<div style='border-left:4px solid {ACCENT};background:#F1EFE9;padding:12px 16px;"
                    f"margin:12px 0 8px 0;font-size:15px;color:{INK}'>"
                    f"<b>One service account, viewer rights — nothing leaves your data room.</b> "
                    f"Watermarks and handwriting are fine.</div>", unsafe_allow_html=True)
        st.caption("View-only data rooms are the normal case, not the exception. We read in place with "
                   "the rights you grant and nothing is downloaded or transferred.")
        st.write("")
        with st.expander("🔒 Security & data handling"):
            st.markdown("- **Tenant isolation** — one private instance + storage volume per client; no shared database, no co-mingling.\n"
                        "- **Your data, your model** — every figure is computed in your environment; your data never trains a shared model.\n"
                        "- **Credentials** — connector tokens and service-account keys are used in-memory for this session, not stored in code.\n"
                        "- **Encryption & access** — all traffic over HTTPS/TLS; authenticated, role-based login; no public access.\n"
                        "- **Auditability** — every headline number is traceable (provenance + formula-linked workbook).\n"
                        "- Architected to the SOC 2 control areas; a formal SOC 2 Type II certification is not yet completed — "
                        "control mapping available on request.")
        with st.expander("How to get a key (one-time)", expanded=ss["svc"] is None):
            st.markdown("1. Google Cloud Console → IAM → Service Accounts → create → Keys → Add key → JSON.\n"
                        "2. Enable the Drive API.\n3. Share your data-room folder with the service-account email (Viewer).\n"
                        "4. Upload the JSON key + paste the folder link.")
        key=st.file_uploader("Service-account JSON key", type=["json"]); link=st.text_input("Drive folder link or ID")
        c1,c2=st.columns(2)
        if c1.button("Test connection",type="primary") and key and link:
            try:
                svc,email=G.client_from_key(key.getvalue().decode()); ss["svc"]=svc; ss["fid"]=G.folder_id(link)
                ss["files"]=G.list_folder(svc, ss["fid"]); st.success(f"Connected as {email} · {len(ss['files'])} files")
            except Exception as e: st.error(f"Connection failed: {e}")
        if ss["files"]:
            names=[f"{f['name']}  ({f['mimeType'].split('.')[-1]})" for f in ss["files"]]
            pick=st.multiselect("Pull which files?", names, names[:1])
            if c2.button("Pull selected"):
                for i,f in enumerate(ss["files"]):
                    if names[i] in pick:
                        buf=G.download(ss["svc"], f); raw=G.to_dataframe(f, buf) if buf else None
                        if raw is not None: st.dataframe(raw.head()); autoload(raw)
                if ss["df"] is not None: show_mapping(ss["raw"])
        st.divider()
        with st.expander("NetSuite (SuiteQL) — pull live customer revenue from your ERP"):
            st.caption("Token-Based Auth (OAuth 1.0). Create an integration + access token in NetSuite; paste the keys.")
            nc1,nc2=st.columns(2)
            acct=nc1.text_input("Account ID", placeholder="1234567 or 1234567_SB1")
            ck=nc1.text_input("Consumer key"); cs=nc1.text_input("Consumer secret", type="password")
            tid=nc2.text_input("Token ID"); tsx=nc2.text_input("Token secret", type="password")
            q=st.text_area("SuiteQL", NS.DEFAULT_QUERY, height=120)
            if st.button("Pull from NetSuite", type="primary"):
                if not all([acct,ck,cs,tid,tsx]): st.warning("Fill in the account ID and all four keys.")
                else:
                    try:
                        raw=NS.suiteql(acct,ck,cs,tid,tsx,q)
                        if len(raw): st.success(f"Pulled {len(raw)} rows"); st.dataframe(raw.head()); autoload(raw); show_mapping(raw)
                        else: st.warning("Query returned no rows.")
                    except Exception as e: st.error(f"NetSuite error: {e}")
        CX.render_panels(st, ss, autoload, show_mapping)
        st.divider()
        st.subheader("Data rooms")
        DR.render_panels(st, ss, autoload, show_mapping)

    elif page=="Data":
        st.title("Data")
        tab1,tab3,tab2=st.tabs(["Upload a file","Data-room export (ZIP)","Verexa — sample data room"])
        with tab1:
            up=st.file_uploader("Data-room file — CSV · Excel · PDF", type=["csv","xlsx","xls","pdf"])
            if up is not None:
                tables=DOC.extract_tables(up.getvalue(), up.name)
                errs=[l for l,d in tables if d is None]
                tables=[(l,d) for l,d in tables if d is not None]
                if errs:
                    st.error(f"That file could not be read — {errs[0]}")
                elif not tables:
                    st.warning("No analysable tables found in that file.")
                else:
                    best=DOC.best_table(tables); bi=tables.index(best) if best in tables else 0
                    labels=[f"{l}  ·  {len(d)}×{d.shape[1]}" for l,d in tables]
                    pick=st.selectbox(f"AI found {len(tables)} table(s) — best pre-selected", labels, index=bi)
                    raw=tables[labels.index(pick)][1]
                    st.dataframe(raw.head(8), use_container_width=True)
                    if st.button("Use this table ▶", type="primary"): autoload(raw)
                    if ss.get("raw") is not None: show_mapping(ss["raw"])
        with tab3:
            st.caption("Every data-room provider can export the room as a ZIP, so this route works "
                       "for all of them without credentials — Datasite, Intralinks, Ansarada, iDeals "
                       "and the rest keep their APIs behind an enterprise agreement, and this needs none.")
            zup=st.file_uploader("Data-room export — ZIP of the whole room", type=["zip"], key="zipup")
            if zup is not None:
                entries=DR.ingest_archive(zup.getvalue(), zup.name)
                s_=DR.summarise(entries)
                # Held in session rather than noted here: autoload resets the run's register,
                # and the room was read before the table was chosen.
                ss["room"]={"name":zup.name, **{k:s_[k] for k in ("data_files","parsed","skipped")},
                            "unread":[e["path"] for e in entries
                                      if e["kind"]!="data" or not e["tables"]][:40]}
                st.caption(f"{s_['data_files']} data file(s) · {s_['parsed']} parsed · "
                           f"{s_['tables']} table(s) found · {s_['skipped']} not data files")
                choices=[(f"{e['path']}  ·  {l}  ·  {d.shape[0]}×{d.shape[1]}", d)
                         for e in entries for l,d in e["tables"]]
                if not choices:
                    st.warning("No analysable tables found in that export.")
                    st.dataframe(pd.DataFrame([{"file":e["path"],"note":e["note"]} for e in entries]),
                                 use_container_width=True, hide_index=True)
                else:
                    pick=st.selectbox(f"{len(choices)} table(s) across the room", [c[0] for c in choices])
                    raw=dict(choices)[pick]
                    st.dataframe(raw.head(8), use_container_width=True)
                    if st.button("Use this table ▶", type="primary", key="zipuse"): autoload(raw)
                    with st.expander("Everything found in the export"):
                        st.dataframe(pd.DataFrame([{"file":e["path"],"type":e["kind"],
                                                    "tables":len(e["tables"]),"note":e["note"]}
                                                   for e in entries]),
                                     use_container_width=True, hide_index=True)
                    if ss.get("raw") is not None: show_mapping(ss["raw"])

        with tab2:
            st.caption("**Verexa Software** — a €13.6m-ARR vertical-SaaS company, PE-owned, preparing a refinancing. Real-world book (anonymised & de-referenced): customers, a 15-month MRR time-series, and 3 years of quarterly P&L.")
            if st.button("Load sample book",type="primary"):
                load_demo()
            if ss["df"] is not None and ss.get("raw") is not None: show_mapping(ss["raw"])
        if ss.get("ts") is not None:
            st.caption(f"Time-series loaded: {ss['ts'].iloc[:,0].nunique()} customers × {ss['ts'].iloc[:,1].nunique()} months → retention is live.")
        if ss["df"] is not None:
            if ss.get("raw") is not None:
                rd=A.readiness(ss["raw"], ss.get("mapping",{}))
                rc="#5E7C6E" if rd["score"]>=80 else ("#9C6B4F" if rd["score"]>=60 else "#9C2B2B")
                st.markdown(f"<b>Data readiness</b> &nbsp;<span style='background:{rc};color:#fff;padding:2px 10px;border-radius:2px;font-weight:600'>{rd['score']}/100</span>",unsafe_allow_html=True)
                st.dataframe(rd["table"], use_container_width=True, hide_index=True)
            st.divider(); st.subheader("Active dataset — validate"); validation_view(ss["df"])
            st.divider()
            fup=st.file_uploader("Add financials — P&L / balance sheet (long: line_item · period · value)", type=["csv","xlsx"], key="finup")
            if fup is not None:
                ss["fin"]=pd.read_csv(fup) if fup.name.endswith("csv") else pd.read_excel(fup); st.success("Financials loaded — see Dashboard & Analyses → Financials")
            if ss.get("fin") is not None:
                st.caption(f"Financials loaded · {len(ss['fin'])} rows → margin trend, EBITDA bridge, working capital & FCF are live.")

    elif page=="Data analysis":
        data_analysis_page()

    elif page=="Chat terminal":
        chat_terminal_page()

    elif page=="Dashboard":
        st.title("Decision dashboard")
        if ss["df"] is None: st.warning("Load data first (Data tab)."); st.stop()
        if ss.get("is_demo"):
            st.caption("Verexa is an invented company used to demonstrate Organica — not a real business. "
                       "Its data is anonymised and de-referenced.")
        R=run_all(ss["df"])
        k=st.columns(5)
        for col,(label,val) in zip(k,[("ARR",R["Revenue quality"]["kpis"]["ARR"]),
            ("Fully-loaded margin",R["Unit economics & margin"]["kpis"]["Fully-loaded margin"]),
            ("EBITDA",R["Unit economics & margin"]["kpis"]["EBITDA"]),
            ("Margin — probabilistic median",R["Self-validation"]["kpis"]["Margin (MC median)"]),
            ("Coherent",R["Self-validation"]["kpis"]["Coherent"])]): col.metric(label,val)
        with st.expander("Show the math — how each headline number is computed"):
            st.dataframe(PV.show_math(R, ss["assump"]), use_container_width=True, hide_index=True)
        with st.expander(f"Benchmark comparables — {len(ss['comps']) if ss.get('comps') is not None else 0} in '{ss.get('comps_label','')}'  ·  change the comp universe"):
            opt=st.radio("Comp set", ["Reference public-SaaS set","Damodaran sectors (NYU Stern)","Upload comps (CSV)","My portfolio"],
                         index=0, horizontal=True, key="cm_opt", label_visibility="collapsed")
            if opt=="Reference public-SaaS set":
                try: ss["comps"]=CM.reference(); ss["comps_label"]="reference public-SaaS set"
                except Exception: pass
            elif opt=="Damodaran sectors (NYU Stern)":
                try: ss["comps"]=CM.damodaran(); ss["comps_label"]="Damodaran software/IT sectors (NYU Stern)"
                except Exception as e: st.error(f"Damodaran set unavailable: {e}")
                st.caption("Sector medians from Aswath Damodaran's free industry-average datasets (NYU Stern), "
                           "refreshed each January via tools/fetch_damodaran.py. Software & IT-services sectors only.")
            elif opt=="Upload comps (CSV)":
                st.markdown("Upload a CSV of the comparables you trust — e.g. a **Capital IQ / PitchBook / Bloomberg "
                            "export, or a Gartner/Damodaran extract**. One row per comparable. Columns (any subset; "
                            "percentages as plain numbers, multiples as ×):")
                st.code("company, segment, ebitda_margin, rev_growth, rule_of_40, nrr, ev_revenue, ev_ebitda\n"
                        "Example Co, Vertical SaaS, 32, 18, 50, 112, 9, 28", language="text")
                st.download_button("⬇ Download CSV template", CM.template_csv(), "organica_comps_template.csv", "text/csv")
                up=st.file_uploader("Your comps CSV", type=["csv"], key="cmup")
                if up is not None:
                    try: ss["comps"]=pd.read_csv(up); ss["comps_label"]="your uploaded comps"; st.success(f"{len(ss['comps'])} comparables loaded — re-open Dashboard to apply.")
                    except Exception as e: st.error(f"Comps error: {e}")
            else:
                names=S.list_companies()
                if len(names)>=2:
                    if st.button("Build comp set from my portfolio"):
                        with st.spinner("Analysing portfolio companies…"):
                            ss["comps"]=CM.from_portfolio(names, S.load_company, ss["assump"], PF.analyze_company); ss["comps_label"]="your portfolio"
                        st.success(f"Benchmarking against {len(ss['comps'])} portfolio companies — re-open Dashboard to apply.");
                else:
                    st.info("Add ≥2 companies in Portfolio to benchmark against your own book.")
            if ss.get("comps") is not None and len(ss["comps"]):
                st.caption(f"Benchmark is computed against {len(ss['comps'])} comparables · {ss.get('comps_label','')}. "
                           f"Confirm comparability before relying.")
                st.dataframe(ss["comps"].head(20), use_container_width=True, hide_index=True)
        st.write("")
        c1,c2=st.columns(2)
        with c1: chart_for("Revenue quality",R,"d")
        with c2: chart_for("Scenario & stress",R,"d")
        c3,c4=st.columns(2)
        with c3: chart_for("Self-validation",R,"d")
        with c4: chart_for("Pricing",R,"d")
        if "Retention" in R:
            st.divider(); st.markdown("**Retention & ARR bridge**")
            rk=R["Retention"]["kpis"]; kk=st.columns(len(rk))
            for c,(lab,v) in zip(kk, rk.items()): c.metric(lab, v)
            r1,r2=st.columns(2)
            with r1: chart_for("Retention",R,"d")
            cv=R["Retention"]["series"]["curve"]
            with r2: _fig(px.line(x=cv.index.astype(str),y=cv.values,title="Cohort logo retention %",labels={"x":"","y":"%"},color_discrete_sequence=[SAGE]),"ret_curve_d")
        if "Financials" in R:
            st.divider(); st.markdown("**Financials (P&L)**")
            fk=R["Financials"]["kpis"]; fc=st.columns(len(fk))
            for c,(lab,v) in zip(fc,fk.items()): c.metric(lab,v)
            g1,g2=st.columns(2)
            with g1: chart_for("Financials",R,"d")
            se=R["Financials"]["series"]["ebitda"]
            with g2: _fig(px.bar(x=se.index.astype(str),y=se.values,title="EBITDA by quarter (€m)",labels={"x":"","y":"€m"},color_discrete_sequence=[SAGE]),"fin_eb_d")
        st.divider()
        with st.expander("Snapshots — save this run & compare over time"):
            flat={}
            for kn in ["Revenue quality","Unit economics & margin","Retention","Valuation","Self-validation"]:
                if kn in R:
                    for lab,v in R[kn]["kpis"].items(): flat[lab]=v
            sc1,sc2=st.columns([3,1])
            snm=sc1.text_input("Name", value=f"run {datetime.date.today().isoformat()}", label_visibility="collapsed")
            if sc2.button("Save snapshot"): S.save_snapshot(snm, flat); st.success("Saved")
            snaps=S.list_snapshots()
            if snaps:
                rows=[{"snapshot":s, **S.load_snapshot(s)} for s in snaps]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        ss["results"]=R

    elif page=="Deliverability":
        st.title("Deliverability")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px;margin-bottom:14px'>Not can they hit the margin, but "
                    f"<b>which years are executable</b>. Organica models management's own EBITDA trajectory year by year, "
                    f"decomposes each annual step into the lever that has to carry it <i>at its own timing</i> — base drift, "
                    f"the cost-to-serve programme, the systems enablers — and treats pricing as the <b>residual</b>, never the "
                    f"assumed answer. The year a lever is asked to move before it exists is where execution risk enters.</div>",
                    unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first — Connect data, or Data → Verexa sample."); st.stop()
        R=run_all(ss["df"])
        if "Deliverability" not in R: st.warning("Deliverability view unavailable for this dataset."); st.stop()
        dl=R["Deliverability"]
        cols=st.columns(len(dl["kpis"]))
        for c,(kk,vv) in zip(cols,dl["kpis"].items()): c.metric(kk,vv)
        st.write("")
        fr=dl.get("first_risk")
        if fr:
            st.markdown(f"<div style='border-left:3px solid #B23A48;padding:8px 14px;background:#FBF3F2'>"
                        f"<b style='color:#B23A48'>Finding — {dl['notes'][0]}</b><br>"
                        f"<span style='color:{INK}'>{dl['notes'][1]}</span></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='border-left:3px solid {SAGE};padding:8px 14px;background:#F2F6F3'>"
                        f"<b style='color:{SAGE}'>Finding — {dl['notes'][0]}</b><br>"
                        f"<span style='color:{INK}'>{dl['notes'][1]}</span></div>", unsafe_allow_html=True)
        st.write("")
        chart_for("Deliverability",R,suffix="page")
        st.dataframe(dl["tables"]["Year-by-year deliverability"],use_container_width=True,hide_index=True)
        st.caption("Illustrative, MODELLED on the Verexa demo book. The planned trajectory and lever schedule are "
                   "demonstration assumptions, not a client result; the method — decompose the plan, credit each lever "
                   "from the year it becomes available, price is the residual — is the point. Every figure carries its "
                   "evidence class in export.")

    elif page=="IC paper":
        st.title("IC paper")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>The committee's own template, assembled from the "
                    f"reconciled fact base. Each section declares where its content comes from, and the sections a "
                    f"data room cannot answer are left empty rather than drafted.</div>", unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first — Connect data, or Data → Verexa."); st.stop()
        R=ss.get("results") or run_all(ss["df"]); a=ss["assump"]; t=_pinned_terms()
        currency_note(); basis_note(); room_note(); honesty_panel("ic"); trust_copy("ic")
        stamp=datetime.date.today().isoformat(); comp=ss.get("company","Verexa Software")
        risk=_risk_pack(R, a, t)
        secs=IPR.build(R, df=ss["df"], a=a, terms=t, company=comp, stamp=stamp,
                       journeys_mod=J, prov_mod=PV, risk=risk)
        cov=IPR.coverage(secs)
        c=st.columns(4)
        c[0].metric("Sections in the template", cov["total"])
        c[1].metric("Computed from the data room", cov["engine"])
        c[2].metric("Computed from the terms", cov["terms"])
        c[3].metric("Deal-team sections", cov["dealteam"])
        st.caption(cov["summary"])
        st.divider()
        reg=pd.DataFrame([(s["n"],s["title"],s["source"],s["question"]) for s in secs],
                         columns=["#","Section","Source","The question it answers"])
        st.dataframe(reg,use_container_width=True,hide_index=True,height=430)
        st.divider()
        pick=st.selectbox("Preview a section", [f"{s['n']}. {s['title']}" for s in secs])
        s=secs[[f"{x['n']}. {x['title']}" for x in secs].index(pick)]
        st.markdown(f"**{s['n']}. {s['title']}** &nbsp; <span style='color:{MUTE}'>{s['source']} · {s['question']}</span>",
                    unsafe_allow_html=True)
        for kind,val in s["blocks"]:
            if kind=="head": st.markdown(f"**{val}**")
            elif kind=="note" and val: st.markdown(f"<div style='color:{MUTE}'>{val}</div>",unsafe_allow_html=True)
            elif kind=="gap": st.warning(val)
            elif kind=="asks":
                st.markdown("This section must answer:")
                for x in val: st.markdown(f"- {x}")
            elif kind=="kpis" and val:
                cc=st.columns(max(len(val),1))
                for col,(k,v) in zip(cc,val.items()): col.metric(k,v)
            elif kind=="table" and val is not None and len(val):
                st.dataframe(val,use_container_width=True,hide_index=True)

        # THE CLICK-THROUGH. Asked live: "can you click on that and look at the source
        # document?" Traceability is the claim, so a flagged figure has to lead to the
        # records behind it, not to a description of them.
        if s["n"]==16:
            st.divider()
            st.markdown("**Open the source**")
            st.caption("Every figure above resolves to the records that produced it. This is the "
                       "reconciliation flag, traced back to the two files and the customers that "
                       "explain the difference.")
            trace_block(key="ic16")

        st.divider()
        d1,d2=st.columns(2)
        try:
            d1.download_button("⬇ IC paper (PDF)", IPR.build_pdf(secs,comp,stamp,cov),
                               "Organica_IC_paper.pdf","application/pdf",type="primary")
        except Exception as e: d1.caption(f"PDF n/a: {e}")
        d2.download_button("⬇ IC paper (Markdown)", IPR.build_md(secs,comp,stamp,cov),
                           "Organica_IC_paper.md","text/markdown")
        ss["results"]=R

    elif page=="Analyses":
        st.title("Analyses")
        if ss["df"] is None: st.warning("Load data first."); st.stop()
        opts=list(A.MENU)+(["Retention"] if ss.get("ts") is not None else [])+(["Financials"] if ss.get("fin") is not None else [])+["Accounts"]
        pick=st.multiselect("Run which analyses?", opts, opts)
        R=run_all(ss["df"])
        for name in pick:
            if name in R:
                st.subheader(name); render_step(name,R,f"an{name}")
                if name=="Inconsistencies" and ss.get("ts") is not None:
                    with st.expander("Open the source — what does not tie, and why"):
                        trace_block(key="an")
                st.divider()

    elif page=="Ask":
        st.title("Ask Organica")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'><b>Ask answers questions; the Chat terminal builds things.</b> "
                    f"This page is open-ended and conversational — ask anything in plain English. "
                    f"Every answer is computed from your data and cites the figures, never invented, so there is nothing to "
                    f"correct: instead you set <b>house rules and assumptions</b> once and Organica applies them to every answer, "
                    f"learning only from you. <i>For a structured call with a verdict, use Business cases.</i></div>", unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first — Connect data, or Data → Verexa sample."); st.stop()
        R=run_all(ss["df"]); ctx=C.build_context(R)
        learned=S.load_feedback()
        if learned:
            with st.expander(f"✓ Organica has learned {len(learned)} rule(s) from you — applied to every answer", expanded=False):
                for i,it in enumerate(learned):
                    ca,cb=st.columns([0.93,0.07])
                    ca.markdown(f"- {it['note']}")
                    if cb.button("✕",key=f"unlearn{i}",help="Forget this"):
                        S.save_feedback([x for j,x in enumerate(learned) if j!=i]); st.rerun()
        for m in ss["chat"]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        q=st.chat_input("e.g. Which tier should we reprice first, and what does it add to EV?")
        if q:
            ss["chat"].append({"role":"user","content":q})
            with st.chat_message("user"): st.markdown(q)
            with st.chat_message("assistant"):
                with st.spinner("Analysing…"):
                    ans=AI.chat(ss["chat"], ctx, q, learned) or "I can only answer from the loaded analytics — try ARR, margin, pricing, retention, valuation or returns."
                st.markdown(ans)
            ss["chat"].append({"role":"assistant","content":ans})
        # feedback loop — teach Organica from the last answer; it persists and applies to every future answer
        if ss["chat"] and ss["chat"][-1]["role"]=="assistant":
            lastq=next((ss["chat"][i]["content"] for i in range(len(ss["chat"])-1,-1,-1) if ss["chat"][i]["role"]=="user"),"")
            with st.expander("✎ Teach Organica — set a house rule or a simulation assumption", expanded=False):
                with st.form("teach_form",clear_on_submit=True):
                    note=st.text_input("Add a rule or an assumption Organica should apply",
                                       placeholder="e.g. treat setup fees as non-recurring · assume 12% churn in the downside · we load 15% overhead on COGS")
                    if st.form_submit_button("Save — apply to every future answer",type="primary") and note.strip():
                        S.add_feedback(note.strip(),"teach",lastq); st.success("Learned. Organica will apply this from now on."); st.rerun()
        if ss["chat"]:
            if st.button("Clear conversation"): ss["chat"]=[]; st.rerun()

    elif page=="Journeys":
        st.title("Journeys")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px;margin-bottom:14px'>A predefined evaluation process — "
                    f"it diagnoses the company, decides where the data warrants action, and emits agent-ready "
                    f"playbooks (Markdown) to correct or monitor each issue.</div>", unsafe_allow_html=True)
        if ss["df"] is None:
            st.info("Load data first — Connect data, or Data → Demo."); st.stop()
        df=ss["df"]; a=ss["assump"]; jkeys=list(J.JOURNEYS)
        cols=st.columns(len(jkeys))
        for col,jk in zip(cols,jkeys):
            jj=J.JOURNEYS[jk]
            if col.button(f"{jj['title']}\n\n{jj['audience']}", key=f"j_{jk}", use_container_width=True): ss["journey"]=jk
        sel=ss.get("journey") if ss.get("journey") in J.JOURNEYS else jkeys[0]
        R=run_all(df); res=J.run_journey(sel, df, a, R); jj=res["journey"]
        st.divider(); st.subheader(jj["title"])
        vc={"Action required":"#9C2B2B","Watch items":"#9C6B4F","Clean":"#5E7C6E"}[res["verdict"]]
        st.markdown(f"<span style='display:inline-block;padding:3px 12px;border-radius:2px;background:{vc};color:#fff;"
                    f"font-weight:600;font-size:11px;letter-spacing:.06em'>{res['verdict'].upper()}</span> "
                    f"<span style='color:{MUTE}'>&nbsp;{jj['audience']} · {res['crit']} critical · {res['warn']} watch</span>", unsafe_allow_html=True)
        st.caption(jj["purpose"]); st.write("")
        for sname,fs in res["stages"]:
            st.markdown(f"###### {sname}")
            for f in fs:
                dot={"critical":"🔴","warning":"🟠","ok":"🟢"}[f["severity"]]
                st.markdown(f"{dot} **{f['title']}** — {f['insight']}  \n"
                            f"<span style='color:{MUTE};font-size:13px'>{f['metric']}: {f['observed']} "
                            f"(threshold {f['threshold']}) · → {f['recommendation']}</span>", unsafe_allow_html=True)
            st.write("")
        if res["issues"]:
            st.divider(); st.markdown("**Prioritized actions**")
            for i,f in enumerate(res["issues"],1):
                tpl=J.ISSUE.get(f["issue_type"], J.ISSUE["margin"])
                st.markdown(f"{i}. **[{f['severity'].upper()}]** {f['recommendation']} "
                            f"<span style='color:{MUTE}'>· agent: {tpl['agent']} · mode: {tpl['mode']}</span>", unsafe_allow_html=True)
        st.divider()
        stamp=datetime.date.today().isoformat()
        ctx=C.build_context(R); _tc={}
        def _tf(f):
            if f["title"] not in _tc:
                tpl=J.ISSUE.get(f["issue_type"], J.ISSUE["margin"])
                _tc[f["title"]]=AI.tailor_playbook(f, ctx, tpl["agent"], tpl["objective"])
            return _tc[f["title"]]
        jkey=f"{sel}|{R['Unit economics & margin']['kpis']['Fully-loaded margin']}|{len(res['issues'])}"
        zc=ss.setdefault("_jzip",{})
        if jkey not in zc:
            with st.spinner("Tailoring agent playbooks to the numbers…"):
                zc[jkey]=dict(zip=J.bundle_zip(res, "Verexa Software", stamp, _tf),
                              preview=(J.agent_brief_md(res["issues"][0], jj["title"], "Verexa Software", stamp, _tf(res["issues"][0])) if res["issues"] else ""))
        pack=zc[jkey]
        c1,c2=st.columns(2)
        c1.download_button(f"⬇ Agent briefs (.zip · {len(res['issues'])} files)", pack["zip"],
                           f"{sel}_agent_briefs.zip", "application/zip", type="primary")
        c2.download_button("⬇ Journey report (.md)", J.journey_report_md(res, "Verexa Software", stamp),
                           f"{sel}_report.md", "text/markdown")
        if res["issues"]:
            st.caption("Each agent brief carries an AI-tailored playbook grounded in these numbers (predefined template as fallback).")
            with st.expander("Preview an agent brief (.md)"):
                st.code(pack["preview"], language="markdown")
            st.divider(); st.markdown("**Close the loop — dispatch an agent**")
            st.caption("'Monitor' registers the metric on the watchlist (the scheduled agent then watches it); "
                       "'Correct' logs a remediation task and POSTs the brief to your agent runner / webhook (ALERT_WEBHOOK).")
            for i,f in enumerate(res["issues"]):
                tpl=J.ISSUE.get(f["issue_type"], J.ISSUE["margin"])
                dc=st.columns([0.62,0.19,0.19])
                dc[0].markdown(f"**{f['title']}** <span style='color:{MUTE}'>· agent: {tpl['agent']} · suggests: {tpl['mode']}</span>", unsafe_allow_html=True)
                if dc[1].button("▶ Monitor", key=f"mon{i}"):
                    S.dispatch_action(f["title"],"monitor","Verexa Software",metric=f["metric"],trigger=str(f["threshold"]),status="watching")
                    st.success(f"Registered — the scheduled agent will watch {f['metric']}."); st.rerun()
                if dc[2].button("▶ Correct", key=f"cor{i}"):
                    sent=_dispatch_webhook(f, J.agent_brief_md(f, jj["title"], "Verexa Software", stamp, _tf(f)))
                    S.dispatch_action(f["title"],"correct","Verexa Software",metric=f["metric"],
                                      detail=("sent to webhook" if sent else "queued"),status=("dispatched" if sent else "queued"))
                    st.success("Remediation dispatched"+(" + sent to your webhook." if sent else " (queued — set ALERT_WEBHOOK to auto-send).")); st.rerun()
            acts=S.load_actions()
            if acts:
                with st.expander(f"Dispatched actions ({len(acts)})"):
                    st.dataframe(pd.DataFrame(acts)[["title","mode","metric","status","detail"]], use_container_width=True, hide_index=True)
        ss["results"]=R

    elif page=="Monitoring":
        st.title("Monitoring over the hold period")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>The same code path as the IC paper, re-run on a later "
                    f"reporting period. The prior period is <b>recomputed, not stored</b>, so every movement is "
                    f"like-for-like. What is not built is listed at the bottom of this page.</div>",
                    unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first."); st.stop()
        a=ss["assump"]; t=ss["terms"]; comp=ss.get("company","Verexa Software")
        ts=ss.get("ts")
        tab_live,tab_cap=st.tabs(["Current position","What runs today, and what does not"])

        with tab_live:
            if ts is None:
                st.info("Monitoring needs a reporting time series. Load the sample book (it includes the "
                        "monthly series) or upload one on the Data page.")
                st.markdown("**Without a series, this is what still runs:** the threshold gates below, "
                            "re-applied on each new dataset.")
                R=run_all(ss["df"]); crit=[]; watch=[]
                for k in J.JOURNEYS:
                    for f in J.run_journey(k, ss["df"], a, R)["issues"]:
                        (crit if f["severity"]=="critical" else watch).append((J.JOURNEYS[k]["title"], f))
                cc=st.columns(3)
                cc[0].metric("Journeys watched", len(J.JOURNEYS)); cc[1].metric("Critical", len(crit)); cc[2].metric("Watch", len(watch))
                for jt,f in crit+watch:
                    st.markdown(f"**{f['title']}** <span style='color:{MUTE}'>· {jt} · {f['observed']}</span>",
                                unsafe_allow_html=True)
            else:
                mos=HM.months(ts)
                cA,cB,cC=st.columns([1.2,1,1])
                appr=cA.selectbox("Facility drawn at", mos, index=0,
                                  help="The facility is sized once here and pinned. Later periods are measured "
                                       "against the debt actually drawn.")
                nowm=cB.selectbox("Reporting period", mos, index=len(mos)-1)
                pri=cC.selectbox("Compared with", ["(none)"]+mos,
                                 index=(mos.index(mos[max(0,len(mos)-4)])+1))
                if appr != ss.get("appr_month"):
                    ss["appr_month"]=appr; t["quantum"]=None          # re-pin on the chosen month
                pinned=_pinned_terms()
                now=HM.state_at(ts, ss["df"], nowm, a, pinned)
                prior=None if pri=="(none)" else HM.state_at(ts, ss["df"], pri, a, pinned)
                st.caption(f"Facility pinned at €{pinned['quantum']/1e6:.1f}m drawn on the {appr} book, "
                           f"covenants as documented at approval. Terms unchanged since.")
                wl=HM.watchlist(now, prior, a, pinned); sm=HM.summary(wl, now, prior)
                k=st.columns(4)
                k[0].metric("Items monitored", sm["items"])
                k[1].metric("In breach", sm["breaches"])
                k[2].metric("Tight (<20% cushion)", sm["tight"])
                k[3].metric("Moving the wrong way", sm["worsening"])
                st.divider()
                def _style(row):
                    c={"BREACH":"#9C2B2B","tight":"#9C6B4F"}.get(row["Status"],"")
                    return [f"color:{c}" if c else "" for _ in row]
                st.dataframe(wl.style.apply(_style,axis=1), use_container_width=True, hide_index=True)
                st.caption("Covenants are the levels documented at approval. Operating KPI thresholds are "
                           "policy levels set by the lender, not documented covenants — they are early "
                           "warning, not default.")
                with st.expander("What the borrower reported, period by period", expanded=False):
                    try:
                        rep=HM.reported(ts, ss["df"], mos, a, pinned, every=2)
                        st.dataframe(rep["table"],use_container_width=True,hide_index=True)
                        st.caption(rep["note"])
                    except Exception as e:
                        st.caption(f"reporting history n/a: {e}")
                drv=HM.drivers(now, prior)
                fc=None
                try: fc=HM.forecast(ts, ss["df"], mos, a, pinned)
                except Exception as e: st.caption(f"trend n/a: {e}")
                if drv is not None:
                    st.markdown("**Why it moved**")
                    st.dataframe(drv["table"],use_container_width=True,hide_index=True)
                    st.caption(drv["note"])
                if fc is not None:
                    st.markdown("**Will the next test be met?**")
                    st.dataframe(fc["table"],use_container_width=True,hide_index=True)
                    st.caption(fc["note"])
                try:
                    _mc=CXR.monte_carlo(now["R"], a, pinned, horizon_years=1.0)
                    _by=CXR.bayesian(ts, ss["df"], mos, a, pinned, 12, R_for_terms=now["R"])
                    _co=CXR.coherence(now["R"], a, pinned, _mc, _by)
                    st.markdown("**The same question as a probability**")
                    st.caption(f"Computed at the {nowm} reporting position, the one selected above. "
                               f"The Audit page answers the same question at the position in the IC "
                               f"paper, so the two differ by design: the borrower has deteriorated "
                               f"between them.")
                    pc=st.columns(4)
                    for col,(kk,vv) in zip(pc, list(_mc["kpis"].items())[:4]): col.metric(kk,vv)
                    pp=st.columns(2)
                    pp[0].caption("Assumed forward distribution")
                    pp[0].dataframe(_mc["tables"]["Probability of breach"],use_container_width=True,hide_index=True)
                    pp[1].caption(f"Learned from {_by['kpis']['Observations']} reported periods "
                                  f"(drift {_by['kpis']['Inferred EBITDA drift']})")
                    pp[1].dataframe(_by["tables"]["Probability of breach"],use_container_width=True,hide_index=True)
                    with st.expander("Simulation inputs and the posterior"):
                        st.dataframe(_mc["tables"]["Simulation inputs"],use_container_width=True,hide_index=True)
                        st.dataframe(_by["tables"]["Posterior, learned from the borrower's reporting"],
                                     use_container_width=True,hide_index=True)
                    st.markdown("**Coherence**")
                    st.dataframe(_co["tables"]["Coherence"],use_container_width=True,hide_index=True)
                    if _co["flags"]:
                        st.warning("The assumed distribution is more optimistic than what the borrower "
                                   "has actually reported. The learned figure is the one to underwrite to.")
                    st.caption(" ".join(_co["notes"]))
                except Exception as e:
                    st.caption(f"probabilistic layer n/a: {e}")
                currency_note(); basis_note(); room_note(); honesty_panel("mon"); trust_copy("mon")
                st.divider()
                cL,cR=st.columns([1,1])
                with cL:
                    st.markdown("**Direction of travel**")
                    try:
                        pts=[HM.state_at(ts, ss["df"], m, a, pinned) for m in mos[::2]]
                        tr=pd.DataFrame({"period":[p["month"] for p in pts],
                                         "Net leverage":[float(str(p["metrics"]["kpis"]["Net leverage"]).replace("×","")) for p in pts],
                                         "Interest cover":[float(str(p["metrics"]["kpis"]["Interest cover"]).replace("×","")) for p in pts]})
                        fig=go.Figure()
                        fig.add_scatter(x=tr["period"],y=tr["Net leverage"],name="Net leverage",line=dict(color=CLAY))
                        fig.add_scatter(x=tr["period"],y=tr["Interest cover"],name="Interest cover",line=dict(color=ACCENT))
                        fig.add_hline(y=float(pinned["cov_leverage"]),line=dict(color=CLAY,dash="dot"),
                                      annotation_text="leverage covenant")
                        fig.add_hline(y=float(pinned["cov_icr"]),line=dict(color=ACCENT,dash="dot"),
                                      annotation_text="interest-cover covenant")
                        fig.update_layout(title="Covenant path, recomputed each period",yaxis_title="×",legend_title="")
                        _fig(fig,"covpath")
                    except Exception as e:
                        st.caption(f"path n/a: {e}")
                with cR:
                    st.markdown("**The alert, exactly as it is delivered**")
                    msg=HM.alert_md(wl, comp, now, prior, drv, fc)
                    st.code(msg, language="text")
                    if st.button("▶ Send to the webhook"):
                        ok=_dispatch_webhook({"title":"Hold-period monitor","metric":"covenant","observed":sm},
                                             msg)
                        st.success("Sent." if ok else "Queued — set ALERT_WEBHOOK to deliver automatically.")
                st.divider()
                st.markdown("**Schedule**")
                st.code("cron:    0 8 * * *            # daily 08:00 UTC\n"
                        "command: PYTHONPATH=. python app/monitor.py\n"
                        "alert:   ALERT_WEBHOOK fires on breach only\n"
                        "scope:   every saved borrower (Portfolio), else the loaded dataset", language="yaml")

        with tab_cap:
            live,road=HM.capabilities()
            st.markdown("**Runs today**")
            st.dataframe(live,use_container_width=True,hide_index=True)
            st.markdown("**Not built**")
            st.dataframe(road,use_container_width=True,hide_index=True)
            st.caption("No dates are attached to the second table on purpose. It is a statement of what the "
                       "product does not do, not a delivery commitment.")

    elif page=="Audit":
        st.title("Audit")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>Indicative. Monitoring answers how the "
                    f"credit is doing; this gathers what a lender weighs before that. Every figure is "
                    f"the one already in the IC paper, re-ordered. The tests below are ours by default "
                    f"and are meant to be replaced by yours: we compute what you define, we do not "
                    f"propose the policy.</div>", unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first."); st.stop()
        a=ss["assump"]; t=_pinned_terms(); R=ss.get("results") or run_all(ss["df"])
        risk=_risk_pack(R, a, t) or {}
        try:
            pack=LAU.build(R, df=ss["df"], a=a, terms=t, journeys_mod=J,
                           mc=risk.get("mc"), bayes=risk.get("bayes"))
        except Exception as e:
            st.error(f"audit n/a: {e}"); st.stop()
        d=pack["decision"]
        colour={"ok":"#5E7C6E","watch":"#9C6B4F","stop":"#9C2B2B"}[d["colour"]]
        st.markdown(f"<div style='border-left:5px solid {colour};background:#F4F2ED;padding:14px 18px;"
                    f"margin:6px 0 4px 0'><div style='font-size:11px;color:{MUTE};letter-spacing:.08em'>"
                    f"AGAINST THE ILLUSTRATIVE TESTS BELOW</div>"
                    f"<div style='font-size:24px;color:{colour};font-weight:600'>{d['verdict']}</div>"
                    f"<div style='color:{INK};margin-top:4px'>{d['line']}</div></div>",
                    unsafe_allow_html=True)
        k=st.columns(4)
        # The verdict token is short so the tile cannot truncate; the full sentence is in the
        # banner above it. This is the verdict moment of the section.
        _kp=dict(pack["kpis"]); _kp["Verdict"]=d["verdict"].split(" ON ")[0].split(" THE ")[0]
        for col,(kk,vv) in zip(k, _kp.items()): col.metric(kk,vv)
        st.caption(d["note"])
        st.caption("The system has no incentive to approve.")
        st.divider()
        st.markdown("**The gates, and how each was decided**")
        st.dataframe(d["gates"],use_container_width=True,hide_index=True)
        st.divider()
        st.markdown("**Risk register**")
        def _sev(row):
            c={"HIGH":"#9C2B2B","MEDIUM":"#9C6B4F","OPEN":"#7A7A75"}.get(row["Severity"],"")
            return [f"color:{c}" if c else "" for _ in row]
        st.dataframe(d["risks"].style.apply(_sev,axis=1),use_container_width=True,hide_index=True)
        st.divider()
        bm=d["benchmark"]
        with st.expander("Reference points used for the tests above (illustrative)"):
            st.caption("Benchmark data is the lender's own world. These are placeholders so the gates "
                       "have something to test against; the intention is to consume your reference "
                       "data, not to compete with it.")
            st.dataframe(bm["table"],use_container_width=True,hide_index=True)
            st.caption(f"{bm['inside']} of {bm['total']} within reference. {bm['note']}")
            if bm.get("peer") is not None and len(bm["peer"]):
                st.dataframe(bm["peer"],use_container_width=True,hide_index=True)
        if risk.get("mc"):
            st.divider(); st.markdown("**Probability of breach**")
            st.caption("Computed at the position in the IC paper, the point of decision. Monitoring "
                       "answers the same question at a later reporting date, where the figure is "
                       "higher because the borrower has deteriorated since.")
            pc=st.columns(2)
            pc[0].caption("Assumed forward distribution")
            pc[0].dataframe(risk["mc"]["tables"]["Probability of breach"],use_container_width=True,hide_index=True)
            if risk.get("bayes"):
                pc[1].caption(f"Learned from {risk['bayes']['kpis']['Observations']} reported periods")
                pc[1].dataframe(risk["bayes"]["tables"]["Probability of breach"],use_container_width=True,hide_index=True)
        st.divider()
        st.markdown("**Open items arising from the tests**")
        st.dataframe(d["conditions"],use_container_width=True,hide_index=True)
        st.download_button("⬇ Audit summary (CSV)",
                           pd.concat([d["gates"].assign(Section="Gate"),
                                      d["risks"].assign(Section="Risk")],ignore_index=True).to_csv(index=False),
                           "organica_credit_audit.csv","text/csv")
        ss["results"]=R

    elif page=="Portfolio":
        PF.render_page(st, ss, S, pd, MUTE)

    elif page=="Export":
        st.title("Export")
        if ss["df"] is None: st.warning("Load data first."); st.stop()
        R=ss.get("results") or run_all(ss["df"]); stamp=datetime.date.today().isoformat()
        path=os.path.join(OUT,"Organica_pack.xlsx"); X.build_pack(path,R,assumptions=ss["assump"])
        comp=ss.get("company","Verexa Software")
        try:
            _secs=IPR.build(R, df=ss["df"], a=ss["assump"], terms=_pinned_terms(), company=comp,
                            stamp=stamp, journeys_mod=J, prov_mod=PV,
                            risk=_risk_pack(R, ss["assump"], _pinned_terms()))
            _cov=IPR.coverage(_secs)
            st.download_button("⬇ IC paper (PDF) — the committee template",
                               IPR.build_pdf(_secs,comp,stamp,_cov),
                               "Organica_IC_paper.pdf","application/pdf",type="primary")
            st.caption(_cov["summary"])
        except Exception as e:
            st.caption(f"IC paper n/a: {e}")
        st.write("")
        c1,c2,c3,c4=st.columns(4)
        with open(path,"rb") as f:
            c1.download_button("⬇ XLS pack", f, "Organica_pack.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        try:
            c2.download_button("⬇ Board pack (PDF)", BP.build_pdf(R, "Verexa Software", stamp), "Organica_board_pack.pdf", "application/pdf")
        except Exception as e:
            c2.caption(f"PDF n/a: {e}")
        try:
            c3.download_button("⬇ IC memo (.md)", IM.build_md(R, "Verexa Software", stamp), "Organica_IC_memo.md", "text/markdown")
        except Exception as e:
            c3.caption(f"memo n/a: {e}")
        try:
            c4.download_button("⬇ IC deck (PPTX)", ID.build_pptx(R, "Verexa Software", stamp), "Organica_IC_deck.pptx",
                               "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        except Exception as e:
            c4.caption(f"deck n/a: {e}")
        st.caption("IC paper (the committee template) · XLS · board-pack PDF · IC memo (Markdown) · "
                   "IC deck (PowerPoint) — all generated live from the loaded data.")
