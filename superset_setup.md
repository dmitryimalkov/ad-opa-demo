# Шаг 1 — сделать tenant_company_a_role/tenant_company_b_role логинящимися
- Сейчас они NOLOGIN (только для RLS-политик через SET ROLE/GRANT). 
- Заводим им пароли — только под будущие Superset-подключения, права не меняются (те же tenant_a_direct_access/tenant_b_direct_access, только SELECT):
- Сгенирировать два пароля и выполнить команды:
```bash
docker exec -i demo-postgres psql -U postgres -d salesdb -c \
  "ALTER ROLE tenant_company_a_role LOGIN PASSWORD 'n8P4bfFbcNlFvqGeNsqHHTTC';"
docker exec -i demo-postgres psql -U postgres -d salesdb -c \
  "ALTER ROLE tenant_company_b_role LOGIN PASSWORD 'MwBYElSYMSt2hLnXWcpLnHA2';"

```
