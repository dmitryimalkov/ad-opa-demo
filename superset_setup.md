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
Комментарий: В той же salesdb — отдельной БД под это никто не заводил.

В коде DAG это видно прямо по POSTGRES_CONN_ID = "salesdb_postgres" и conn_info.schema (то есть имя БД) берётся из Airflow-коннекшена salesdb_postgres, который был настроен именно на salesdb.

Внутри salesdb сейчас две разные таблицы:

- sales — старая, учебная, с захардкоженными 5 строками, которая была ещё до этой сессии (из postgres-init/), с уже готовыми tenant_isolation_policy/tenant_a_direct_access/tenant_b_direct_access.
- sales_transactions — новая, которую завели DAG-и (_ensure_table() при первом запуске), с реальными объёмами (3381 строка company_a, 11408 строк company_b). Она переиспользует те же роли (tenant_company_a_role/tenant_company_b_role), но политики у неё свои, под своим именем (tenant_a_direct_access/tenant_b_direct_access — да, совпадают по названию с политиками на sales, но это разные объекты, привязанные каждый к своей таблице).

То есть отдельную БД не заводили сознательно — RLS и так разграничивает по строкам внутри одной БД, а Superset-подключения из плана будут смотреть именно на sales_transactions в salesdb.
