"""
superset_config.py — логин через LDAP штатным механизмом Flask-
AppBuilder (AUTH_TYPE=AUTH_LDAP), та же нативная схема, что у Airflow/
Postgres/ClickHouse/MinIO на этом стенде. Проверки доступа к
дашбордам/датасетам — через OpaSupersetSecurityManager (см.
opa_security_manager.py), который на каждое обращение спрашивает OPA.
"""

import os

from flask_appbuilder.security.manager import AUTH_LDAP

from opa_security_manager import OpaSupersetSecurityManager

# --- Секрет и своя метаданные-БД Superset (НЕ salesdb — там только
# бизнес-данные тенантов; Superset хранит дашборды/датасеты/юзеров в
# отдельной БД superset_meta, см. шаг создания роли/БД в Postgres) ---
SECRET_KEY = os.environ.get(
    "SUPERSET_SECRET_KEY", "M7GHLaR1aP7NcVdf8dL7mUalxsADw6T0Ljryy9C4iGI"
)
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SUPERSET_METADATA_DB_URI",
    "postgresql+psycopg2://superset_meta:vv-QkjoEUpWGDZNhIN69KFUG@postgres:5432/superset_meta",
)

# --- LDAP-логин: те же параметры, что в webserver_config.py у Airflow ---
AUTH_TYPE = AUTH_LDAP
AUTH_LDAP_SERVER = "ldap://ldap:389"
AUTH_LDAP_SEARCH = "ou=people,dc=demo,dc=local"
AUTH_LDAP_UID_FIELD = "uid"
AUTH_LDAP_BIND_USER = "cn=admin,dc=demo,dc=local"
AUTH_LDAP_BIND_PASSWORD = "AdminPass123!"

# Автосоздание пользователя Superset при первом успешном LDAP-логине —
# без этого пришлось бы заранее заводить каждого через superset fab
# create-user. Базовая FAB-роль тут почти не важна: реальные решения
# по дашбордам/датасетам принимает OpaSupersetSecurityManager, а не
# эта роль сама по себе.
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Gamma"

# Кастомный security manager — единая точка, где решения по
# dashboard/dataset идут через OPA (см. opa_security_manager.py).
CUSTOM_SECURITY_MANAGER = OpaSupersetSecurityManager

# Публичный доступ без логина выключен — вход только через LDAP.
PUBLIC_ROLE_LIKE = None
