# Мультитенантный Airflow через OPA — руководство

## 1. Задача

Пользователи Company A и Company B работают в одном Airflow с датасетами
и метаданными (DAG, Variables), не видя данные друг друга. Разграничение
дополнительно по ролям (admin/analyst/viewer). Требование: раз control-plane
Airflow — это HTTP/REST (в отличие от Postgres/ClickHouse, где сырой
протокол не даёт встроиться), OPA должен проверяться **на каждое
действие**, а не только на этапе выдачи "пропуска" (как мы делали для
прямого доступа к БД).

## 2. Матрица ролей

| Роль | Datasets (DAG) | Metadata (Variables) |
|---|---|---|
| admin | просмотр, запуск, удаление своих DAG | чтение и запись |
| analyst | только просмотр своих DAG | только чтение |
| viewer | ничего | ничего |

Изоляция по компании — сквозная: чужие DAG не просто недоступны, а
физически не видны в списке.

## 3. Архитектурное решение

Три отдельных механизма, каждый со своей ролью:

1. **Аутентификация** — Flask-AppBuilder (`AUTH_TYPE = AUTH_LDAP`),
   проверяет только пароль напрямую в нашем LDAP. Больше ничего не
   делает — ни ролей, ни групп отсюда не берём.
2. **Определение tenant/роли** — **живой LDAP-поиск** прямо внутри
   нашего Auth Manager: `(member=<DN пользователя>)` на стороне
   группы, тот же принцип, что мы использовали весь проект через
   `ldapsearch`. НЕ используется `memberof`-overlay и НЕ используется
   встроенный ролевой sync Flask-AppBuilder (`AUTH_ROLES_MAPPING`) —
   см. раздел 4 почему.
3. **Авторизация** — кастомный `OpaFabAuthManager(FabAuthManager)`,
   переопределяющий конкретные методы принятия решений так, чтобы они
   спрашивали наш OPA (`authz.rego`, тот же файл, что у Gateway) на
   каждый вызов.

### Файлы

| Файл | Роль |
|---|---|
| `airflow-custom/Dockerfile` | Образ Airflow + `apache-airflow-providers-fab[ldap]` + `python-ldap` (нужны системные `libldap2-dev libsasl2-dev gcc`) |
| `airflow-custom/webserver_config.py` | `AUTH_TYPE=AUTH_LDAP` — только проверка пароля |
| `airflow-custom/opa_auth_manager.py` | Живой LDAP-поиск групп + вызовы OPA |
| `airflow-dags/company_a__load_dataset.py`, `company_b__load_dataset.py` | Демо-DAG, названы с префиксом tenant_id через `__` |
| `postgres-init/03-create-airflow-db.sql` | Отдельная БД для состояния Airflow (тот же паттерн, что `keycloak`) |
| `opa-policies/authz.rego` | Ресурсы `airflow_dag`/`airflow_variable` добавлены в тот же `role_permissions` |

### Naming convention DAG — ключевой механизм изоляции

`company_a__load_dataset` — префикс до `__` читается как `tenant_id`
напрямую (без доп. маппинга). Это единственное, на чём держится
привязка DAG к компании.

## 4. Все найденные особенности (и почему решили именно так)

### 4.1. `airflow standalone` подменяет Auth Manager

Команда `standalone` **принудительно** переключает на встроенный
`SimpleAuthManager`, полностью игнорируя `AIRFLOW__CORE__AUTH_MANAGER`.
Решение — запускать компоненты раздельно:
```bash
airflow db migrate && (airflow scheduler &) && (airflow dag-processor &) && airflow api-server
```

### 4.2. DAG Processor — отдельный обязательный компонент в Airflow 3.x

В 2.x парсинг DAG был частью `scheduler`. В 3.x — отдельный процесс
`airflow dag-processor`. Без него файлы лежат на диске, но
`airflow dags list` показывает `No data found`, и никакой ошибки
нигде не появляется — просто тихо ничего не происходит.

### 4.3. `memberof`-overlay не подошёл под нашу LDAP-схему

Переменная `LDAP_ENABLE_MEMBEROF` **не существует** у
`osixia/openldap` (моя ошибка, не проверил заранее). У образа есть
встроенный bootstrap для `memberof`, но он захардкожен под
`groupOfUniqueNames`/`uniqueMember` (схема AD), а у нас
`groupOfNames`/`member`. Решение — отказались от overlay полностью,
делаем живой поиск групп в коде (см. `_fetch_ldap_groups` в
`opa_auth_manager.py`).

### 4.4. `filter_authorized_dag_ids` — не тот метод

Самая дорогая по времени находка. Список DAG в UI Airflow формирует
**`get_authorized_dag_ids`**, а не `filter_authorized_dag_ids` —
именно `FabAuthManager` переопределяет первый, используя
`access_control`. Мы полдня переопределяли второй, из-за чего OPA ни
разу не вызывался, а список был всегда пуст (Public-роль по
умолчанию не имеет прав на DAG). Оба метода сейчас переопределены в
`opa_auth_manager.py` — на случай, если какой-то другой путь всё же
использует `filter_authorized_dag_ids`.

### 4.5. Кэширование класса в уже запущенном процессе

После правки `opa_auth_manager.py` (это bind-mount, не часть образа)
**`docker compose restart airflow` недостаточно** — уже запущенный
Python-процесс держит импортированный модуль в памяти. Нужно:
```bash
docker compose stop airflow && docker rm demo-airflow && docker compose up -d airflow
```

### 4.6. `api-server` — новое имя команды вместо `webserver`

В Airflow 3.x веб/API-компонент запускается командой `airflow
api-server`, не `airflow webserver`.

### 4.7. `403` на Dashboard у viewer — это нормально, не баг

Виджеты главной страницы (Deadlines, История) требуют доступ к
DAG-related данным. У viewer нет прав на `airflow_dag` вообще — Airflow
показывает `403 Forbidden` баннером прямо на Dashboard. Смотреть нужно
именно вкладку **Dag-и** — там корректно `0 Dags`, без ошибки.

### 4.8. LDAP без persistent volume — данные терялись при пересоздании

Как и Postgres/ClickHouse изначально — исправлено добавлением
`ldapdata:/var/lib/ldap` и `ldapconfig:/etc/ldap/slapd.d`.

### 4.9. Fail-closed по умолчанию

Если OPA недоступен, `_check_opa` возвращает `False` (не `True`) —
сознательное решение: сбой инфраструктуры не должен превращаться в
полный доступ по умолчанию.

## 5. Известное ограничение (не реализовано)

Решения OPA внутри `opa_auth_manager.py` **не пишутся** в
`audit.audit_log` ClickHouse — в отличие от `demo-api`, где это
встроено в `check_opa()`. Аудит для Airflow-действий сейчас есть
только в виде debug-файла (`/tmp/opa_auth_manager_debug.log`),
временного и не персистентного. Логичное развитие — добавить туда же
запись в ClickHouse, как в Gateway.

---

## 6. Частые команды и отладка

### Проверить, какой Auth Manager реально загружен
```bash
docker exec demo-airflow python3 -c "from airflow.configuration import conf; print(conf.get('core', 'auth_manager'))"
```

### Проверить точную сигнатуру метода в установленной версии (не доверять документации вслепую)
```bash
docker exec demo-airflow python3 -c "
from airflow.providers.fab.auth_manager.fab_auth_manager import FabAuthManager
import inspect
print(inspect.signature(FabAuthManager.get_authorized_dag_ids))
"
```

### Список DAG и ошибки импорта — независимо от UI/авторизации
```bash
docker exec demo-airflow airflow dags list
docker exec demo-airflow airflow dags list-import-errors
```

### Прямой вызов нашего Auth Manager в обход HTTP — самый быстрый способ проверить логику
```bash
docker exec demo-airflow python3 -c "
import sys; sys.path.insert(0, '/opt/airflow/custom')
from opa_auth_manager import OpaFabAuthManager
class FakeUser: username = 'alice'
mgr = OpaFabAuthManager()
print(mgr.get_authorized_dag_ids(user=FakeUser()))
"
```

### Живой LDAP-поиск групп — проверка того же запроса, что делает наш код
```bash
docker exec demo-airflow python3 -c "
import ldap
conn = ldap.initialize('ldap://ldap:389')
conn.simple_bind_s('cn=admin,dc=demo,dc=local', 'AdminPass123!')
print(conn.search_s('ou=groups,dc=demo,dc=local', ldap.SCOPE_SUBTREE, '(member=uid=alice,ou=people,dc=demo,dc=local)', ['cn']))
"
```

### Прямая проверка пароля пользователя, в обход Airflow/FAB
```bash
docker exec demo-ldap ldapwhoami -x -D "uid=alice,ou=people,dc=demo,dc=local" -w "Password123!" -H ldap://localhost:389
```

### Наш debug-лог (если ещё не убран из кода)
```bash
docker exec demo-airflow cat /tmp/opa_auth_manager_debug.log
docker exec demo-airflow rm -f /tmp/opa_auth_manager_debug.log   # очистить перед новым тестом
```

### Полное пересоздание после правки кода (не restart!)
```bash
docker compose stop airflow && docker rm demo-airflow && docker compose up -d airflow
```

### Таблица "симптом → причина"

| Симптом | Причина | Решение |
|---|---|---|
| `Forcing auth manager to SimpleAuthManager` в логах | Команда `standalone` | Раздельный запуск компонентов (4.1) |
| `airflow dags list` → `No data found`, файлы на диске есть | Нет `dag-processor` | Добавить в command (4.2) |
| `Invalid login` в UI | Проблема с LDAP bind/данными | `ldapwhoami` напрямую, проверить что `ou=people` вообще существует |
| `result: 32 No such object` в логах Airflow | LDAP-дерево пустое (нет persistent volume, контейнер пересоздался) | Перезагрузить `ldap-init`, добавить volume (4.8) |
| Логин проходит, но `0 Dags` без ошибок | Переопределён не тот метод (4.4), или debug-файл не создаётся вовсе | Проверить `get_authorized_dag_ids`, полное пересоздание контейнера (4.5) |
| Прямой Python-вызов работает, а через браузер — нет | Кэш процесса, контейнер не пересоздан по-настоящему | `stop && rm && up`, не `restart` |
| `403` на Dashboard у viewer | Ожидаемо (4.7) | Смотреть вкладку Dag-и, не главную страницу |
