"""Organica — Streamlit entry (clear launcher; stays unobfuscated because Streamlit execs it).
All UI + logic lives in the obfuscated _ui module; render() runs on every rerun.
Run:  streamlit run app/app.py
"""
import os, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_root, os.path.join(_root, "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import _ui
_ui.render()
