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
