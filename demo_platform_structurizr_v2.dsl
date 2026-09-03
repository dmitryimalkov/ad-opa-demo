workspace "Demo AuthN/AuthZ Stand v2" "Демо-стенд: AD/LDAP + Keycloak + OPA + Postgres (RLS двумя способами) + ClickHouse-аудит" {

    model {
        user = person "Пользователь компании" "Сотрудник Company A или Company B (Alice, Bob, Carol, Dave), логинится через свой LDAP-аккаунт"

        dbeaver = softwareSystem "DBeaver" "Внешний SQL-клиент на компьютере пользователя — НЕ часть платформы, использует прямое подключение к БД, минуя Gateway" {
            tags "External"
        }

        platform = softwareSystem "Demo Multi-tenant Platform" "AuthN/AuthZ демо-стенд: аутентификация через AD-совместимый каталог, авторизация через OPA, изоляция данных через RLS, полный аудит решений" {

            ldap = container "LDAP / AD" "Каталог пользователей и групп — эмуляция Active Directory" "OpenLDAP"

            keycloak = container "Keycloak" "OIDC-брокер: проверяет пароль через LDAP, выпускает JWT с tenant_id/roles. Production-режим, состояние в Postgres" "Keycloak 25, Java"

            opa = container "OPA" "Policy Decision Point: RBAC + строгая tenant-изоляция (Rego-политики), --watch авто-перезагрузка" "Open Policy Agent"

            gateway = container "Demo Gateway" "Проверяет JWT, спрашивает OPA, выставляет tenant_id для RLS, выдаёт self-service DB-credentials с TTL, отдаёт портал /portal и /audit-log" "FastAPI, Python"

            salesDb = container "Postgres: salesdb" "Данные продаж. ДВА независимых механизма RLS: 1) по сессионной переменной app.tenant_id (для Gateway) 2) по роли подключения + VALID UNTIL (для прямого доступа)" "PostgreSQL 16"

            keycloakDb = container "Postgres: keycloak db" "Конфигурация Keycloak — отдельная БД в том же экземпляре Postgres" "PostgreSQL 16"

            group "Логирование и аудит" {
                clickhouse = container "ClickHouse" "audit.audit_log — решения OPA (allow/deny) со всех эндпоинтов. audit.request_log — HTTP access log (латентность, включая неудачную аутентификацию, которая не доходит до OPA)" "ClickHouse 24.8"
            }
        }

        # --- связи: аутентификация и обычный путь через Gateway ---
        user -> keycloak "Логинится (username/password), получает JWT"
        user -> gateway "HTTP-запросы с Bearer JWT: /sales, /db-credentials, /audit-log, /portal"

        keycloak -> ldap "Читает пользователей и группы, проверяет пароль (LDAP bind)"
        keycloak -> keycloakDb "Хранит состояние realm/client/mappers"

        gateway -> keycloak "Проверяет подпись JWT через JWKS"
        gateway -> opa "Запрашивает allow/deny: read, write, grant_direct_db_access, view_audit_log"
        gateway -> salesDb "SET app.tenant_id + SELECT/INSERT (/sales); CREATE/ALTER ROLE ... VALID UNTIL (/db-credentials)"

        gateway -> clickhouse "ПИШЕТ: audit_log (каждое решение OPA) и request_log (каждый HTTP-запрос, включая 401 до OPA)"
        gateway -> clickhouse "ЧИТАЕТ: audit_log для /audit-log — только admin, с фильтром по своему tenant_id"

        # --- связи: прямой путь, минуя Gateway ---
        user -> dbeaver "Использует для прямых SQL-запросов (например, аналитика через привычный клиент)"
        dbeaver -> salesDb "Прямое SQL-подключение — LOGIN-роль, выданная через /db-credentials, RLS привязана К РОЛИ, доступ истекает по VALID UNTIL"
    }

    views {

        systemContext platform "Level1_Context" {
            include *
            autoLayout lr
            description "Level 1 — кто и что взаимодействует с платформой снаружи, включая внешний инструмент DBeaver"
        }

        container platform "Level2_Container" {
            include *
            autoLayout lr
            description "Level 2 — контейнеры платформы, два независимых пути изоляции (Gateway/OPA и прямой доступ), выделенный блок логирования"
        }

        styles {
            element "Person" {
                shape person
                background #08427b
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
        }
    }
}
