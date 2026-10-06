-- Esquema de la base de datos de precios de la electricidad
-- Una fila por hora y serie (PVPC o mercado spot).

CREATE TABLE IF NOT EXISTS prices (
    ts_utc        TEXT    NOT NULL,              -- inicio de la hora en UTC (ISO 8601)
    ts_local      TEXT    NOT NULL,              -- misma hora en Europe/Madrid (ISO 8601, sin offset)
    series        TEXT    NOT NULL CHECK (series IN ('pvpc', 'spot')),
    price_eur_mwh REAL    NOT NULL,
    PRIMARY KEY (ts_utc, series)
);

CREATE INDEX IF NOT EXISTS idx_prices_local  ON prices (ts_local);
CREATE INDEX IF NOT EXISTS idx_prices_series ON prices (series, ts_local);

-- Registro de cada ejecución del ETL (útil para auditar las actualizaciones automáticas)
CREATE TABLE IF NOT EXISTS etl_runs (
    run_at_utc   TEXT    NOT NULL,
    start_date   TEXT    NOT NULL,
    end_date     TEXT    NOT NULL,
    rows_upserted INTEGER NOT NULL
);

-- Vista con el precio medio diario por serie
CREATE VIEW IF NOT EXISTS daily_prices AS
SELECT
    substr(ts_local, 1, 10)       AS day,
    series,
    ROUND(AVG(price_eur_mwh), 2)  AS avg_price,
    ROUND(MIN(price_eur_mwh), 2)  AS min_price,
    ROUND(MAX(price_eur_mwh), 2)  AS max_price,
    COUNT(*)                      AS hours
FROM prices
GROUP BY day, series;
