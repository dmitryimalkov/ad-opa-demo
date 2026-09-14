workspace "Demo AuthN/AuthZ Stand v4" "Демо-стенд: AD/LDAP + Keycloak + OPA + Postgres (RLS двумя способами) + ClickHouse-аудит + Airflow (мультитенантный, через OPA) + MinIO (нативный LDAP)" {

    model {
        user = person "Пользователь компании" "Сотрудник Company A или Company B (Alice, Bob, Carol, Dave), логинится через свой LDAP-аккаунт"

        dbeaver = softwareSystem "DBeaver" "Внешний SQL-клиент на компьютере пользователя — НЕ часть платформы, прямое подключение к БД, минуя Gateway" {
            tags "External"
        }

        platform = softwareSystem "Demo Multi-tenant Platform" "AuthN/AuthZ демо-стенд: аутентификация через AD-совместимый каталог, авторизация через OPA, изоляция данных через RLS и живую проверку в Airflow, полный аудит решений" {

            ldap = container "LDAP / AD" "Каталог пользователей и групп — эмуляция Active Directory. groupOfNames/member (НЕ groupOfUniqueNames/uniqueMember — важно для интеграций)" "OpenLDAP"

            keycloak = container "Keycloak" "OIDC-брокер: проверяет пароль через LDAP, выпускает JWT с tenant_id/roles. Production-режим, состояние в Postgres" "Keycloak 25, Java"

            opa = container "OPA" "Policy Decision Point: RBAC + строгая tenant-изоляция (Rego-политики), --watch авто-перезагрузка. Единая точка решений для Gateway И Airflow" "Open Policy Agent"

            gateway = container "Demo Gateway" "Проверяет JWT, спрашивает OPA, выставляет tenant_id для RLS, выдаёт self-service DB-credentials с TTL, отдаёт портал /portal и /audit-log" "FastAPI, Python"

            salesDb = container "Postgres: salesdb" "Данные продаж. ДВА независимых механизма RLS: по сессионной переменной (Gateway) и по роли подключения + VALID UNTIL (прямой доступ)" "PostgreSQL 16"

            keycloakDb = container "Postgres: keycloak db" "Конфигурация Keycloak — отдельная БД в том же экземпляре Postgres" "PostgreSQL 16"

            airflowDb = container "Postgres: airflow db" "Метаданные Airflow (история запусков, Variables) — отдельная БД в том же Postgres" "PostgreSQL 16"

            airflow = container "Airflow" "Оркестрация датасетов/метаданных. Логин — LDAP (только пароль). Роль/tenant — ЖИВОЙ LDAP-поиск групп внутри Auth Manager (не memberof, не FAB role-sync). Изоляция DAG — через кастомный OpaFabAuthManager, спрашивающий OPA на каждое действие" "Airflow 3.3, scheduler+dag-processor+api-server"

            minio = container "MinIO" "S3-совместимое хранилище датасетов (bucket 'datasets', разделение по префиксу company_a/ и company_b/). Аутентификация — ЖИВОЙ AssumeRoleWithLDAPIdentity (встроенный STS MinIO). Привязка IAM-политик к LDAP-группам — СТАТИЧЕСКАЯ, прописана в init-скрипте вручную, зеркалирует ролевую матрицу OPA, но БЕЗ реального вызова OPA API (известный технический долг). Viewer получает отказ уже на этапе входа — нет ни одной привязанной политики" "MinIO"

            group "Логирование и аудит" {
                clickhouse = container "ClickHouse" "audit.audit_log — решения OPA от Gateway. audit.request_log — HTTP access log. ПРИМЕЧАНИЕ: решения OPA от Airflow И от MinIO сюда пока НЕ пишутся (известное ограничение)" "ClickHouse 24.8"
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
        gateway -> clickhouse "ПИШЕТ audit_log/request_log; ЧИТАЕТ audit_log для /audit-log (только admin, tenant-фильтр)"

        # --- связи: прямой путь к БД, минуя Gateway ---
        user -> dbeaver "Использует для прямых SQL-запросов"
        dbeaver -> salesDb "Прямое SQL-подключение — LOGIN-роль, выданная через /db-credentials, RLS привязана К РОЛИ, доступ истекает по VALID UNTIL"

        # --- связи: Airflow (мультитенантный, живой OPA на каждое действие) ---
        user -> airflow "Логинится напрямую (LDAP пароль), просматривает/запускает свои DAG"
        airflow -> ldap "Проверка пароля (FAB AUTH_LDAP) + ЖИВОЙ поиск групп (member=<DN>) внутри OpaFabAuthManager"
        airflow -> opa "is_authorized_dag / get_authorized_dag_ids / is_authorized_variable — НА КАЖДОЕ действие, не только при провижининге"
        airflow -> airflowDb "Хранит DAG runs, Variables, состояние FAB (роли Public/Viewer/User/Op/Admin — не используются для решений, только LDAP+OPA)"

        # --- связи: MinIO (нативный LDAP STS, OPA НЕ вызывается в реальном времени) ---
        user -> minio "Логинится напрямую LDAP-паролем (AssumeRoleWithLDAPIdentity), получает временные S3-credentials, читает/пишет свой префикс"
        minio -> ldap "Проверка пароля + ЖИВОЙ поиск групп (member=<DN>) — то же, что и Airflow, но силами встроенного STS MinIO, не нашего кода"
    }

    views {

        systemContext platform "Level1_Context" {
            include *
            autoLayout lr
            description "Level 1 — кто и что взаимодействует с платформой снаружи, включая внешний DBeaver"
        }

        container platform "Level2_Container" {
            include *
            autoLayout lr
            description "Level 2 — контейнеры платформы: четыре независимых пути изоляции (Gateway/OPA живой, прямой доступ к БД статический, Airflow/OPA живой, MinIO/LDAP статический), выделенный блок логирования"
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
