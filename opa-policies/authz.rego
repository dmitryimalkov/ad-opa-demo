package platform.authz

import future.keywords.in

default allow = false

role_permissions := {
    "admin":   {"sales_data": {"read", "write"}, "database": {"grant_direct_db_access"}},
    "analyst": {"sales_data": {"read"},           "database": {"grant_direct_db_access"}},
    "viewer":  {"sales_data": set(),              "database": set()}
}

rbac_allow {
    some role in input.user.roles
    input.action in role_permissions[role][input.resource.type]
}

same_tenant {
    input.user.tenant_id == input.resource.tenant_id
}

allow {
    rbac_allow
    same_tenant
}

# Явные причины отказа — показываем их разработчикам на демо,
# чтобы было видно, ПОЧЕМУ именно запрещено
deny_reason["cross_tenant_access"] {
    not same_tenant
}

deny_reason["role_not_permitted"] {
    same_tenant
    not rbac_allow
}
