-- Единая таблица для решений OPA со ВСЕХ путей платформы (Gateway,
-- /db-credentials, в будущем /s3-upload-url, Airflow Auth Manager и т.д.)
-- MergeTree — классический ClickHouse движок для append-only данных,
-- ORDER BY по времени и tenant — типичный профиль запросов
-- "покажи все отказы для Company B за последнюю неделю".

CREATE TABLE IF NOT EXISTS audit.audit_log (
    ts DateTime64(3),
    user_sub String,
    user_tenant_id String,
    action String,
    resource_type String,
    resource_tenant_id String,
    allow UInt8,
    deny_reason String
) ENGINE = MergeTree()
ORDER BY (ts, user_tenant_id);
