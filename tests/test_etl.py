import json
from pathlib import Path

import pandas as pd

from src import analysis, db, etl

FIXTURE = Path(__file__).parent / "fixtures" / "ree_sample.json"


def load_payload():
    return json.loads(FIXTURE.read_text())


def test_transform_hourly_and_series():
    df = etl.transform(load_payload())
    assert set(df["series"]) == {"pvpc", "spot"}
    assert len(df) == 4  # 2 horas x 2 series
    # el spot de 15 minutos se agrega a media horaria
    spot0 = df[(df["series"] == "spot") & (df["ts_local"] == "2026-10-04T00:00:00")]["price_eur_mwh"].item()
    assert spot0 == round((208.08 + 206.63 + 205.4 + 204.0) / 4, 2)
    # 00:00 en Madrid (UTC+2) son las 22:00 UTC del día anterior
    assert "2026-10-03T22:00:00Z" in set(df["ts_utc"])


def test_transform_empty_payload():
    assert etl.transform({}).empty


def test_upsert_is_idempotent(tmp_path):
    conn = db.get_connection(tmp_path / "test.db")
    df = etl.transform(load_payload())
    db.upsert_prices(conn, df)
    db.upsert_prices(conn, df)
    assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 4


def test_cheapest_window():
    day = pd.DataFrame({
        "ts_local": pd.date_range("2026-10-04", periods=6, freq="h", tz="Europe/Madrid"),
        "price": [5, 4, 1, 2, 6, 7],
    })
    start, end, avg = analysis.cheapest_window(day, 2)
    assert start.hour == 2 and end.hour == 4 and avg == 1.5
    assert analysis.cheapest_window(day, 10) is None


def test_classify_hours():
    labels = analysis.classify_hours(pd.Series([1, 2, 3, 4, 5, 6]))
    assert list(labels) == ["Barata", "Barata", "Media", "Media", "Cara", "Cara"]
