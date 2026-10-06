"""Funciones de análisis usadas por el dashboard (sin dependencias de Streamlit)."""
from __future__ import annotations

import pandas as pd


def to_unit(prices: pd.Series, unit: str) -> pd.Series:
    """€/MWh → €/kWh si se pide."""
    return prices / 1000 if unit == "€/kWh" else prices


def classify_hours(prices: pd.Series) -> pd.Series:
    """Clasifica cada hora del día en barata / media / cara según terciles."""
    if prices.empty:
        return pd.Series(dtype="object")
    labels = ["Barata", "Media", "Cara"]
    ranks = prices.rank(method="first")
    return pd.qcut(ranks, q=3, labels=labels).astype(str)


def cheapest_window(day_df: pd.DataFrame, hours: int) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    """Ventana de `hours` horas consecutivas con el menor precio medio.

    `day_df` debe tener columnas ts_local (datetime) y price (float), ordenadas.
    Devuelve (inicio, fin, precio medio) o None si no hay datos suficientes.
    """
    if len(day_df) < hours:
        return None
    rolling = day_df["price"].rolling(hours).mean()
    end_idx = rolling.idxmin()
    pos = day_df.index.get_loc(end_idx)
    start_row = day_df.iloc[pos - hours + 1]
    end_row = day_df.iloc[pos]
    return start_row["ts_local"], end_row["ts_local"] + pd.Timedelta(hours=1), float(rolling.loc[end_idx])


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Media, mínimo y máximo diario por serie, con media móvil de 7 días."""
    out = (
        df.assign(day=df["ts_local"].dt.date)
        .groupby(["series", "day"], as_index=False)["price"]
        .agg(avg="mean", min="min", max="max")
    )
    out["avg_7d"] = out.groupby("series")["avg"].transform(lambda s: s.rolling(7, min_periods=1).mean())
    out["day"] = pd.to_datetime(out["day"])
    return out


def hour_weekday_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Precio medio por día de la semana (filas) y hora (columnas)."""
    days = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    tmp = df.assign(weekday=df["ts_local"].dt.weekday, hour=df["ts_local"].dt.hour)
    mat = tmp.pivot_table(index="weekday", columns="hour", values="price", aggfunc="mean")
    mat = mat.reindex(index=range(7), columns=range(24))
    mat.index = days
    return mat
