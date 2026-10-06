"""ETL: descarga precios de la API de Red Eléctrica (REE) y los guarda en SQLite.

Uso:
    python -m src.etl                 # actualización incremental (hasta mañana)
    python -m src.etl --backfill 365  # descarga el último año completo
    python -m src.etl --start 2025-01-01 --end 2025-03-31
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src import db

API_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
TZ = ZoneInfo("Europe/Madrid")
SERIES_IDS = {"1001": "pvpc", "600": "spot"}  # ids de indicador en la API de REE
CHUNK_DAYS = 7  # la API limita el rango por petición; descargamos por semanas

log = logging.getLogger("etl")


# --------------------------------------------------------------------------- extract
def fetch_range(start: date, end: date, session: requests.Session | None = None) -> dict:
    """Descarga el JSON bruto de REE entre dos fechas (ambas incluidas)."""
    session = session or requests.Session()
    params = {
        "start_date": f"{start.isoformat()}T00:00",
        "end_date": f"{end.isoformat()}T23:59",
        "time_trunc": "hour",
    }
    for attempt in range(4):
        resp = session.get(API_URL, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        log.warning("REE respondió %s (intento %s): %s", resp.status_code, attempt + 1, resp.text[:200])
        time.sleep(2 ** attempt)
    resp.raise_for_status()
    return {}


# ------------------------------------------------------------------------- transform
def transform(payload: dict) -> pd.DataFrame:
    """Convierte la respuesta de REE en filas horarias (ts_utc, ts_local, series, price_eur_mwh).

    Desde octubre de 2025 el mercado spot se publica cada 15 minutos; se agrega a
    precio medio horario para poder compararlo con el PVPC, que es horario.
    """
    frames = []
    for item in payload.get("included", []):
        series = SERIES_IDS.get(str(item.get("id")))
        values = item.get("attributes", {}).get("values") or []
        if not series or not values:
            continue
        df = pd.DataFrame(values)[["datetime", "value"]]
        df["series"] = series
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["ts_utc", "ts_local", "series", "price_eur_mwh"])

    df = pd.concat(frames, ignore_index=True)
    ts = pd.to_datetime(df["datetime"], utc=True)
    df["hour_utc"] = ts.dt.floor("h")
    hourly = (
        df.groupby(["hour_utc", "series"], as_index=False)["value"].mean()
        .rename(columns={"value": "price_eur_mwh"})
    )
    hourly["price_eur_mwh"] = hourly["price_eur_mwh"].round(2)
    hourly["ts_utc"] = hourly["hour_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    hourly["ts_local"] = hourly["hour_utc"].dt.tz_convert(TZ).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return hourly[["ts_utc", "ts_local", "series", "price_eur_mwh"]].sort_values(["ts_utc", "series"])


# ------------------------------------------------------------------------------ load
def run(start: date, end: date, db_path=db.DB_PATH) -> int:
    conn = db.get_connection(db_path)
    session = requests.Session()
    total = 0
    try:
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
            log.info("Descargando %s → %s", chunk_start, chunk_end)
            df = transform(fetch_range(chunk_start, chunk_end, session))
            total += db.upsert_prices(conn, df)
            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(0.5)  # ser amables con la API pública
        db.log_run(conn, start.isoformat(), end.isoformat(), total)
    finally:
        conn.close()
    log.info("Filas insertadas/actualizadas: %s", total)
    return total


def incremental_range(db_path=db.DB_PATH, default_days: int = 365) -> tuple[date, date]:
    """Desde el último día guardado (se vuelve a pedir por si había huecos) hasta mañana."""
    today = datetime.now(TZ).date()
    conn = db.get_connection(db_path)
    try:
        last = db.last_timestamp(conn)
    finally:
        conn.close()
    start = date.fromisoformat(last[:10]) - timedelta(days=1) if last else today - timedelta(days=default_days)
    return start, today + timedelta(days=1)  # el PVPC de mañana se publica sobre las 20:15


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backfill", type=int, help="descargar los últimos N días")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args()

    today = datetime.now(TZ).date()
    if args.start:
        start, end = args.start, args.end or today + timedelta(days=1)
    elif args.backfill:
        start, end = today - timedelta(days=args.backfill), today + timedelta(days=1)
    else:
        start, end = incremental_range()
    run(start, end)


if __name__ == "__main__":
    main()
