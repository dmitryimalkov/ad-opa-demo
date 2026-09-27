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
_**Комментарий: В той же salesdb — отдельной БД под это никто не заводил.**_

В коде DAG это видно прямо по POSTGRES_CONN_ID = "salesdb_postgres" и conn_info.schema (то есть имя БД) берётся из Airflow-коннекшена salesdb_postgres, который был настроен именно на salesdb.

Внутри salesdb сейчас две разные таблицы:

- sales — старая, учебная, с захардкоженными 5 строками, которая была ещё до этой сессии (из postgres-init/), с уже готовыми tenant_isolation_policy/tenant_a_direct_access/tenant_b_direct_access.
- sales_transactions — новая, которую завели DAG-и (_ensure_table() при первом запуске), с реальными объёмами (3381 строка company_a, 11408 строк company_b). Она переиспользует те же роли (tenant_company_a_role/tenant_company_b_role), но политики у неё свои, под своим именем (tenant_a_direct_access/tenant_b_direct_access — да, совпадают по названию с политиками на sales, но это разные объекты, привязанные каждый к своей таблице).

То есть отдельную БД не заводили сознательно — RLS и так разграничивает по строкам внутри одной БД, а Superset-подключения из плана будут смотреть именно на sales_transactions в salesdb.

 - Сразу проверка, что роль реально видит только свои строки (должно быть 1 строка с company_a, второй запрос — с company_b):
```bash
docker exec -i demo-postgres psql -U tenant_company_a_role -d salesdb -h localhost -c \
  "SELECT tenant_id, count(*) FROM sales_transactions GROUP BY tenant_id;"
docker exec -i demo-postgres psql -U tenant_company_b_role -d salesdb -h localhost -c \
  "SELECT tenant_id, count(*) FROM sales_transactions GROUP BY tenant_id;"
```
_**Комментарий**_
(Пароли попросит psql, если он не подхватит PGPASSWORD — можно добавить -e PGPASSWORD=... перед psql в docker exec, или добавить временно в pg_hba.conf доверие для localhost, если он уже так настроен для postgres.)
Вывод должен показать, что обе роли видят только свой tenant_id, двигаемся к authz.rego.

Далее, Прежде чем патчить authz.rego под bi_dashboard — необходимо проверить актуальный cat ~/ad-opa-demo/opa-policies/authz.rego. 
В плане есть запись про запланированное добавление rbac_allow_service (байпас same_tenant для сервисных ролей типа metadata_ingestion), но не уверен, реализовано ли это уже на файле, или всё ещё в планах — а патч под Superset должен лечь поверх реального текущего состояния, а не той копии, что мне присылали раньше.

# Шаг 2 Правим политики авторизации в authz.rego
Добавляю bi_dashboard во все четыре роли. Проще и надёжнее — перезаписать файл целиком, чем точечно резать sed-ом (риск задеть не ту строку с одинаковым текстом {"s3_access"}/set()).

Выполните на ВМ:
```bash
cat > ~/ad-opa-demo/opa-policies/authz.rego << 'EOF'
package platform.authz

import future.keywords.in

default allow = false

role_permissions := {
    "admin":   {
        "sales_data": {"read", "write"},
        "database": {"grant_direct_db_access"},
        "audit_log": {"view_audit_log"},
        "airflow_dag": {"airflow_dag_view", "airflow_dag_trigger", "airflow_dag_delete"},
        "airflow_variable": {"airflow_variable_view", "airflow_variable_trigger"},
        "s3_bucket": {"s3_access"},
        "bi_dashboard": {"bi_view"},
    },
    "analyst": {
        "sales_data": {"read"},
        "database": {"grant_direct_db_access"},
        "audit_log": set(),
        "airflow_dag": {"airflow_dag_view"},
        "airflow_variable": {"airflow_variable_view"},
        "s3_bucket": {"s3_access"},
        "bi_dashboard": {"bi_view"},
    },
    "viewer":  {
        "sales_data": set(),
        "database": set(),
        "audit_log": set(),
        "airflow_dag": set(),
        "airflow_variable": set(),
        "s3_bucket": set(),
        "bi_dashboard": set(),
    },
    # Сервисная роль для ingestion-агентов (OpenMetadata и т.п.).
    # Только чтение airflow-метаданных, без записи/триггеров/удаления
    # и без доступа к данным других ресурсов.
    "metadata_ingestion": {
        "sales_data": set(),
        "database": set(),
        "audit_log": set(),
        "airflow_dag": {"airflow_dag_view"},
        "airflow_variable": {"airflow_variable_view"},
        "s3_bucket": set(),
        "bi_dashboard": set(),
    },
}

# Роли, для которых tenant-изоляция намеренно не применяется —
# это служебные технические аккаунты, а не пользователи компаний.
service_roles := {"metadata_ingestion"}

rbac_allow {
    some role in input.user.roles
    input.action in role_permissions[role][input.resource.type]
}

rbac_allow_service {
    some role in input.user.roles
    role in service_roles
    input.action in role_permissions[role][input.resource.type]
}

same_tenant {
    input.user.tenant_id == input.resource.tenant_id
}

allow {
    rbac_allow
    same_tenant
}

# Сервисные роли обходят same_tenant — им по определению нужен
# обзор по всем тенантам сразу (см. документ по OpenMetadata ingestion).
allow {
    rbac_allow_service
}

# Явные причины отказа — показываем их разработчикам на демо,
# чтобы было видно, ПОЧЕМУ именно запрещено
deny_reason["cross_tenant_access"] {
    not same_tenant
    not rbac_allow_service
}

deny_reason["role_not_permitted"] {
    same_tenant
    not rbac_allow
}
EOF
```
*Проверка*
OPA у вас в docker-compose подхватывает файлы политик на лету — проверьте, что он принял без ошибок:

```bash
docker logs demo-opa --tail 5
```
Ожидаем "err":null. Пришлёте — двигаемся к opa_security_manager.py.
## Дополнительные проверки
```bash
curl -s -X POST http://localhost:8181/v1/data/platform/authz \
  -H 'Content-Type: application/json' \
  -d '{"input":{"user":{"tenant_id":"company_a","roles":["analyst"]},"action":"bi_view","resource":{"type":"bi_dashboard","tenant_id":"company_a"}}}' \
  | python3 -m json.tool

```
Ожидаемо: "allow": false, "deny_reason": {"cross_tenant_access": true}.

Если порт 8181 наружу с ВМ не проброшен — то же самое можно прогнать изнутри контейнера: docker exec demo-opa там скорее всего нет curl, так что тогда через docker exec -i demo-api python3 -c "..." с httpx/urllib на http://opa:8181/..., как в остальных проверках этой сессии.

# Шаг 3 Прописываем политики opa_security_manager.py (наследование)
Что здесь важно:

- raise_for_dashboard_access блокирует открытие конкретного чужого дашборда, но can_access_dashboard обязателен отдельно — без него чужие дашборды всё ещё были бы видны в общем списке /dashboard/list/, просто не открывались бы по клику. Тот же нюанс, что get_authorized_dag_ids у Airflow — одной точки перехвата недостаточно.
- Ресурсы без префикса <tenant>__ в имени (например, служебные дашборды без тенанта) — намеренно пропускаются к штатной FAB-логике, а не блокируются вслепую.
- OPA недоступен → отказ (fail-closed), как и в opa_auth_manager.py.
- Названия исключений/классов (DashboardAccessDeniedError, SupersetSecurityException) могут не совпасть с вашей версией Superset — если будет ImportError/AttributeError, пришлёте traceback, поправим под точную версию.

Закинуть файл на ВМ можно тем же scp, что и раньше:
```bash
scp -i /Users/dmitry/Downloads/id_rsa \
    opa_security_manager.py \
    user1@192.144.13.138:~/ad-opa-demo/superset-custom/opa_security_manager.py
```
# Шаг 4 Готовимся развернуть BI Superset
Скачайте оба (~/Downloads/Dockerfile и ~/Downloads/superset_config.py) и закиньте в ту же папку, куда уже уехал opa_security_manager.py:
```bash
scp -i /Users/dmitry/Downloads/id_rsa \
    ~/Downloads/Dockerfile ~/Downloads/superset_config.py \
    user1@192.144.13.138:~/ad-opa-demo/superset-custom/
```
### Дальше на ВМ, по порядку:

1. Метаданные-БД Superset в Postgres (отдельная от salesdb — там только тенантские данные):
