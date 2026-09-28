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
    # Сервисная роль для платформенной настройки Superset (заведение
    # Database-подключений, датасетов, дашбордов на этапе настройки
    # стенда) — нужен обзор bi_dashboard по ОБОИМ тенантам сразу,
    # остального не касается.
    "bi_admin": {
        "sales_data": set(),
        "database": set(),
        "audit_log": set(),
        "airflow_dag": set(),
        "airflow_variable": set(),
        "s3_bucket": set(),
        "bi_dashboard": {"bi_view"},
    },
}

# Роли, для которых tenant-изоляция намеренно не применяется —
# это служебные технические аккаунты, а не пользователи компаний.
service_roles := {"metadata_ingestion", "bi_admin"}

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
