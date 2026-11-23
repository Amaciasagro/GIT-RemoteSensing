"""Export: CSV buttons per table and global ZIP (CSV + metadata)."""
import io, json, zipfile
import pandas as pd
import streamlit as st


def registrar(nombre, df):
    """Saves a table for the global ZIP."""
    if isinstance(df, pd.DataFrame) and not df.empty:
        st.session_state.setdefault("exportables", {})[nombre] = df


def boton_csv(df, nombre, key):
    st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{nombre}.csv", mime="text/csv", key=key)


def zip_bytes(meta):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, df in st.session_state.get("exportables", {}).items():
            z.writestr(f"{nombre}.csv", df.to_csv(index=False))
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    return buf.getvalue()
