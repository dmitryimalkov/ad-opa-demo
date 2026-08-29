-- Таблица продаж с колонкой tenant_id
CREATE TABLE sales (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    product TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    sale_date DATE NOT NULL
);

-- Тестовые данные: намеренно похожие суммы, чтобы на демо сразу было видно,
-- что company_a не видит company_b и наоборот
INSERT INTO sales (tenant_id, region, product, amount, sale_date) VALUES
('company_a', 'eu', 'Widget X', 1000, '2026-07-01'),
('company_a', 'eu', 'Widget Y', 1500, '2026-07-15'),
('company_a', 'uk', 'Widget X', 900,  '2026-08-01'),
('company_b', 'eu', 'Gadget Z', 5000, '2026-07-05'),
('company_b', 'us', 'Gadget W', 7000, '2026-08-10');

-- Включаем Row-Level Security
ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales FORCE ROW LEVEL SECURITY;

-- Политика: видны только строки своего tenant_id.
-- Значение current_setting('app.tenant_id') выставляется demo-api
-- ПОСЛЕ проверки JWT и OPA — никогда не берётся от клиента напрямую.
CREATE POLICY tenant_isolation_policy ON sales
    USING (tenant_id = current_setting('app.tenant_id', true));

-- Отдельная роль приложения (не суперпользователь) — на неё и распространяется RLS.
-- Суперпользователь postgres игнорирует RLS по умолчанию, поэтому демо-api
-- должен подключаться именно под app_user, а не под postgres.
CREATE ROLE app_user LOGIN PASSWORD 'app_user_pass';
GRANT SELECT, INSERT ON sales TO app_user;
GRANT USAGE, SELECT ON SEQUENCE sales_id_seq TO app_user;
