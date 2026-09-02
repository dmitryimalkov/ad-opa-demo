# Демо-стенд: AD/LDAP + Keycloak + OPA + PostgreSQL RLS для 2 тенантов

Цель: на одной VM в cloud.ru поднять полный контур из наших диаграмм и
живьём показать, что Company A и Company B работают на одном стенде,
но физически не могут увидеть данные друг друга.

## Почему OpenLDAP, а не настоящий AD

cloud.ru не предоставляет managed AD/Directory-сервис — только
IaaS/PaaS (VM, Object Storage, Managed Kubernetes, Managed PostgreSQL).
Поднимать полноценный Windows Server AD DS на VM для демо — избыточно
(лицензии, долгая настройка домена, DNS-инфраструктура).

**Keycloak общается с directory-сервисом по протоколу LDAP** — для
Keycloak реальный AD и OpenLDAP выглядят одинаково (User Federation →
LDAP provider). Поэтому для демо и обучения разработчиков OpenLDAP —
абсолютно рабочая замена: вся логика "группа → tenant_id/roles в JWT"
идентична. Когда стенд нужно будет подключить к реальному корпоративному
AD — меняется только Connection URL в Keycloak (LDAP provider), остальная
архитектура (OPA, RLS, Gateway) не трогается.

## 1. Что поднять в cloud.ru

Минимально достаточно **одной VM** (Evolution Compute):

- Рекомендуемая конфигурация: 2 vCPU / 4-8 GB RAM, Ubuntu 22.04/24.04
- Диск: 20-30 GB (система) — этого хватит для Docker-образов демо-стенда
- Сеть: одна VPC, один публичный IP (или доступ через VPN/bastion, если
  политика безопасности компании требует)
- Группа безопасности (Security Group): открыть входящие порты только
  с вашего IP/офисной сети, не на 0.0.0.0/0:
  - `8081` — Keycloak admin console
  - `8080` — phpldapadmin (просмотр LDAP-структуры)
  - `8000` — demo-api (Gateway)
  - `8181` — OPA (для отладки политик, можно закрыть после демо)
  - `22` — SSH

Managed PostgreSQL и Managed Kubernetes от cloud.ru **не обязательны**
для демо — контейнеризованный Postgres в docker-compose полностью
достаточен, чтобы показать RLS. Managed-сервисы имеет смысл использовать,
когда стенд перерастёт в pre-prod окружение.

## 2. Установка на VM

```bash
# на свежей Ubuntu VM
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# перелогиниться, затем:
git clone <ваш репозиторий с этим проектом> ad-opa-demo
cd ad-opa-demo
docker compose up -d
```

Проверить, что всё поднялось:
```bash
docker compose ps
```

## 3. Настройка Keycloak (один раз, через UI — 10 минут)

Откройте `http://<VM_IP>:8081`, логин `admin`/`admin`.

> **Про ошибку "HTTPS required":** в docker-compose уже есть служебный
> контейнер `keycloak-init`, который при первом старте стека сам заходит
> в Keycloak через общий сетевой namespace (`network_mode: service:keycloak`)
> и отключает требование HTTPS для realm `master` — именно поэтому
> `http://<VM_IP>:8081/admin` должен открываться сразу, без SSH-туннеля.
> Проверить, что он отработал: `docker logs demo-keycloak-init` — там
> должна быть строка `[init] Готово: master realm sslRequired=NONE`.
>
> Это исправляет доступ к **админке** (она всегда работает через realm
> `master`). Но когда вы создадите ниже realm `demo` — на него это
> автоматическое отключение не распространяется (realm `demo` ещё не
> существовал в момент старта контейнеров). Поэтому после шага 3.1
> сразу зайдите в **Realm settings** realm'а `demo` → General → **Require
> SSL** → выставьте **None** вручную — иначе запросы к
> `/realms/demo/protocol/openid-connect/token` (получение токенов
> Alice/Carol и т.д.) будут падать с той же ошибкой.

### 3.1 Создать realm
Create realm → имя `demo`.

### 3.2 Подключить LDAP (User Federation)
User federation → Add provider → `ldap`:
- Vendor: `Other`
- Connection URL: `ldap://ldap:389` (имя сервиса из docker-compose)
- Bind DN: `cn=admin,dc=demo,dc=local`
- Bind Credential: `AdminPass123!`
- Users DN: `ou=people,dc=demo,dc=local`
- Username LDAP attribute: `uid`
- Nажать **Test connection** → **Test authentication** → Save → Synchronize all users.

### 3.3 Подключить группы (Mappers)
В настройках LDAP-провайдера → Mappers → Add group-ldap-mapper:
- LDAP Groups DN: `ou=groups,dc=demo,dc=local`
- Group Name LDAP Attribute: `cn`
- Membership Attribute: `member`

Синхронизируйте группы (Sync LDAP Groups To Keycloak).

### 3.4 Создать client для demo-api
Clients → Create client:
- Client ID: `demo-gateway`
- Client authentication: Off (для демо используем Direct Access Grants —
  Resource Owner Password flow, чтобы просто получать токен через curl)
- Capability config: включить **Direct access grants**

### 3.5 Создать custom claim mappers: tenant_id и roles
Это ключевой шаг — именно здесь группы LDAP превращаются в claims токена.

Client `demo-gateway` → Client scopes → `demo-gateway-dedicated` → Add mapper → By configuration:

**Mapper 1 — tenant_id** (User Attribute или Hardcoded per group — для
демо проще всего сделать через **Group Membership mapper** + скрипт
маппинга на стороне demo-api, но нагляднее — назначить каждому
пользователю LDAP-атрибут `businessCategory` со значением tenant_id
(`company_a`/`company_b`) при создании пользователя, и замаппить его
через User Attribute mapper → Token Claim Name: `tenant_id`).

**Mapper 2 — roles**: Group Membership mapper →
Token Claim Name: `roles`, Full group path: Off — тогда в токене окажется
массив имён групп (`CompanyA-Analysts` и т.п.), который demo-api
интерпретирует. Для строгого соответствия ролям `admin/analyst/viewer`
из наших OPA-политик проще всего добавить в demo-api маленькую функцию
нормализации имени группы в роль (`CompanyA-Analysts` → `analyst`) —
либо сразу назвать LDAP-группы `analyst`/`admin`/`viewer` без префикса
компании, а tenant_id брать отдельным атрибутом (это чище и рекомендуется
для реального AD-интеграции тоже).

> Для быстрого демо разработчикам проще всего пойти по второму пути:
> переименовать группы в LDIF на `analyst`, `admin`, `viewer` и добавить
> отдельный LDAP-атрибут `o` (organization) со значением `company_a`/
> `company_b`, замапленный как `tenant_id`. Это ровно то же самое, что
> происходит в реальном AD с department/extensionAttribute.

## 4. Сценарий демонстрации разработчикам

### Шаг 1 — получить токен Alice (Company A, analyst)
```bash
curl -s -X POST "http://<VM_IP>:8081/realms/demo/protocol/openid-connect/token" \
  -d "client_id=demo-gateway" \
  -d "grant_type=password" \
  -d "username=alice" \
  -d "password=Password123!" | jq -r .access_token
```

### Шаг 2 — посмотреть, что Gateway увидел в токене
```bash
TOKEN_ALICE=<вставить токен>
curl -s http://<VM_IP>:8000/whoami -H "Authorization: Bearer $TOKEN_ALICE" | jq
```
Ожидаемо: `tenant_id: company_a`, `roles: ["analyst"]`.

### Шаг 3 — запросить данные под Alice
```bash
curl -s http://<VM_IP>:8000/sales -H "Authorization: Bearer $TOKEN_ALICE" | jq
```
Видны только строки `company_a`.

### Шаг 4 — та же операция под Carol (Company B)
```bash
TOKEN_CAROL=<токен carol/Password123!>
curl -s http://<VM_IP>:8000/sales -H "Authorization: Bearer $TOKEN_CAROL" | jq
```
Видны только строки `company_b` — **тот же самый эндпоинт, тот же код**.

### Шаг 5 — главный "вау-момент" для разработчиков: попытка подмены tenant_id
```bash
curl -s "http://<VM_IP>:8000/sales?tenant_id=company_b" \
  -H "Authorization: Bearer $TOKEN_ALICE" | jq
```
Alice всё равно получит только `company_a` — покажите в ответе поле
`note_ignored_query_param`, и объясните: даже если Gateway случайно
использует параметр запроса где-то в логике, **RLS в Postgres всё равно
не пропустит чужие строки**, потому что `app.tenant_id` в сессии
выставляется из JWT, а не из query.

### Шаг 6 — показать отказ по роли (Dave, viewer, Company B)
```bash
TOKEN_DAVE=<токен dave/Password123!>
curl -s http://<VM_IP>:8000/sales -H "Authorization: Bearer $TOKEN_DAVE" | jq
```
Ожидаемо: `403`, `deny_reason: ["role_not_permitted"]` — Dave как viewer
не имеет доступа к сырым `sales_data` по нашей OPA-матрице.

### Шаг 7 — показать сами политики и тесты (для инженерной аудитории)
```bash
docker exec -it demo-opa opa test /policies -v
```
Запустите тесты изоляции прямо на демо — это самый убедительный аргумент
для разработчиков: изоляция проверяется автоматически, не "на словах".

## 5. Что стоит рассказать разработчикам отдельно (концептуально)

- **Где именно проставляется tenant_id** — пройдитесь по коду
  `demo-api/main.py`: JWT → `extract_user_context` → OPA → `SET app.tenant_id`.
  Покажите, что нигде в коде нет `if tenant == "company_a"` — вся
  изоляция декларативна (Rego-политика + SQL RLS-политика), а не
  захардкожена в бизнес-логике.
- **RLS — последний рубеж, а не единственный.** Даже если бы Gateway
  содержал баг и не звал OPA вообще — Postgres всё равно бы отфильтровал
  строки, если `app.tenant_id` корректно выставлен. А если сессия вообще
  не выставит `app.tenant_id` — `FORCE ROW LEVEL SECURITY` в этом стенде
  просто не покажет ни одной строки (это тоже стоит продемонстрировать
  отдельным вызовом psql без `SET`).
- **Путь к реальному AD** — покажите, что единственное изменение для
  перехода с демо на прод — это Connection URL в Keycloak LDAP-провайдере
  на реальный AD-контроллер, плюс маппинг реальных AD-групп/атрибутов
  вместо `businessCategory`/`cn` из нашего LDIF.

## 7. Прямой доступ к БД (DBeaver) через self-service credentials

Это отдельный сценарий, не похожий на остальной demo-api — не про
Gateway, проксирующий запрос, а про выдачу пользователю СОБСТВЕННЫХ
credentials к Postgres, которыми он дальше сам подключается любым
клиентом (DBeaver, psql, что угодно), полностью МИМО Gateway и OPA.

### Почему это отдельный путь

DBeaver говорит с Postgres по бинарному протоколу, а не по HTTP —
там негде вызвать OPA на каждый SQL-запрос. Поэтому OPA здесь
проверяется один раз — в момент, когда пользователь просит выдать
ему credentials, а не на каждый последующий SELECT. Дальше изоляцию
держит не Gateway, а Row Policy, привязанная к самой роли подключения
(`postgres-init/02-tenant-roles.sql`).

### Как получить credentials

```bash
TOKEN_ALICE=$(curl -s -X POST "http://localhost:8081/realms/demo/protocol/openid-connect/token" -d "client_id=demo-gateway" -d "grant_type=password" -d "username=alice" -d "password=Password123!" | jq -r .access_token)

curl -s -X POST http://localhost:8000/db-credentials -H "Authorization: Bearer $TOKEN_ALICE" | jq
```

Ожидаемый ответ:
```json
{
  "warning": "Сохраните пароль сейчас — повторно он показан не будет...",
  "host": "192.144.13.138",
  "port": 5432,
  "database": "salesdb",
  "username": "alice_company_a",
  "password": "<сгенерированный, каждый раз новый>"
}
```

### Проверка в DBeaver

Создайте новое подключение PostgreSQL с этими `host`/`port`/`database`/
`username`/`password` — обычный пароль, никакого OIDC/LDAP в самом
DBeaver настраивать не нужно. Выполните `SELECT * FROM sales` —
должны увидеть только строки `company_a` (или `company_b`, если
получали credentials под Carol), причём **автоматически**, без
единого `WHERE` в запросе.

### Проверка отказа (Dave, viewer)

```bash
TOKEN_DAVE=$(curl -s -X POST "http://localhost:8081/realms/demo/protocol/openid-connect/token" -d "client_id=demo-gateway" -d "grant_type=password" -d "username=dave" -d "password=Password123!" | jq -r .access_token)

curl -s -X POST http://localhost:8000/db-credentials -H "Authorization: Bearer $TOKEN_DAVE" | jq
```
Ожидаем `403` с `deny_reason: ["role_not_permitted"]` — Dave как viewer
не имеет права на `grant_direct_db_access` по нашей OPA-матрице,
поэтому даже роль в Postgres для него никогда не создастся.

### Что почеркнуть разработчикам

Каждый вызов `/db-credentials` **перевыпускает** пароль (`ALTER ROLE`) —
предыдущий сразу перестаёт действовать. Это сознательный выбор:
проще выдавать заново по требованию, чем хранить где-то склад
активных паролей, который сам по себе стал бы точкой утечки.

## 8. Быстрая проверка "что если RLS отключить" (опционально, для эффекта)

Чтобы наглядно показать разработчикам ЦЕННОСТЬ RLS — можно временно
подключиться под суперпользователем `postgres` (не `app_user`) и
выполнить `SELECT * FROM sales` без `SET app.tenant_id` — суперпользователь
по умолчанию игнорирует RLS, и будут видны строки обеих компаний.
Это хороший повод объяснить, почему в `docker-compose.yml` demo-api
специально подключается под ограниченным `app_user`, а не под `postgres`
для обычных запросов — и почему `ADMIN_DB_DSN` (суперпользователь,
нужен только для `/db-credentials`) — отдельная, более чувствительная
переменная, которую стоит беречь строже, чем `DB_DSN`.
