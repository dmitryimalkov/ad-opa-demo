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
