"""Acceso a la base de datos SQLite."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.db"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def upsert_prices(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Inserta o actualiza filas (ts_utc, ts_local, series, price_eur_mwh)."""
    if df.empty:
        return 0
    rows = df[["ts_utc", "ts_local", "series", "price_eur_mwh"]].itertuples(index=False, name=None)
    with conn:
        conn.executemany(
            """
            INSERT INTO prices (ts_utc, ts_local, series, price_eur_mwh)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (ts_utc, series) DO UPDATE SET
                ts_local = excluded.ts_local,
                price_eur_mwh = excluded.price_eur_mwh
            """,
            list(rows),
        )
    return len(df)


def log_run(conn: sqlite3.Connection, start: str, end: str, rows: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO etl_runs VALUES (datetime('now'), ?, ?, ?)", (start, end, rows)
        )


def last_timestamp(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(ts_local) FROM prices WHERE series = 'pvpc'").fetchone()
    return row[0] if row else None


def load_prices(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    """Devuelve todas las filas con columnas datetime ya parseadas."""
    conn = get_connection(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT ts_utc, ts_local, series, price_eur_mwh FROM prices ORDER BY ts_utc", conn
        )
    finally:
        conn.close()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ts_local"] = df["ts_utc"].dt.tz_convert("Europe/Madrid")
    return df
