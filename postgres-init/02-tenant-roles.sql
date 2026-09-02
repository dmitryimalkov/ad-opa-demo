-- Групповые роли по tenant для ПРЯМОГО доступа к БД (например, через DBeaver).
-- В отличие от app_user (которым подключается demo-api и который полагается
-- на SET app.tenant_id из кода), эти роли изолируют данные ЧЕРЕЗ ТО, КЕМ
-- установлено соединение — RLS-политика привязана прямо к роли (TO ...),
-- поэтому работает без какого-либо приложения между клиентом и БД.

CREATE ROLE tenant_company_a_role NOLOGIN;
CREATE ROLE tenant_company_b_role NOLOGIN;

GRANT SELECT ON sales TO tenant_company_a_role, tenant_company_b_role;

-- Permissive-политики складываются по ИЛИ с уже существующей
-- tenant_isolation_policy из 01-init.sql — она не мешает, просто
-- для прямых подключений через tenant-роль всегда false
-- (current_setting('app.tenant_id') пуст), а вот эти политики её
-- перекрывают, добавляя доступ на основе самой роли.

CREATE POLICY tenant_a_direct_access ON sales
    FOR SELECT TO tenant_company_a_role
    USING (tenant_id = 'company_a');

CREATE POLICY tenant_b_direct_access ON sales
    FOR SELECT TO tenant_company_b_role
    USING (tenant_id = 'company_b');
