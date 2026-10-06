-- Consultas de análisis sobre data/prices.db
-- Ejecutar con:  sqlite3 data/prices.db < sql/analysis.sql
.headers on
.mode column

-- 1. Precio medio PVPC por hora del día (perfil horario) en los últimos 90 días
SELECT
    CAST(substr(ts_local, 12, 2) AS INTEGER)  AS hour,
    ROUND(AVG(price_eur_mwh), 2)              AS avg_pvpc_eur_mwh
FROM prices
WHERE series = 'pvpc'
  AND ts_local >= date('now', '-90 days')
GROUP BY hour
ORDER BY hour;

-- 2. Las 10 horas más caras de la historia registrada
SELECT ts_local, series, price_eur_mwh
FROM prices
ORDER BY price_eur_mwh DESC
LIMIT 10;

-- 3. Evolución mensual con variación respecto al mes anterior (funciones de ventana)
WITH monthly AS (
    SELECT substr(ts_local, 1, 7) AS month, AVG(price_eur_mwh) AS avg_price
    FROM prices
    WHERE series = 'pvpc'
    GROUP BY month
)
SELECT
    month,
    ROUND(avg_price, 2)                                                      AS avg_pvpc,
    ROUND(avg_price - LAG(avg_price) OVER (ORDER BY month), 2)               AS diff_vs_prev,
    ROUND(100.0 * (avg_price / LAG(avg_price) OVER (ORDER BY month) - 1), 1) AS pct_vs_prev
FROM monthly
ORDER BY month;

-- 4. Diferencia media entre el PVPC (lo que paga el consumidor) y el mercado spot
SELECT
    substr(p.ts_local, 1, 7)                          AS month,
    ROUND(AVG(p.price_eur_mwh - s.price_eur_mwh), 2)  AS avg_spread_eur_mwh
FROM prices p
JOIN prices s ON s.ts_utc = p.ts_utc AND s.series = 'spot'
WHERE p.series = 'pvpc'
GROUP BY month
ORDER BY month;

-- 5. Fines de semana frente a días laborables
SELECT
    CASE WHEN strftime('%w', ts_local) IN ('0', '6') THEN 'fin de semana' ELSE 'laborable' END AS day_type,
    ROUND(AVG(price_eur_mwh), 2) AS avg_pvpc
FROM prices
WHERE series = 'pvpc'
GROUP BY day_type;

-- 6. Hora más barata de cada día del último mes (ROW_NUMBER)
WITH ranked AS (
    SELECT
        substr(ts_local, 1, 10) AS day,
        substr(ts_local, 12, 5) AS hour,
        price_eur_mwh,
        ROW_NUMBER() OVER (PARTITION BY substr(ts_local, 1, 10) ORDER BY price_eur_mwh) AS rn
    FROM prices
    WHERE series = 'pvpc' AND ts_local >= date('now', '-30 days')
)
SELECT day, hour AS cheapest_hour, price_eur_mwh
FROM ranked
WHERE rn = 1
ORDER BY day;
