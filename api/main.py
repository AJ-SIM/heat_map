# /api/main.py — Azure-ready: ingest + public CSV/JSON endpoints
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import os, csv, json
from math import floor
from typing import List

app = FastAPI()

# Where CSV/JSON files are stored (override in Azure App Settings if you want)
DATA_DIR = os.environ.get("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)

def fpath(device: str, kind: str) -> str:
    # kind: "clean" | "raw" | "meta"
    if kind == "meta":
        return os.path.join(DATA_DIR, f"{device}_meta.json")
    suffix = "" if kind == "clean" else "_raw"
    return os.path.join(DATA_DIR, f"{device}{suffix}.csv")

def rotate_if_mismatch(path: str, expected_cols: int):
    if not os.path.exists(path): return
    try:
        with open(path, "r", encoding="utf-8") as f:
            header = f.readline().strip()
        actual = 0 if not header else header.count(",") + 1
        if actual != expected_cols:
            os.replace(path, path.replace(".csv", "_legacy.csv"))
    except Exception:
        pass

@app.get("/health")
def health():
    return {"ok": True, "app": "heat_map_api"}

@app.post("/ingest")
async def ingest(req: Request):
    """
    ESP32 payload (ts in ms):
    {
      "device": "heatMap-esp32-01",
      "ts": <millis since boot>,
      "names": ["Sensor1",...],
      "temps": [clean floats],
      "raw":   [raw floats]      # may include 85 / -127
    }
    """
    data = await req.json()
    device = data.get("device", "unknown")
    ts_ms  = data.get("ts")
    names  = data.get("names")
    temps: List = data.get("temps", [])
    raw:   List = data.get("raw", [])

    if ts_ms is None or not isinstance(temps, list) or len(temps) == 0:
        return JSONResponse({"ok": False, "error": "bad payload"}, status_code=400)

    ts_s = int(floor(float(ts_ms)/1000.0 + 0.5))  # nice seconds too

    clean_csv = fpath(device, "clean")
    raw_csv   = fpath(device, "raw")
    meta_json = fpath(device, "meta")

    n = len(temps)
    # ts_s + ts_ms + N sensors
    rotate_if_mismatch(clean_csv, 2 + n)
    rotate_if_mismatch(raw_csv,   2 + n)

    # headers
    if not os.path.exists(clean_csv):
        header = ["ts_s","ts_ms"] + ([f"{nm}_C" for nm in names] if names and len(names)==n
                                     else [f"t{i}_C" for i in range(n)])
        with open(clean_csv, "w", newline="") as f:
            csv.writer(f).writerow(header)

    if not os.path.exists(raw_csv):
        header_raw = ["ts_s","ts_ms"] + ([f"{nm}_raw" for nm in names] if names and len(names)==n
                                         else [f"t{i}_raw" for i in range(n)])
        with open(raw_csv, "w", newline="") as f:
            csv.writer(f).writerow(header_raw)

    if names and not os.path.exists(meta_json):
        try:
            with open(meta_json, "w", encoding="utf-8") as f:
                json.dump({"names": names}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # append rows
    with open(clean_csv, "a", newline="") as f:
        row = [ts_s, int(ts_ms)] + [("" if v is None else float(v)) for v in temps]
        csv.writer(f).writerow(row)

    if isinstance(raw, list) and len(raw) == n:
        with open(raw_csv, "a", newline="") as f:
            row_raw = [ts_s, int(ts_ms)] + [("" if v is None else float(v)) for v in raw]
            csv.writer(f).writerow(row_raw)

    print(f"[heat_map] {device}: saved n={n} at ts_ms={ts_ms}")
    return {"ok": True, "n": n}

# ---------- Public endpoints the dashboard will read ----------
@app.get("/data/{device}/clean.csv")
def get_clean_csv(device: str):
    path = fpath(device, "clean")
    if not os.path.exists(path): return PlainTextResponse("", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return PlainTextResponse(f.read(), media_type="text/csv")

@app.get("/data/{device}/raw.csv")
def get_raw_csv(device: str):
    path = fpath(device, "raw")
    if not os.path.exists(path): return PlainTextResponse("", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return PlainTextResponse(f.read(), media_type="text/csv")

@app.get("/data/{device}/names.json")
def get_names(device: str):
    path = fpath(device, "meta")
    if not os.path.exists(path): return JSONResponse({"names": None})
    with open(path, "r", encoding="utf-8") as f:
        return JSONResponse(json.load(f))
