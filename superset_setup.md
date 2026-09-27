# Шаг 1 — сделать tenant_company_a_role/tenant_company_b_role логинящимися
- Сейчас они NOLOGIN (только для RLS-политик через SET ROLE/GRANT). 
- Заводим им пароли — только под будущие Superset-подключения, права не меняются (те же tenant_a_direct_access/tenant_b_direct_access, только SELECT):
