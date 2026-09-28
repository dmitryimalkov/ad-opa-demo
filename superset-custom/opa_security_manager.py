"""
OpaSupersetSecurityManager — расширяет стандартный SupersetSecurityManager.
Логин — штатный Flask-AppBuilder механизм через AUTH_TYPE=AUTH_LDAP
(проверка пароля, сессии — как обычно). РЕШЕНИЯ ПО АВТОРИЗАЦИИ на
дашборды/датасеты переопределены так, чтобы они спрашивали НАШ OPA на
каждое обращение — тот же принцип, что OpaFabAuthManager в Airflow
(airflow-custom/opa_auth_manager.py), не статичный маппинг LDAP-группы
на роль Superset один раз при логине.

LDAP-поиск групп сознательно продублирован из opa_auth_manager.py, а
не вынесен в общий модуль — тот же принцип независимости сервисов
друг от друга, что и в остальном проекте (у Superset и Airflow разные
жизненные циклы деплоя, общий модуль означал бы их связать).

Соглашение об имени дашборда/датасета: "<tenant_id>__<name>", в
точности как "<tenant_id>__load_dataset" у DAG — из него достаётся
tenant_id для запроса в OPA, без отдельного маппинга.

Изоляция на уровне СТРОК данных обеспечена отдельно, через Postgres
RLS: у company_a__* датасетов подключение идёт под tenant_company_a_role,
у company_b__* — под tenant_company_b_role (см. два Database-подключения
company_a_salesdb/company_b_salesdb). Эта проверка — второй, независимый
слой: даже без разделения по ролям БД она не даст открыть чужой дашборд
или датасет через UI/API Superset.

ВАЖНО (как и в opa_auth_manager.py): это экспериментальная часть —
методы SupersetSecurityManager, которые тут переопределены
(raise_for_dashboard_access, can_access_dashboard, raise_for_access),
могут отличаться по сигнатуре между версиями Superset. Если при
первом запуске что-то упадёт — смотрите `docker logs demo-superset`,
там будет точный traceback с тем, какой метод/аргумент не совпал.
"""

import os

import httpx
import ldap

from superset.security import SupersetSecurityManager

OPA_URL = os.environ.get("OPA_URL", "http://opa:8181/v1/data/platform/authz")
LDAP_URI = os.environ.get("LDAP_URI", "ldap://ldap:389")
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "cn=admin,dc=demo,dc=local")
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "AdminPass123!")
LDAP_PEOPLE_DN = os.environ.get("LDAP_PEOPLE_DN", "ou=people,dc=demo,dc=local")
LDAP_GROUPS_DN = os.environ.get("LDAP_GROUPS_DN", "ou=groups,dc=demo,dc=local")

# Та же схема разбора LDAP-группы, что в opa_auth_manager.py:
# "CompanyA-Analysts" -> tenant_id="company_a", role="analyst".
TENANT_MAP = {"CompanyA": "company_a", "CompanyB": "company_b"}
ROLE_MAP = {"Analysts": "analyst", "Admins": "admin", "Viewers": "viewer", "BiAdmin": "bi_admin"}

# Physical-датасеты в этой версии Superset нельзя переименовать через
# UI (поле "Name" отдельно от table_name просто отсутствует в форме
# редактирования) — так что для ДАТАСЕТОВ тенант определяем не по
# соглашению об имени "<tenant>__...", а по тому, к какому
# Database-подключению они принадлежат: у company_a_salesdb/
# company_b_salesdb название подключения уже однозначно говорит,
# чей это тенант. Дашборды по-прежнему используют префикс в title
# (dashboard_title редактируется свободно, ограничений интерфейса нет).
DB_NAME_TENANT_MAP = {"company_a_salesdb": "company_a", "company_b_salesdb": "company_b"}

DEBUG_LOG_PATH = "/tmp/opa_security_manager_debug.log"


def _debug(msg):
    try:
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _fetch_ldap_groups(username):
    if not username:
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
        _debug(f"_fetch_ldap_groups: username={username!r} groups={groups}")
        return groups
    except Exception as e:
        _debug(f"_fetch_ldap_groups: ОШИБКА для username={username!r}: {e}")
        return []


def _extract_tenant_and_roles(username):
    tenant_id = None
    roles = []
    for group_name in _fetch_ldap_groups(username):
        parts = group_name.split("-", 1)
        if len(parts) != 2:
            continue
        company_part, role_part = parts
        if company_part in TENANT_MAP:
            tenant_id = TENANT_MAP[company_part]
        if role_part in ROLE_MAP:
            roles.append(ROLE_MAP[role_part])
    _debug(f"_extract_tenant_and_roles: username={username!r} -> tenant_id={tenant_id!r} roles={roles}")
    return tenant_id, roles


def _tenant_from_name(name):
    if name and "__" in name:
        return name.split("__", 1)[0]
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
        # Fail-closed — как и в Airflow: если OPA недоступен, не пускаем.
        _debug(f"_check_opa: ОШИБКА вызова OPA, отказываю: {e}")
        return False


class OpaSupersetSecurityManager(SupersetSecurityManager):

    def _opa_allows_resource(self, resource_name):
        """resource_name — dashboard_title или table_name/имя датасета.
        Без префикса "<tenant>__" считаем ресурс вне периметра этой
        проверки (общесистемные объекты Superset) и отдаём решение
        штатному FAB-механизму (super()...), а не блокируем вслепую."""
        tenant = _tenant_from_name(resource_name)
        if tenant is None:
            return True
        user = self.get_user()
        username = getattr(user, "username", None)
        tenant_id, roles = _extract_tenant_and_roles(username)
        return _check_opa(tenant_id, roles, "bi_view", "bi_dashboard", tenant)

    def raise_for_dashboard_access(self, dashboard):
        """Дёргается при открытии конкретного дашборда (view/API)."""
        if not self._opa_allows_resource(getattr(dashboard, "dashboard_title", None)):
            from superset.dashboards.exceptions import DashboardAccessDeniedError
            raise DashboardAccessDeniedError()
        super().raise_for_dashboard_access(dashboard)

    def can_access_dashboard(self, dashboard):
        """Дёргается при построении СПИСКА дашбордов (/dashboard/list/,
        API listing) — без переопределения этого метода чужие дашборды
        были бы не видны только при попытке открыть, но всё ещё
        отображались бы в общем списке."""
        if not self._opa_allows_resource(getattr(dashboard, "dashboard_title", None)):
            return False
        return super().can_access_dashboard(dashboard)

    def _opa_allows_datasource(self, datasource):
        """Тенант датасета — сперва пробуем по префиксу имени (на случай
        если его всё же переименуют в "<tenant>__..."), а если префикса
        нет — по имени Database-подключения (DB_NAME_TENANT_MAP)."""
        table_name = getattr(datasource, "table_name", None) or getattr(datasource, "name", None)
        tenant = _tenant_from_name(table_name)
        if tenant is None:
            db_name = getattr(getattr(datasource, "database", None), "database_name", None)
            tenant = DB_NAME_TENANT_MAP.get(db_name)
        if tenant is None:
            # Ни по имени, ни по подключению не определили тенант -
            # ресурс вне периметра этой проверки, отдаём штатному FAB.
            return True
        user = self.get_user()
        username = getattr(user, "username", None)
        tenant_id, roles = _extract_tenant_and_roles(username)
        return _check_opa(tenant_id, roles, "bi_view", "bi_dashboard", tenant)

    def raise_for_access(self, *args, datasource=None, **kwargs):
        """Дёргается при обращении к датасету — как из чарта/дашборда,
        так и напрямую из SQL Lab (если он включён)."""
        if datasource is not None:
            if not self._opa_allows_datasource(datasource):
                from superset.exceptions import SupersetSecurityException
                raise SupersetSecurityException(
                    "Доступ к датасету другого тенанта запрещён OPA (bi_dashboard/same_tenant)"
                )
        super().raise_for_access(*args, datasource=datasource, **kwargs)
