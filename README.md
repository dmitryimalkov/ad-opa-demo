# Демо-стенд: AD/LDAP + Keycloak + OPA + PostgreSQL RLS для 2 тенантов

Цель: на одной VM в cloud.ru поднять полный контур из наших диаграмм и
живьём показать, что Company A и Company B работают на одном стенде,
но физически не могут увидеть данные друг друга.

# Подключение
chmod 600 ~/Downloads/id_rsa

#### Вход на ВМ
ssh -i ~/Downloads/id_rsa user1@192.144.13.138

/Users/dmitry/Downloads/ad-opa-demo-4
#### Запись нового docker-compose
scp -i ~/Downloads/id_rsa /Users/dmitry/Downloads/ad-opa-demo-4/docker-compose.yml user1@192.144.13.138:/home/user1/ad-opa-demo/docker-compose.yml

#### Запись нового sql

/Users/dmitry/Downloads/ad-opa-demo-4/postgres-init

scp -i ~/Downloads/id_rsa /Users/dmitry/Downloads/ad-opa-demo-4/postgres-init/00-create-keycloak-db.sql user1@192.144.13.138:/home/user1/ad-opa-demo/postgres-init/00-create-keycloak-db.sql

#### Запись нового main.py

/Users/dmitry/Downloads/ad-opa-demo-5/demo-api

scp -i ~/Downloads/id_rsa /Users/dmitry/Downloads/ad-opa-demo-5/demo-api/main.py user1@192.144.13.138:/home/user1/ad-opa-demo/demo-api/main.py

#### Настройка Клока
Откройте http://192.144.13.138:8081, логин admin/admin.
Create realm → имя demo → Create.
Сразу: Realm settings → General → Require SSL → None.
User federation → Add provider → ldap:
Vendor: Other (сразу, чтобы остальные поля подставились правильно)
Connection URL: ldap://ldap:389
Bind DN: cn=admin,dc=demo,dc=local
Bind Credential: AdminPass123!
Users DN: ou=people,dc=demo,dc=local
Username LDAP attribute: uid
RDN LDAP attribute: uid
UUID LDAP attribute: entryUUID
User object classes: inetOrgPerson, organizationalPerson
Edit mode: READ_ONLY
Test connection → Test authentication → Save → Synchronize all users.
Mappers → Add group-ldap-mapper (Name: group-mapper, Mapper Type: group-ldap-mapper):
LDAP Groups DN: ou=groups,dc=demo,dc=local
Group Name LDAP Attribute: cn
Group Object Classes: groupOfNames
Membership LDAP Attribute: member
Membership Attribute Type: DN
Save → Sync LDAP Groups To Keycloak.
Client demo-gateway (Direct access grants) + custom claim mappers (tenant_id, roles) — как в шагах 3.4–3.5 README.

Раз вы это уже проходили дважды — должно пойти быстро, минут за 5. Если где-то на этих шагах что-то не совпадёт с тем, что видите на экране — присылайте, разберёмся, как и раньше.





ssh -i ~/Downloads/id_rsa -L 8081:localhost:8081 user1@192.144.13.138

tail -f /var/log/apt/term.log

scp -i /путь/к/вашему/ключу.pem /путь/к/ad-opa-demo.zip user1@192.144.13.138:~/

scp -i /путь/к/вашему/ключу.pem /путь/к/docker-compose.yml user1@192.144.13.138:~/ad-opa-demo/docker-compose.yml

ls -la /home/user1/ad-opa-demo/ldap-bootstrap/01-tenants.ldif
cat /home/user1/ad-opa-demo/ldap-bootstrap/01-tenants.ldif



### Обмануть клок

ssh -L 8081:localhost:8081 user1@192.144.13.138

# 1. Установите зависимости
sudo apt install -y ca-certificates curl gnupg

# 2. Добавьте ключ Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 3. Добавьте репозиторий Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. Обновите и установите Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin



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




## 2. Установка на VM

```bash
# на свежей Ubuntu VM
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# перелогиниться, затем:
git clone https://github.com/dmitryimalkov/ad-opa-demo.git ad-opa-demo
cd ad-opa-demo
docker compose up -d
```

Проверить, что всё поднялось:
```bash
docker compose ps
```

## 3. Настройка Keycloak (один раз, через UI — 10 минут)

Откройте `http://192.144.13.138:8081`, логин `admin`/`admin`.

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

## 6. Быстрая проверка "что если RLS отключить" (опционально, для эффекта)

Чтобы наглядно показать разработчикам ЦЕННОСТЬ RLS — можно временно
подключиться под суперпользователем `postgres` (не `app_user`) и
выполнить `SELECT * FROM sales` без `SET app.tenant_id` — суперпользователь
по умолчанию игнорирует RLS, и будут видны строки обеих компаний.
Это хороший повод объяснить, почему в `docker-compose.yml` demo-api
специально подключается под ограниченным `app_user`, а не под `postgres`.
