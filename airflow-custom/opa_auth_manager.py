"""
OpaFabAuthManager — расширяет стандартный FabAuthManager (логин через
LDAP — проверка пароля, сессии — штатный механизм Flask-AppBuilder),
но переопределяет РЕШЕНИЯ ПО АВТОРИЗАЦИИ для DAG и Variables так, чтобы
они спрашивали НАШ OPA на каждое действие.

Группы пользователя мы НЕ берём из FAB Role (это потребовало бы
memberof-overlay на LDAP-сервере, что оказалось ненадёжным — см.
комментарий в webserver_config.py) — вместо этого делаем живой LDAP-
поиск "member=<DN пользователя>" прямо здесь, тем же способом, что мы
использовали весь проект через ldapsearch, и который использует
Keycloak в своём group-ldap-mapper.

ВАЖНО: это самая экспериментальная часть стенда. API кастомных Auth
Manager в Airflow 3.x относительно новый и менялся даже в последних
минорных версиях. Если что-то здесь не заработает с первого раза —
смотрите docker logs demo-airflow, там будет точный traceback с тем,
какой метод/сигнатура не совпали.
"""

import os
import httpx
import ldap

from airflow.providers.fab.auth_manager.fab_auth_manager import FabAuthManager

OPA_URL = os.environ.get("OPA_URL", "http://opa:8181/v1/data/platform/authz")
LDAP_URI = os.environ.get("LDAP_URI", "ldap://ldap:389")
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "cn=admin,dc=demo,dc=local")
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "AdminPass123!")
LDAP_PEOPLE_DN = os.environ.get("LDAP_PEOPLE_DN", "ou=people,dc=demo,dc=local")
LDAP_GROUPS_DN = os.environ.get("LDAP_GROUPS_DN", "ou=groups,dc=demo,dc=local")

# Та же логика разбора роли, что в demo-api/main.py — специально
# продублирована здесь (не общий модуль), чтобы Airflow и Gateway
# были полностью независимы друг от друга по коду и деплою.
TENANT_MAP = {"CompanyA": "company_a", "CompanyB": "company_b"}
ROLE_MAP = {"Analysts": "analyst", "Admins": "admin", "Viewers": "viewer"}

# Airflow передаёт HTTP-подобные методы (GET/POST/DELETE/MENU) —
# переводим их в те же по духу действия, что используются в audit_log.
METHOD_ACTION_MAP = {"GET": "view", "POST": "trigger", "PUT": "trigger", "DELETE": "delete", "MENU": "view"}


DEBUG_LOG_PATH = "/tmp/opa_auth_manager_debug.log"


def _debug(msg):
    """Файловый лог вместо print — на случай если stdout дочерних
    процессов Airflow (dag-processor/api-server воркеры) не долетает
    до docker logs так, как мы ожидаем."""
    try:
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _fetch_ldap_groups(username):
    """Живой LDAP-поиск: в каких группах состоит пользователь, через
    (member=<DN>) на стороне группы — без memberof-overlay."""
    if not username:
        _debug(f"_fetch_ldap_groups: username пустой/None, возвращаю []")
        return []
    user_dn = f"uid={username},{LDAP_PEOPLE_DN}"
    try:
        conn = ldap.initialize(LDAP_URI)
        conn.simple_bind_s(LDAP_BIND_DN, LDAP_BIND_PASSWORD)
        results = conn.search_s(
            LDAP_GROUPS_DN, ldap.SCOPE_SUBTREE, f"(member={user_dn})", ["cn"]
        )
        conn.unbind_s()
        groups = []
        for _dn, attrs in results:
            cn_values = attrs.get("cn", [])
            if cn_values:
                groups.append(cn_values[0].decode() if isinstance(cn_values[0], bytes) else cn_values[0])
        _debug(f"_fetch_ldap_groups: username={username!r} user_dn={user_dn!r} groups={groups}")
        return groups
    except Exception as e:
        _debug(f"_fetch_ldap_groups: ОШИБКА для username={username!r}: {e}")
        return []


def _extract_tenant_and_roles(user):
    """Разбирает СЫРЫЕ имена LDAP-групп (CompanyA-Analysts и т.п.)
    в tenant_id + нормализованные роли — та же логика, что
    extract_user_context в demo-api."""
    tenant_id = None
    roles = []
    if user is None:
        _debug("_extract_tenant_and_roles: user is None")
        return tenant_id, roles
    username = getattr(user, "username", None)
    _debug(f"_extract_tenant_and_roles: user={user!r} type={type(user)} username={username!r}")
    for group_name in _fetch_ldap_groups(username):
        parts = group_name.split("-", 1)
        if len(parts) != 2:
            continue
        company_part, role_part = parts
        if company_part in TENANT_MAP:
            tenant_id = TENANT_MAP[company_part]
        if role_part in ROLE_MAP:
            roles.append(ROLE_MAP[role_part])
    _debug(f"_extract_tenant_and_roles: итог tenant_id={tenant_id!r} roles={roles}")
    return tenant_id, roles


def _dag_tenant(dag_id):
    """DAG называется как company_a__load_dataset — префикс до '__'
    это tenant_id уже в нужном формате, без доп. маппинга."""
    if dag_id and "__" in dag_id:
        return dag_id.split("__", 1)[0]
    return None


def _check_opa(tenant_id, roles, action, resource_type, resource_tenant_id):
    payload = {
        "input": {
            "user": {"tenant_id": tenant_id, "roles": roles},
            "action": action,
            "resource": {"type": resource_type, "tenant_id": resource_tenant_id},
        }
    }
    try:
        resp = httpx.post(OPA_URL, json=payload, timeout=5.0)
        resp.raise_for_status()
        allow = bool(resp.json().get("result", {}).get("allow"))
        _debug(f"_check_opa: payload={payload} -> allow={allow}")
        return allow
    except Exception as e:
        # Fail-closed: если OPA недоступен — НЕ пускаем, а не наоборот.
        _debug(f"_check_opa: ОШИБКА вызова OPA, отказываю: {e}")
        return False


class OpaFabAuthManager(FabAuthManager):

    def __init__(self, *args, **kwargs):
        _debug(f"OpaFabAuthManager.__init__ вызван, args={args} kwargs={kwargs}")
        super().__init__(*args, **kwargs)

    def is_authorized_dag(self, *, method, access_entity=None, details=None, user=None) -> bool:
        _debug(f"is_authorized_dag ВЫЗВАН: method={method!r} details={details!r} user_in={user!r}")
        user = user or self.get_user()
        tenant_id, roles = _extract_tenant_and_roles(user)
        dag_id = getattr(details, "id", None) if details else None
        resource_tenant = _dag_tenant(dag_id) if dag_id else tenant_id
        action = METHOD_ACTION_MAP.get(method, "view")
        return _check_opa(tenant_id, roles, f"airflow_dag_{action}", "airflow_dag", resource_tenant)

    def get_authorized_dag_ids(self, *, user=None, method="GET", session=None):
        """
        КЛЮЧЕВОЙ метод — именно его Airflow вызывает для формирования
        списка DAG в UI. filter_authorized_dag_ids (ниже) в
        FabAuthManager НЕ используется для этого — у FAB здесь другой
        путь (get_authorized_dag_ids), который мы и переопределяем.
        """
        user = user or self.get_user()
        _debug(f"get_authorized_dag_ids: method={method!r} user_in={user!r}")
        tenant_id, roles = _extract_tenant_and_roles(user)
        action = METHOD_ACTION_MAP.get(method, "view")

        from airflow.models.dag import DagModel
        from airflow.utils.session import create_session

        with create_session() as db_session:
            all_dag_ids = [row[0] for row in db_session.query(DagModel.dag_id).all()]
        _debug(f"get_authorized_dag_ids: все известные dag_ids={all_dag_ids}")

        allowed = set()
        for dag_id in all_dag_ids:
            resource_tenant = _dag_tenant(dag_id) or tenant_id
            if _check_opa(tenant_id, roles, f"airflow_dag_{action}", "airflow_dag", resource_tenant):
                allowed.add(dag_id)
        _debug(f"get_authorized_dag_ids: итог allowed={allowed}")
        return allowed

    def filter_authorized_dag_ids(self, *, dag_ids, user=None, method="GET", team_name=None):
        user = user or self.get_user()
        _debug(f"filter_authorized_dag_ids: dag_ids={dag_ids} method={method!r} user_in={user!r}")
        tenant_id, roles = _extract_tenant_and_roles(user)
        action = METHOD_ACTION_MAP.get(method, "view")
        allowed = set()
        for dag_id in dag_ids:
            resource_tenant = _dag_tenant(dag_id) or tenant_id
            if _check_opa(tenant_id, roles, f"airflow_dag_{action}", "airflow_dag", resource_tenant):
                allowed.add(dag_id)
        _debug(f"filter_authorized_dag_ids: итог allowed={allowed}")
        return allowed

    def is_authorized_variable(self, *, method, details=None, user=None) -> bool:
        user = user or self.get_user()
        tenant_id, roles = _extract_tenant_and_roles(user)
        var_key = getattr(details, "key", None) if details else None
        resource_tenant = _dag_tenant(var_key) if var_key else tenant_id
        action = METHOD_ACTION_MAP.get(method, "view")
        return _check_opa(tenant_id, roles, f"airflow_variable_{action}", "airflow_variable", resource_tenant)
