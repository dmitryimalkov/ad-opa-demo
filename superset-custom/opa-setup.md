# Настройка Superset поверх OPA (multitenancy BI)

Sep 27, 2026 · @Dimi

## Обзор

Цель: добавить BI (Apache Superset) поверх демо-стенда так, чтобы Alice видела только свои дашборды (company\_a), а Carol — только свои (company\_b), по тому же принципу, что уже реализован в Airflow.

**Общая схема — два независимых слоя защиты:**

1. **Вход — через LDAP, как и везде на стенде.** Superset настроен с `AUTH_TYPE=AUTH_LDAP` — никакого локального admin/admin, логин и пароль проверяются напрямую в LDAP, как у Airflow/Postgres/ClickHouse/MinIO.
2. **Авторизация — через OPA на каждое обращение,** а не через статичный маппинг LDAP-группы на роль Superset один раз при логине. Кастомный `OpaSupersetSecurityManager` перехватывает доступ к дашбордам/датасетам и спрашивает OPA каждый раз — точно так же, как `OpaFabAuthManager` у Airflow.

**Изоляция данных — двухслойная:**

- **На уровне строк (Postgres RLS)** — два отдельных Database-подключения в Superset (`company_a_salesdb`, `company_b_salesdb`), каждое логинится в Postgres под своей tenant-ролью (`tenant_company_a_role`/`tenant_company_b_role`) — теми же, что и в RLS-политиках таблицы `sales_transactions`, созданной DAG-ами. Даже произвольный SQL в SQL Lab физически не увидит чужие строки.
- **На уровне объектов Superset (OPA)** — какие дашборды/датасеты вообще видны и открываются — через новый тип ресурса `bi_dashboard` в `authz.rego`, с тем же механизмом `same_tenant`/`service_roles`, что и у остальных ресурсов стенда.

## Шаги (кратко)

1. **`authz.rego`** — добавлен новый тип ресурса `bi_dashboard` (действие `bi_view`) во все существующие роли (`admin`, `analyst`, `viewer`, `metadata_ingestion`) плюс новая сервисная роль `bi_admin` (добавлена в `service_roles`, обходит `same_tenant` через `rbac_allow_service` — тот же механизм, что уже использовался для `metadata_ingestion`).
2. **`superset-custom/opa_security_manager.py`** — новый файл: класс `OpaSupersetSecurityManager(SupersetSecurityManager)`. Логин остаётся штатным (LDAP через Flask-AppBuilder), но решения о доступе к дашбордам/датасетам переопределены так, чтобы каждый раз спрашивать OPA — по образцу `OpaFabAuthManager` в Airflow. LDAP-поиск групп и `TENANT_MAP`/`ROLE_MAP` сознательно продублированы (не вынесены в общий модуль), как и везде на стенде.
3. **`superset-custom/superset_config.py`** — `AUTH_TYPE = AUTH_LDAP` с теми же параметрами, что у Airflow, `CUSTOM_SECURITY_MANAGER = OpaSupersetSecurityManager`, `PUBLIC_ROLE_LIKE = None` (без логина никто не входит), отдельная метаданные-БД `superset_meta` в Postgres (не `salesdb`).
4. **`superset-custom/Dockerfile`** — кастомная сборка поверх `apache/superset:3.1.0` (добавлены `python-ldap`, `httpx`, `psycopg2-binary` и системные `libldap2-dev`/`libsasl2-dev`), по тому же паттерну, что `airflow-custom/` и `minio-sync/`.
5. **`docker-compose.yml`** — добавлен сервис `superset`, поднят через `docker compose build && docker compose up -d`. Проверено: LDAP-логин работает снаружи на порту 8088 (в отличие от MinIO, у которого 9000/9001 закрыты файрволом); прямые curl-запросы к OPA подтвердили, что `bi_dashboard`/`bi_admin`/`service_roles` считаются корректно; `docker logs demo-superset` — чистый старт без ошибок импорта.

## Подробно: после создания Database-подключений

**Почему не одно подключение под Alice.** Был вопрос, может ли Alice (company\_a) сама завести оба Database-подключения (company\_a и company\_b). Решение — нет: тенант-скопированный аккаунт аналитика не должен держать/создавать инфраструктуру, охватывающую оба тенанта — это ломало бы весь принцип изоляции, даже если сами дашборды/датасеты потом и ограничиваются OPA. Вместо этого завели отдельный платформенный аккаунт.

**Платформенный аккаунт `superset-admin`.** Аналогично `openmetadata-svc` у Airflow/OpenMetadata, но такого аккаунта для Superset ещё не было — завели с нуля:

- Новая LDAP-группа `Platform-BiAdmin`, в неё добавлен пользователь `superset-admin`.
- В `authz.rego`: новая сервисная роль `bi_admin` в `role_permissions` (права только на `bi_dashboard: {bi_view}`, на бизнес-данные/DAG/переменные/S3 — пустые множества, то есть никаких прав кроме BI); роль добавлена в `service_roles`, чтобы она обходила проверку `same_tenant` (`rbac_allow_service`) — тот же механизм, что уже использовался для `metadata_ingestion`.
- В `opa_security_manager.py`: `ROLE_MAP` дополнен записью `"BiAdmin": "bi_admin"`, чтобы LDAP-группа `Platform-BiAdmin` корректно разбиралась в роль.
- Через `docker exec -it demo-superset superset shell` вручную повысил пользователю `superset-admin` роль FAB `Admin` (открывает в UI пункты меню Settings, недоступные обычному Gamma-пользователю: Database Connections, Datasets и т.п.). Важно: роль FAB `Admin` даёт доступ к UI-функциям управления, но фактический доступ к конкретным дашбордам/датасетам всё равно решает OPA через `OpaSupersetSecurityManager` — роль `bi_admin` там и есть то, что реально даёт доступ к обоим тенантам.

**Созданы два Database-подключения** под `superset-admin`: `company_a_salesdb` (host `postgres`, имя БД — фактически `salesdb`, пользователь `tenant_company_a_role`) и `company_b_salesdb` (то же самое, пользователь `tenant_company_b_role`). Важно: оба подключаются к одной и той же ФИЗИЧЕСКОЙ БД `salesdb` — разделение данных обеспечивает только Postgres RLS на основе того, под какой ролью идёт подключение, а не разные БД. Поле “DATABASE NAME” в форме — это имя ФИЗИЧЕСКОЙ БД (`salesdb` в обоих случаях), а `company_a_salesdb`/`company_b_salesdb` — это DISPLAY NAME подключения в Superset (эти два поля легко перепутать — пришлось уточнять по ходу завода первого подключения).

**Обнаруженное ограничение UI: у датасетов нет отдельного поля “Имя”.** План был дать датасетам то же имя-префикс `<tenant_id>__...`, что и дашбордам и DAG'ам. Но в Superset 3.1.0 у физических датасетов поле “Name”, отдельное от `table_name`, просто отсутствует — проверено в двух вкладках модалки редактирования (SOURCE — даже после снятия замка редактирования; SETTINGS) — есть только `table_name`, который у обоих тенантов одинаков — `sales_transactions`. Дашбордов это не касается — у них `dashboard_title` редактируется свободно, ограничений интерфейса нет.

**Исправление: `DB_NAME_TENANT_MAP`.** Вместо переименования датасетов тенант датасета теперь определяется тем, к какому Database-подключению он принадлежит. В `opa_security_manager.py` добавлен словарь:

```python
DB_NAME_TENANT_MAP = {"company_a_salesdb": "company_a", "company_b_salesdb": "company_b"}
```

Логика в `_opa_allows_datasource`: сначала пробует выделить тенант из префикса имени (`<tenant>__...`) — на случай, если в будущем появится способ их переименовать; если префикса нет — берёт `database_name` связанного с датасетом Database-подключения и ищет его в `DB_NAME_TENANT_MAP`. Если тенант не определился ни так, ни так — ресурс считается вне периметра этой проверки, и решение отдаётся штатному FAB-механизму (не блокируется вслепую). Обновлённый файл занова собран в образ и перезапущен в `demo-superset` — `docker logs` подтвердил чистый старт.

**Созданы оба датасета.** Один `sales_transactions` на каждом Database-подключении — в итоге в списке датасетов две строки с одинаковым именем, но разными Database в столбце “Database” — это ожидаемо и нормально, переименовывать их не нужно.

## Что дальше (завтра)

Инфраструктура готова: оба Database-подключения и оба датасета созданы. Осталось:

1. **Создать по одному чарту** на каждом датасете (`sales_transactions` из `company_a_salesdb` и из `company_b_salesdb`).
2. **Собрать дашборды** с именами по соглашению `<tenant_id>__<name>`, например `company_a__sales_overview` и `company_b__sales_overview` — именно по этому префиксу `OpaSupersetSecurityManager` будет определять тенант дашборда и спрашивать OPA.
3. **Проверить изоляцию под альтернативными пользователями**:
   - `alice`/`Password123!` (company\_a) — должна видеть только `company_a__sales_overview`, втоорой дашборд не должен появиться даже в списке (проверяется переопределённый `can_access_dashboard`).
   - `carol`/`Password123!` (company\_b) — только `company_b__sales_overview`.
   - Прямой переход по URL на чужой дашборд (мимо списка) — ожидается отказ (`DashboardAccessDeniedError`/403), проверяет `raise_for_dashboard_access`.
   - Дополнительно можно проверить, что даже при попытке открыть чужой датасет напрямую (SQL Lab или API) — срабатывает `raise_for_access`/`SupersetSecurityException`.

При отладке полезно смотреть отладочный лог `/tmp/opa_security_manager_debug.log` внутри контейнера `demo-superset` — там видно точное решение OPA на каждый запрос.
