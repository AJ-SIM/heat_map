# /dashboard/app.py — reads CSV/JSON from the API; password-protected
import os, json, re
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="heat_map – Live", layout="wide")
st.title("heat_map – Live Temperatures")

# ---- configure via Azure App Settings ----
API_BASE   = os.environ.get("API_BASE", "http://localhost:8000")
DEVICE_ID  = os.environ.get("DEVICE_ID", "heatMap-esp32-01")
DASH_PASS  = os.environ.get("DASH_PASSWORD")  # optional simple gate

# ---- password gate ----
if DASH_PASS:
    pw = st.text_input("Password", type="password")
    if pw != DASH_PASS:
        st.stop()

# ---- controls ----
c1,c2,c3 = st.columns([1,1,1])
with c1: mins = st.slider("Last N minutes", 1, 240, 15)
with c2: auto = st.checkbox("Auto-refresh every 5 s", True)
with c3: trim_reset = st.checkbox("Start fresh on device reset", True)

# ---- load from API ----
clean_url = f"{API_BASE}/data/{DEVICE_ID}/clean.csv"
names_url = f"{API_BASE}/data/{DEVICE_ID}/names.json"

try:
    df = pd.read_csv(clean_url, on_bad_lines="skip")
except Exception as e:
    st.error(f"Could not load data from API: {e}")
    if auto: st_autorefresh(interval=5000, key="wait")
    st.stop()

# time axis
if "ts_s" in df.columns: df["abs_s"] = df["ts_s"].astype(float)
elif "ts_ms" in df.columns: df["abs_s"] = df["ts_ms"].astype(float)/1000.0
else:
    st.warning("No time column yet."); st.stop()

# reset handling
if trim_reset and len(df) > 1:
    dec = df["abs_s"].diff().fillna(0) < 0
    if dec.any():
        last = df.index[dec].max()
        df = df.loc[last+1:].copy()

# last N minutes
now_s = float(df["abs_s"].iloc[-1])
cut = now_s - mins*60.0
df = df[df["abs_s"] >= cut].copy()
df["time_s"] = df["abs_s"] - df["abs_s"].min()

# sensor columns
val_cols = [c for c in df.columns if c.endswith("_C")]
if not val_cols:
    st.warning("No sensor columns found."); st.stop()

# rename t0_C→SensorX_C using names.json if available
name_overrides = None
try:
    meta = pd.read_json(names_url)
    if isinstance(meta, pd.DataFrame) and "names" in meta:
        name_overrides = list(meta["names"])
except Exception:
    pass

tpat = re.compile(r"^t(\d+)_C$")
rename_map = {}
if name_overrides and len(name_overrides) == len(val_cols):
    for i, col in enumerate(val_cols):
        if tpat.match(col): rename_map[col] = f"{name_overrides[i]}_C"
elif all(tpat.match(c) for c in val_cols):
    for i, col in enumerate(val_cols):
        rename_map[col] = f"Sensor{i+1}_C"

if rename_map:
    df = df.rename(columns=rename_map)
    val_cols = [rename_map.get(c, c) for c in val_cols]

# rounding: 0.1–0.4 down, 0.5–0.9 up (half-up)
def round_half_up(x):
    a = np.array(x, dtype=float)
    return np.where(np.isnan(a), np.nan, np.floor(a + 0.5))

df_round = df.copy()
for c in val_cols:
    df_round[c] = round_half_up(df_round[c])

# plot
long = df_round.melt(id_vars="time_s", value_vars=val_cols,
                     var_name="sensor", value_name="temp_C")
fig = px.line(long, x="time_s", y="temp_C", color="sensor",
              labels={"time_s":"Time (s)","temp_C":"Temp (°C)","sensor":"Sensor"})
fig.update_traces(line=dict(width=3))
st.plotly_chart(fig, use_container_width=True)

# table
with st.expander("Latest 20 rows"):
    cols = ["time_s"] + val_cols
    t = df_round[cols].copy()
    t["time_s"] = t["time_s"].round(2)
    st.dataframe(t.tail(20), use_container_width=True)

if auto:
    st_autorefresh(interval=5000, key="live")
