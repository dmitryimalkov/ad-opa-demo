# Настройки Keycloak на демо-стенде — полный чек-лист

Отражает состояние на текущий момент диалога. Пункты с пометкой
⚠️ стоит перепроверить на VM — либо потому что мы наблюдали, что
настройка слетала при пересоздании контейнера, либо потому что
явного подтверждения выполнения в диалоге не было.

## 1. Инфраструктура (вне UI Keycloak, задаётся в docker-compose.yml)

| Параметр | Значение | Зачем |
|---|---|---|
| Образ | `quay.io/keycloak/keycloak:25.0.6` | Версия `25.0`/`25.0.1` содержит баг `invalid_grant` в `kcadm.sh` (issue #30866), исправлено в `25.0.2+` |
| Режим запуска | `start` (production), НЕ `start-dev` | `start-dev` хранит состояние в файловой H2-базе внутри контейнера — терялось при каждом пересоздании |
| Backend БД | PostgreSQL, база `keycloak` в том же контейнере `demo-postgres` (`KC_DB=postgres`) | Persistent volume `pgdata` — состояние переживает пересоздание контейнера Keycloak |
| Флаги команды | `--http-enabled=true --hostname-strict=false` | Production-режим по умолчанию требует HTTPS и настроенный hostname — отключено для демо без TLS |
| `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` | `admin` / `admin` | Бутстрап первого админа при пустой БД |
| Сервис `keycloak-init` | Одноразовый контейнер, `network_mode: service:keycloak` | Автоматически выставляет `sslRequired=NONE` для realm `master` сразу при старте — чтобы админка открывалась по `http://<IP>:8081` без SSH-туннеля |

## 2. Realm `master`

| Настройка | Значение | Статус |
|---|---|---|
| Require SSL | `None` | ✅ Выставляется автоматически сервисом `keycloak-init` при каждом старте стека |

## 3. Realm `demo` — общие настройки

| Настройка | Значение | Статус |
|---|---|---|
| Realm name | `demo` | ✅ Создан вручную |
| Require SSL | `None` | ⚠️ **Настраивается вручную, не автоматизировано.** Мы наблюдали, что при пересоздании Keycloak (или в других обстоятельствах) эта настройка слетала — последний раз ловили ошибку `HTTPS required` на `/portal`. Проверяйте после любого пересоздания контейнера `demo-keycloak`: **Realm settings → General → Require SSL → None** |
| Access Token Lifespan | `900` секунд (15 минут) | ⚠️ **Рекомендовано, но не подтверждено выполненным.** Команда для применения: `docker exec -it demo-keycloak /opt/keycloak/bin/kcadm.sh update realms/demo -s accessTokenLifespan=900` (после `kcadm config credentials` под `admin`). Согласовано по времени с TTL пароля Postgres из `/db-credentials` |

## 4. Realm `demo` — User Federation (LDAP)

Раздел **User federation** → провайдер типа `ldap`:

| Поле | Значение |
|---|---|
| Vendor | `Other` (НЕ Active Directory — при выборе AD подставляются неверные значения UUID/object classes) |
| Connection URL | `ldap://ldap:389` |
| Bind DN | `cn=admin,dc=demo,dc=local` |
| Bind Credential | `AdminPass123!` |
| Users DN | `ou=people,dc=demo,dc=local` |
| Username LDAP attribute | `uid` |
| RDN LDAP attribute | `uid` |
| UUID LDAP attribute | `entryUUID` (НЕ `objectGUID` — это для настоящего AD) |
| User object classes | `inetOrgPerson, organizationalPerson` (НЕ `person, organizationalPerson, user` — это набор под AD) |
| Edit mode | `READ_ONLY` |

**Mapper на этом провайдере** (вкладка Mappers):

| Поле | Значение |
|---|---|
| Name | `group-mapper` |
| Mapper Type | `group-ldap-mapper` |
| LDAP Groups DN | `ou=groups,dc=demo,dc=local` |
| Group Name LDAP Attribute | `cn` |
| Group Object Classes | `groupOfNames` |
| Membership LDAP Attribute | `member` |
| Membership Attribute Type | `DN` |

После настройки выполнялись: **Test connection** → **Test authentication** →
**Save** → **Synchronize all users** → **Sync LDAP Groups To Keycloak**.

## 5. Realm `demo` — Client `demo-gateway`

| Настройка | Значение |
|---|---|
| Client ID | `demo-gateway` |
| Client authentication | Off |
| Direct access grants | Включено (нужно для `curl`/`grant_type=password` и страницы `/portal`) |
| Standard flow | Не настраивался целенаправленно (оставался по умолчанию) — **полноценный Authorization Code flow с redirect URI НЕ реализован**, страница `/portal` использует упрощённый Direct Grant прямо из браузера |
| Web origins | `*` | Добавлено, чтобы браузерный JS на `/portal` (порт 8000) мог обращаться к Keycloak (порт 8081) без блокировки CORS |

**Mapper в Client scopes → `demo-gateway-dedicated`:**

| Поле | Значение |
|---|---|
| Name | `roles-mapper` |
| Mapper Type | `Group Membership` |
| Token Claim Name | `roles` |
| Full group path | Off (иначе в токене будет `/CompanyA-Analysts` с лишним слэшем) |

**Важно:** `tenant_id` в JWT **не приходит отдельным claim'ом** — он вообще
не настраивается в Keycloak. `demo-api` сам разбирает его из значения
`roles` (`CompanyA-Analysts` → `tenant_id=company_a`, `role=analyst`) —
см. функцию `extract_user_context` в `main.py`.

## 6. Что обсуждалось, но НЕ реализовано на стенде

Эти пункты фигурировали в разговоре как концепция/план, но реальных
действий в Keycloak по ним не выполнялось — не ищите эти настройки
на текущем стенде:

- **Realm `company-b-idp`** — второй realm, изображающий отдельный AD
  Company B, с LDAP-фильтром `(mail=*@company-b.demo)`
- **Identity Provider `company-b-sso`** внутри realm `demo` — OIDC-брокеринг
  на этот второй realm
- **Client `demo-platform-broker`** с Client authentication (секретом)
  для машинного обмена между двумя Keycloak
- **Hardcoded Attribute mapper** (`tenant_id: company_b`) и **Attribute
  Importer mapper** для ролей на стороне IdP

Это был план для сценария "много компаний, у каждой свой AD" — на
демо-стенде по-прежнему один LDAP с группами `CompanyA-*`/`CompanyB-*`.

## 7. Тестовые пользователи (из LDAP, видны в Keycloak после синхронизации)

| Пользователь | Группа в LDAP | Роль после разбора Gateway | Компания |
|---|---|---|---|
| alice | CompanyA-Analysts | analyst | company_a |
| bob | CompanyA-Admins | admin | company_a |
| carol | CompanyB-Analysts | analyst | company_b |
| dave | CompanyB-Viewers | viewer | company_b |

Пароль у всех: `Password123!`

## Рекомендация — что проверить прямо сейчас

Учитывая пометки ⚠️ выше, стоит зайти в Keycloak и вручную сверить:
1. Realm `demo` → Require SSL действительно `None`
2. Access Token Lifespan действительно `900`, а не значение по умолчанию (обычно `300`)

Если что-то из этого не совпадёт — не проблема стенда, просто ещё не
применяли эту конкретную настройку или она была сброшена ранее.
