"""Per-module results management in st.session_state, with detection of stale results."""
import streamlit as st


def firma(*partes):
    return "|".join(str(p) for p in partes)


def guardar(modulo, datos, firma_):
    st.session_state.setdefault("datos", {})[modulo] = {"datos": datos, "firma": firma_}


def obtener(modulo, firma_actual):
    """Returns (data, current). `vigente` is False if AOI/dates/parameters changed since the query."""
    d = st.session_state.get("datos", {}).get(modulo)
    if not d:
        return None, False
    return d["datos"], d["firma"] == firma_actual


def limpiar():
    for k in ("datos", "exportables"):
        st.session_state.pop(k, None)
