-- Метаданные Airflow (история запусков DAG, Variables и т.д.) —
-- отдельная БД в том же Postgres, аналогично базе keycloak.

CREATE USER airflow WITH PASSWORD 'airflow_pass';
CREATE DATABASE airflow OWNER airflow;
\connect airflow
GRANT ALL ON SCHEMA public TO airflow;
