-- HTTP access log уровня инфраструктуры — отдельно от audit_log
-- (который про бизнес-решения OPA). Эта таблица логирует ВСЕ запросы
-- к Gateway без исключения, включая те, что не дошли до OPA вообще
-- (например, невалидный/просроченный JWT — 401 до вызова check_opa).

CREATE TABLE IF NOT EXISTS audit.request_log (
    ts DateTime64(3),
    method String,
    path String,
    status_code UInt16,
    duration_ms Float32,
    client_ip String
) ENGINE = MergeTree()
ORDER BY ts;
