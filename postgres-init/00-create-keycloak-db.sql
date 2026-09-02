-- Отдельная БД для состояния Keycloak (realm, пользователи, клиенты, mappers).
-- Хранится физически в том же Postgres-контейнере, что и sales — это нормально
-- для демо-стенда, но НЕ для прода (там Keycloak лучше держать в собственном
-- экземпляре БД, отдельном от бизнес-данных).

CREATE USER keycloak WITH PASSWORD 'keycloak_pass';
CREATE DATABASE keycloak OWNER keycloak;

-- В PostgreSQL 15+ права CREATE на схему public по умолчанию не выдаются
-- никому, кроме владельца схемы (а им остаётся postgres, даже если keycloak
-- стал владельцем самой БД). Без этой строки Keycloak не сможет создать
-- свои таблицы при первом запуске (Liquibase migration упадёт с permission denied).
\connect keycloak
GRANT ALL ON SCHEMA public TO keycloak;
