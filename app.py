"""Dashboard del precio de la luz en España (PVPC y mercado spot).

Ejecutar con:  streamlit run app.py
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import analysis, db, etl

TZ = ZoneInfo("Europe/Madrid")
SERIES_LABELS = {"pvpc": "PVPC (tarifa regulada)", "spot": "Mercado spot (OMIE)"}
COLORS = {"Barata": "#2e9e6b", "Media": "#e8a33d", "Cara": "#d64545"}
SERIES_COLORS = {"pvpc": "#2f6fdb", "spot": "#9a6dd7"}

st.set_page_config(page_title="Precio de la luz en España", page_icon="⚡", layout="wide")


# ----------------------------------------------------------------------------- datos
@st.cache_data(ttl=60 * 30, show_spinner="Cargando datos…")
def get_data() -> pd.DataFrame:
    df = db.load_prices()
    if df.empty:
        # Primera ejecución sin base de datos: descargamos los últimos 90 días al vuelo.
        today = datetime.now(TZ).date()
        etl.run(today - timedelta(days=90), today + timedelta(days=1))
        df = db.load_prices()
    return df


df_all = get_data()
if df_all.empty:
    st.error("No hay datos. Ejecuta `python -m src.etl --backfill 365` para descargarlos.")
    st.stop()

now = datetime.now(TZ)
today = now.date()

# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("⚙️ Opciones")
    series = st.radio(
        "Serie de precios",
        options=["pvpc", "spot"],
        format_func=SERIES_LABELS.get,
        help="PVPC: precio regulado que pagan los consumidores con tarifa regulada (incluye peajes y cargos). "
        "Spot: precio mayorista del mercado diario.",
    )
    unit = st.radio("Unidad", ["€/kWh", "€/MWh"], horizontal=True)
    min_day, max_day = df_all["ts_local"].dt.date.min(), df_all["ts_local"].dt.date.max()
    default_start = max(min_day, today - timedelta(days=90))
    date_range = st.date_input(
        "Periodo para el histórico",
        value=(default_start, min(max_day, today)),
        min_value=min_day,
        max_value=max_day,
    )
    st.caption(f"Datos de **{min_day:%d/%m/%Y}** a **{max_day:%d/%m/%Y}**")
    st.caption("Fuente: [REE · apidatos.ree.es](https://www.ree.es/es/apidatos)")

fmt = "{:.4f}" if unit == "€/kWh" else "{:.2f}"
df = df_all[df_all["series"] == series].copy()
df["price"] = analysis.to_unit(df["price_eur_mwh"], unit)


def day_frame(d) -> pd.DataFrame:
    return df[df["ts_local"].dt.date == d].sort_values("ts_local").reset_index(drop=True)


df_today = day_frame(today)
df_yesterday = day_frame(today - timedelta(days=1))
df_tomorrow = day_frame(today + timedelta(days=1))

# ---------------------------------------------------------------------------- header
st.title("⚡ Precio de la luz en España")
st.caption(f"{SERIES_LABELS[series]} · actualizado {now:%d/%m/%Y %H:%M} (hora peninsular)")

if df_today.empty:
    st.warning("Todavía no hay precios para hoy. Mostrando el último día disponible.")
    df_today = day_frame(df["ts_local"].dt.date.max())

current = df_today[df_today["ts_local"].dt.hour == now.hour]
avg_today = df_today["price"].mean()
avg_yest = df_yesterday["price"].mean() if not df_yesterday.empty else None
cheap = df_today.loc[df_today["price"].idxmin()]
pricey = df_today.loc[df_today["price"].idxmax()]

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Precio ahora",
    f"{fmt.format(current['price'].iloc[0])} {unit}" if not current.empty else "—",
    help="Precio de la hora en curso",
)
c2.metric(
    "Media de hoy",
    f"{fmt.format(avg_today)} {unit}",
    delta=f"{(avg_today / avg_yest - 1) * 100:+.1f}% vs ayer" if avg_yest else None,
    delta_color="inverse",
)
c3.metric(f"Hora más barata · {fmt.format(cheap['price'])} {unit}", f"{cheap['ts_local']:%H}:00 h")
c4.metric(f"Hora más cara · {fmt.format(pricey['price'])} {unit}", f"{pricey['ts_local']:%H}:00 h")

tab_day, tab_hist, tab_patterns, tab_data = st.tabs(
    ["📅 Hoy y mañana", "📈 Histórico", "🔥 Patrones", "🗂️ Datos"]
)


# ------------------------------------------------------------------- tab: hoy/mañana
def hourly_bar(day_df: pd.DataFrame, title: str) -> go.Figure:
    plot = day_df.assign(
        hora=day_df["ts_local"].dt.strftime("%H:00"),
        tramo=analysis.classify_hours(day_df["price"]),
    )
    fig = px.bar(
        plot, x="hora", y="price", color="tramo", color_discrete_map=COLORS,
        category_orders={"tramo": ["Barata", "Media", "Cara"]},
        labels={"hora": "Hora", "price": unit, "tramo": ""}, title=title,
    )
    fig.update_xaxes(categoryorder="array", categoryarray=list(plot["hora"]))
    fig.add_hline(y=plot["price"].mean(), line_dash="dot", line_color="gray",
                  annotation_text="media", annotation_position="top left")
    fig.update_layout(height=380, margin=dict(t=50, b=10), legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    return fig


with tab_day:
    left, right = st.columns([3, 1])
    with left:
        st.plotly_chart(hourly_bar(df_today, f"Hoy, {df_today['ts_local'].iloc[0]:%d/%m/%Y}"), use_container_width=True)
        if not df_tomorrow.empty:
            st.plotly_chart(hourly_bar(df_tomorrow, f"Mañana, {df_tomorrow['ts_local'].iloc[0]:%d/%m/%Y}"), use_container_width=True)
        else:
            st.info("Los precios de mañana se publican cada día alrededor de las 20:15.")
    with right:
        st.subheader("🔌 Mejor momento")
        hours = st.slider("Duración del consumo (horas)", 1, 6, 2,
                          help="Por ejemplo, 2 h para una lavadora o 3 h para cargar un coche")
        for label, d in [("Hoy", df_today), ("Mañana", df_tomorrow)]:
            win = analysis.cheapest_window(d, hours)
            if win:
                start, end, price = win
                st.success(f"**{label}:** de {start:%H:%M} a {end:%H:%M}\n\nMedia: {fmt.format(price)} {unit}")
        if not df_today.empty:
            expensive = df_today.nlargest(3, "price")["ts_local"].dt.strftime("%H:00")
            st.error("**Evita hoy:** " + ", ".join(sorted(expensive)))

# --------------------------------------------------------------------- tab: histórico
with tab_hist:
    if isinstance(date_range, tuple) and len(date_range) == 2:
        d0, d1 = date_range
    else:
        d0, d1 = default_start, max_day
    both = df_all[(df_all["ts_local"].dt.date >= d0) & (df_all["ts_local"].dt.date <= d1)].copy()
    both["price"] = analysis.to_unit(both["price_eur_mwh"], unit)
    daily = analysis.daily_summary(both)

    sel = daily[daily["series"] == series]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sel["day"], y=sel["max"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=sel["day"], y=sel["min"], fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(47,111,219,0.15)", name="Rango mín–máx"))
    fig.add_trace(go.Scatter(x=sel["day"], y=sel["avg"], name="Media diaria", line=dict(color=SERIES_COLORS[series])))
    fig.add_trace(go.Scatter(x=sel["day"], y=sel["avg_7d"], name="Media móvil 7 días",
                             line=dict(color="black", dash="dash")))
    fig.update_layout(title=f"Precio diario · {SERIES_LABELS[series]}", yaxis_title=unit, height=420,
                      hovermode="x unified", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    comp = px.line(
        daily.assign(serie=daily["series"].map(SERIES_LABELS)), x="day", y="avg", color="serie",
        color_discrete_map={SERIES_LABELS[k]: v for k, v in SERIES_COLORS.items()},
        labels={"day": "", "avg": unit, "serie": ""}, title="PVPC frente a mercado spot (media diaria)",
    )
    comp.update_layout(height=360, legend=dict(orientation="h", y=1.1))
    st.plotly_chart(comp, use_container_width=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Media del periodo", f"{fmt.format(sel['avg'].mean())} {unit}")
    m2.metric("Día más barato", f"{sel.loc[sel['avg'].idxmin(), 'day']:%d/%m/%Y}" if not sel.empty else "—")
    m3.metric("Día más caro", f"{sel.loc[sel['avg'].idxmax(), 'day']:%d/%m/%Y}" if not sel.empty else "—")

# ---------------------------------------------------------------------- tab: patrones
with tab_patterns:
    period = df[(df["ts_local"].dt.date >= d0) & (df["ts_local"].dt.date <= d1)]
    mat = analysis.hour_weekday_matrix(period)
    heat = px.imshow(
        mat, aspect="auto", color_continuous_scale="RdYlGn_r",
        labels=dict(x="Hora", y="", color=unit), title="Precio medio por día de la semana y hora",
    )
    heat.update_xaxes(tickmode="linear", dtick=2)
    heat.update_layout(height=380)
    st.plotly_chart(heat, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        prof = period.assign(hora=period["ts_local"].dt.hour).groupby("hora", as_index=False)["price"].mean()
        fig_prof = px.line(prof, x="hora", y="price", markers=True, title="Perfil horario medio",
                           labels={"hora": "Hora", "price": unit})
        fig_prof.update_traces(line_color=SERIES_COLORS[series])
        st.plotly_chart(fig_prof, use_container_width=True)
    with col_b:
        monthly = df.assign(mes=df["ts_local"].dt.strftime("%Y-%m"))
        fig_box = px.box(monthly, x="mes", y="price", title="Distribución mensual (todo el histórico)",
                         labels={"mes": "", "price": unit}, points=False)
        fig_box.update_traces(marker_color=SERIES_COLORS[series])
        st.plotly_chart(fig_box, use_container_width=True)

# -------------------------------------------------------------------------- tab: datos
with tab_data:
    table = (
        df_all[(df_all["ts_local"].dt.date >= d0) & (df_all["ts_local"].dt.date <= d1)]
        .pivot_table(index="ts_local", columns="series", values="price_eur_mwh")
        .rename(columns={"pvpc": "PVPC (€/MWh)", "spot": "Spot (€/MWh)"})
        .sort_index(ascending=False)
    )
    table.index = table.index.strftime("%Y-%m-%d %H:%M")
    table.index.name = "Hora"
    st.dataframe(table, use_container_width=True, height=420)
    st.download_button("⬇️ Descargar CSV", table.to_csv().encode("utf-8"),
                       file_name=f"precio_luz_{d0}_{d1}.csv", mime="text/csv")

st.divider()
st.caption("Proyecto de portfolio · Datos públicos de Red Eléctrica de España · Código en GitHub")
