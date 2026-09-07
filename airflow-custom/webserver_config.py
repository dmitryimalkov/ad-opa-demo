"""
Конфигурация Flask-AppBuilder (веб-слой Airflow) — логин напрямую
через наш LDAP (проверка пароля), той же схемой "нативная LDAP-
авторизация", что мы уже делали для Postgres/ClickHouse.

Группы/роли пользователя здесь НЕ читаем (без memberof-overlay это
ненадёжно и специфично под схему LDAP-сервера) — вместо этого
opa_auth_manager.py сам делает живой LDAP-поиск "member=<DN>" на
каждую проверку, тем же способом, что мы использовали весь проект
через ldapsearch. Здесь LDAP отвечает только за "это точно Alice, и
пароль верный" — ни за что больше.
"""

from flask_appbuilder.security.manager import AUTH_LDAP

AUTH_TYPE = AUTH_LDAP

AUTH_LDAP_SERVER = "ldap://ldap:389"
AUTH_LDAP_SEARCH = "ou=people,dc=demo,dc=local"
AUTH_LDAP_UID_FIELD = "uid"
AUTH_LDAP_BIND_USER = "cn=admin,dc=demo,dc=local"
AUTH_LDAP_BIND_PASSWORD = "AdminPass123!"

AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"
