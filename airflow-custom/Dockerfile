FROM apache/airflow:3.3.1-python3.12

USER root
# python-ldap (нужен для FAB AUTH_LDAP) компилируется из исходников —
# без этих системных библиотек pip install падает с ошибкой сборки.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libldap2-dev libsasl2-dev gcc \
    && rm -rf /var/lib/apt/lists/*

USER airflow
# В Airflow 3.x FAB — отдельный устанавливаемый провайдер, а не часть ядра.
# python-ldap указан явно (не только через extra [ldap]) — он нужен ещё и
# напрямую нашему opa_auth_manager.py для живого поиска групп.
RUN pip install --no-cache-dir "apache-airflow-providers-fab[ldap]" "python-ldap"
