"""Organica UI. In the deploy build this module is obfuscated; the clear launcher app.py
imports it and calls render() on every Streamlit rerun (PyArmor forbids exec'ing an obfuscated
entry, but importing an obfuscated module + calling a function is fine).
"""
import os, sys, datetime
import pandas as pd, numpy as np, streamlit as st
import plotly.express as px, plotly.graph_objects as go
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyses as A, store as S, gdrive as G, xls_export as X, auth as AU, cases as C, ai as AI, journeys as J, boardpack as BP, icmemo as IM, docs as DOC, netsuite as NS, provenance as PV, icdeck as ID, portfolio as PF, connectors as CX, comps as CM

ACCENT="#2C5560"; INK="#1A1A1A"; MUTE="#7A7A75"; CLAY="#9C6B4F"; SAGE="#5E7C6E"; LINE="#E6E3DD"
TEAL=ACCENT  # back-compat for helpers
OUT=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"out"); os.makedirs(OUT, exist_ok=True)
st.set_page_config(page_title="Organica", layout="wide")
PLT=dict(template="plotly_white", font=dict(family="Helvetica, Arial, sans-serif", color=INK, size=13),
         margin=dict(l=10,r=10,t=44,b=10), title_font=dict(size=15, color=INK))
ss=st.session_state

# ---------------- helpers ----------------
def autoload(raw):
    m=AI.detect_columns(raw); ss["raw"]=raw; ss["mapping"]=m; ss["is_demo"]=False
    ss["df"]=A.normalize(raw, m["revenue"], m.get("volume"), m.get("tier"), m.get("revenue_is_monthly",True), m.get("customer"))
    S.save_table("customers", ss["df"]); return m

def show_mapping(raw):
    m=ss.get("mapping",{})
    st.success(f"Loaded {len(ss['df'])} rows · ARR €{ss['df'].revenue.sum()/1e6:.2f}m · recognised by {m.get('_by','?')}")
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

def validation_view(df):
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

# ---------------- per-run entrypoint ----------------
def render():
    ss.setdefault("raw", None); ss.setdefault("df", None); ss.setdefault("svc", None); ss.setdefault("files", [])
    ss.setdefault("assump", {**A.DEFAULTS}); ss.setdefault("user", None); ss.setdefault("mapping", {}); ss.setdefault("case", None); ss.setdefault("ts", None); ss.setdefault("chat", []); ss.setdefault("fin", None)
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
    NAV=["Business cases","Ask","Journeys","Connect data","Data","Dashboard","Deliverability","Analyses","Export"]
    if ss.get("role")=="admin": NAV=NAV+["Monitoring","Portfolio"]
    page=st.sidebar.radio("Navigation", NAV, label_visibility="collapsed")
    st.sidebar.divider(); AU.sidebar_signout(ss)
    with st.sidebar.expander("Assumptions"):
        a=ss["assump"]
        a["loaded_fte"]=st.number_input("Loaded €/FTE",50_000,250_000,a["loaded_fte"],5_000)
        a["unit_rate"]=st.number_input("Unit cost €/unit/yr",0.0,5.0,float(a["unit_rate"]),0.01)
        a["egress_pct"]=st.slider("Egress % of revenue",0.0,0.10,a["egress_pct"],0.005)
        a["peer_floor"]=st.number_input("Peer price floor €",0,500_000,a["peer_floor"],1_000)
        a["mc_n"]=st.select_slider("Probabilistic draws",[20_000,50_000,100_000,200_000],a["mc_n"])

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
                    f"Below: Google Drive (service-account key); the ERP/CRM connectors are further down.</div>",unsafe_allow_html=True); st.write("")
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

    elif page=="Data":
        st.title("Data"); tab1,tab2=st.tabs(["Upload a file","Verexa — sample data room"])
        with tab1:
            up=st.file_uploader("Data-room file — CSV · Excel · PDF", type=["csv","xlsx","xls","pdf"])
            if up is not None:
                tables=DOC.extract_tables(up.getvalue(), up.name)
                if not tables:
                    st.warning("No analysable tables found in that file.")
                else:
                    best=DOC.best_table(tables); bi=tables.index(best) if best in tables else 0
                    labels=[f"{l}  ·  {len(d)}×{d.shape[1]}" for l,d in tables]
                    pick=st.selectbox(f"AI found {len(tables)} table(s) — best pre-selected", labels, index=bi)
                    raw=tables[labels.index(pick)][1]
                    st.dataframe(raw.head(8), use_container_width=True)
                    if st.button("Use this table ▶", type="primary"): autoload(raw)
                    if ss.get("raw") is not None: show_mapping(ss["raw"])
        with tab2:
            st.caption("**Verexa Software** — a €13.6m-ARR vertical-SaaS company, PE-owned, preparing a refinancing. Real-world book (anonymised & de-referenced): customers, a 15-month MRR time-series, and 3 years of quarterly P&L.")
            if st.button("Load sample book",type="primary"):
                root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                autoload(pd.read_csv(os.path.join(root,"examples","data","customers.csv")))
                ss["is_demo"]=True
                try: ss["ts"]=pd.read_csv(os.path.join(root,"examples","data","monthly.csv"))
                except Exception: pass
                try: ss["fin"]=pd.read_csv(os.path.join(root,"examples","data","financials.csv"))
                except Exception: pass
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

    elif page=="Analyses":
        st.title("Analyses")
        if ss["df"] is None: st.warning("Load data first."); st.stop()
        opts=list(A.MENU)+(["Retention"] if ss.get("ts") is not None else [])+(["Financials"] if ss.get("fin") is not None else [])+["Accounts"]
        pick=st.multiselect("Run which analyses?", opts, opts)
        R=run_all(ss["df"])
        for name in pick:
            if name in R:
                st.subheader(name); render_step(name,R,f"an{name}"); st.divider()

    elif page=="Ask":
        st.title("Ask Organica")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>Open-ended and conversational — ask anything in plain English. "
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
        st.title("Monitoring")
        st.markdown(f"<div style='color:{MUTE};margin-top:-8px'>A scheduled agent re-runs every journey on a cadence "
                    f"and alerts on critical breaches. This is what it sees right now.</div>", unsafe_allow_html=True)
        if ss["df"] is None: st.info("Load data first."); st.stop()
        R=run_all(ss["df"]); a=ss["assump"]; crit=[]; watch=[]
        for k in J.JOURNEYS:
            res=J.run_journey(k, ss["df"], a, R)
            for f in res["issues"]:
                (crit if f["severity"]=="critical" else watch).append((res["journey"]["title"], f))
        cc=st.columns(3)
        cc[0].metric("Journeys watched", len(J.JOURNEYS)); cc[1].metric("Critical breaches", len(crit)); cc[2].metric("Watch items", len(watch))
        st.divider()
        for tag,items,col in [("Critical breaches",crit,"#9C2B2B"),("Watch items",watch,"#9C6B4F")]:
            if items:
                st.markdown(f"**{tag}**")
                for jt,f in items:
                    st.markdown(f"<span style='color:{col}'>●</span> **{f['title']}** "
                                f"<span style='color:{MUTE}'>· {jt} · {f['observed']}</span> → {f['recommendation']}", unsafe_allow_html=True)
                st.write("")
        st.divider(); st.markdown("**Schedule & alerting**")
        st.code("cron:    0 8 * * *            # daily 08:00 UTC\n"
                "command: PYTHONPATH=. python app/monitor.py\n"
                "alert:   ALERT_WEBHOOK (Slack/webhook) fires on any critical breach\n"
                "output:  the same Markdown agent briefs the Journeys page emits", language="yaml")
        st.caption("Runs as a separate Render cron service from the same obfuscated build.")

    elif page=="Portfolio":
        PF.render_page(st, ss, S, pd, MUTE)

    elif page=="Export":
        st.title("Export")
        if ss["df"] is None: st.warning("Load data first."); st.stop()
        R=ss.get("results") or run_all(ss["df"]); stamp=datetime.date.today().isoformat()
        path=os.path.join(OUT,"Organica_pack.xlsx"); X.build_pack(path,R,assumptions=ss["assump"])
        c1,c2,c3,c4=st.columns(4)
        with open(path,"rb") as f:
            c1.download_button("⬇ XLS pack", f, "Organica_pack.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
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
        st.caption("XLS · board-pack PDF · IC memo (Markdown) · IC deck (PowerPoint) — all generated live from the loaded data.")
