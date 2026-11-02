"""Organica Engine — single entrypoint.  python run.py configs/<engagement>.yaml
Ingest → reconcile → economics → scenario → validate → render.  Offline. Exit 1 if a tie fails.
"""
import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import pipeline as P, validate as V
ROOT=os.path.dirname(os.path.abspath(__file__))

def main(cfg_path):
    cfg=P.load_config(cfg_path)
    print(f"▸ Engagement: {cfg['engagement']}")
    tables=P.ingest(cfg, ROOT)
    metrics, factbase, ties = P.reconcile(cfg, tables)
    econ, stack = P.economics(cfg, tables, metrics)
    scen = P.scenario(cfg, econ)
    mc_df, detail, coherent = V.run(cfg, econ)
    ties_ok = (ties["Status"]=="✓").all() if len(ties) else True
    dashboard=pd.DataFrame([
        ("Engagement", cfg["engagement"], "—"),
        ("ARR", f"{cfg['currency']}{metrics['arr']/1e6:.2f}m", "RECONSTRUCTED"),
        ("Customers", f"{int(metrics['customers'])}", "OBSERVED"),
        ("Fully-loaded margin (point)", f"{econ['margin']:.0f}%", "MODELLED"),
        ("Margin — MC median", mc_df.loc[mc_df['Metric']=='Margin — MC median','Value'].iloc[0], "MODELLED"),
        ("Cross-reference ties", "all pass" if ties_ok else "FAIL", "—"),
        ("Bayesian coherence", "coherent" if coherent else "point optimistic — re-centre", "—"),
    ], columns=["KPI","Value","Evidence"])
    out=os.path.join(ROOT,"out",f"{cfg['engagement'].split('(')[0].strip().replace(' ','_')}_pack.xlsx")
    P.render(cfg, out, factbase, ties, stack, scen, mc_df, detail, dashboard)
    print(f"  fact base: {len(factbase)} metrics · ties {'PASS' if ties_ok else 'FAIL'} · margin {econ['margin']:.0f}% · coherent {coherent}")
    print(f"✓ pack → {out}")
    return 0 if ties_ok else 1

if __name__=="__main__":
    cfg = sys.argv[1] if len(sys.argv)>1 else os.path.join(ROOT,"configs","example_saas.yaml")
    sys.exit(main(cfg))
