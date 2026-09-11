package platform.authz

test_analyst_reads_own_tenant_allowed {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "read",
        "resource": {"type": "sales_data", "tenant_id": "company_a"}
    }
}

test_analyst_cannot_read_other_tenant {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "read",
        "resource": {"type": "sales_data", "tenant_id": "company_b"}
    }
}

test_viewer_cannot_read_sales_data {
    not allow with input as {
        "user": {"tenant_id": "company_b", "roles": ["viewer"]},
        "action": "read",
        "resource": {"type": "sales_data", "tenant_id": "company_b"}
    }
}

test_admin_can_write_own_tenant {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["admin"]},
        "action": "write",
        "resource": {"type": "sales_data", "tenant_id": "company_a"}
    }
}

test_analyst_can_get_db_credentials {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "grant_direct_db_access",
        "resource": {"type": "database", "tenant_id": "company_a"}
    }
}

test_viewer_cannot_get_db_credentials {
    not allow with input as {
        "user": {"tenant_id": "company_b", "roles": ["viewer"]},
        "action": "grant_direct_db_access",
        "resource": {"type": "database", "tenant_id": "company_b"}
    }
}

test_cannot_get_db_credentials_for_other_tenant {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["admin"]},
        "action": "grant_direct_db_access",
        "resource": {"type": "database", "tenant_id": "company_b"}
    }
}

test_admin_can_view_audit_log {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["admin"]},
        "action": "view_audit_log",
        "resource": {"type": "audit_log", "tenant_id": "company_a"}
    }
}

test_analyst_cannot_view_audit_log {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "view_audit_log",
        "resource": {"type": "audit_log", "tenant_id": "company_a"}
    }
}

test_analyst_can_view_own_dag {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "airflow_dag_view",
        "resource": {"type": "airflow_dag", "tenant_id": "company_a"}
    }
}

test_analyst_cannot_view_other_tenant_dag {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "airflow_dag_view",
        "resource": {"type": "airflow_dag", "tenant_id": "company_b"}
    }
}

test_analyst_cannot_trigger_dag {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "airflow_dag_trigger",
        "resource": {"type": "airflow_dag", "tenant_id": "company_a"}
    }
}

test_admin_can_trigger_own_dag {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["admin"]},
        "action": "airflow_dag_trigger",
        "resource": {"type": "airflow_dag", "tenant_id": "company_a"}
    }
}

test_viewer_cannot_see_any_dag {
    not allow with input as {
        "user": {"tenant_id": "company_b", "roles": ["viewer"]},
        "action": "airflow_dag_view",
        "resource": {"type": "airflow_dag", "tenant_id": "company_b"}
    }
}

test_analyst_can_access_own_s3_bucket {
    allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "s3_access",
        "resource": {"type": "s3_bucket", "tenant_id": "company_a"}
    }
}

test_viewer_cannot_access_s3_bucket {
    not allow with input as {
        "user": {"tenant_id": "company_b", "roles": ["viewer"]},
        "action": "s3_access",
        "resource": {"type": "s3_bucket", "tenant_id": "company_b"}
    }
}

test_analyst_cannot_access_other_tenant_s3_bucket {
    not allow with input as {
        "user": {"tenant_id": "company_a", "roles": ["analyst"]},
        "action": "s3_access",
        "resource": {"type": "s3_bucket", "tenant_id": "company_b"}
    }
}
