#!/bin/bash
# Preflight-проверка стенда перед демонстрацией.
# Запускать на VM, из папки проекта: bash preflight-check.sh
#
# Чинит все известные нестабильные места, с которыми мы уже
# сталкивались: рассинхронизация паролей ролей в Postgres (возникает
# из-за того, что POSTGRES_PASSWORD в docker-compose применяется
# ТОЛЬКО при первой инициализации пустого volume — дальнейшие правки
# compose-файла на уже существующий volume не влияют), и настройки
# realm demo (Require SSL, Access Token Lifespan), которые слетали
# при пересозданиях Keycloak.

set -e
echo "===================================="
echo "Preflight-проверка демо-стенда"
echo "===================================="

echo ""
echo "[1/6] Все ли контейнеры подняты"
docker compose ps

echo ""
echo "[2/6] Проверка пароля postgres (суперпользователь, нужен для /db-credentials)"
CHECK=$(docker exec demo-api python -c "
import psycopg2, sys
try:
    psycopg2.connect('postgresql://postgres:postgres@postgres:5432/salesdb').close()
    print('OK')
except Exception:
    print('FAIL')
" 2>/dev/null || echo "FAIL")

if [ "$CHECK" == "OK" ]; then
    echo "OK: пароль postgres корректен"
else
    echo "ИСПРАВЛЯЮ: пароль postgres не совпадает, сбрасываю..."
    docker exec demo-postgres psql -U postgres -d postgres -c "ALTER ROLE postgres WITH PASSWORD 'postgres';"
    echo "Готово"
fi

echo ""
echo "[3/6] Проверка пароля keycloak (роль БД для состояния Keycloak)"
CHECK=$(docker exec demo-api python -c "
import psycopg2, sys
try:
    psycopg2.connect('postgresql://keycloak:keycloak_pass@postgres:5432/keycloak').close()
    print('OK')
except Exception:
    print('FAIL')
" 2>/dev/null || echo "FAIL")

NEEDS_KEYCLOAK_RESTART=0
if [ "$CHECK" == "OK" ]; then
    echo "OK: пароль keycloak корректен"
else
    echo "ИСПРАВЛЯЮ: пароль keycloak не совпадает, сбрасываю..."
    docker exec demo-postgres psql -U postgres -d postgres -c "ALTER ROLE keycloak WITH PASSWORD 'keycloak_pass';"
    NEEDS_KEYCLOAK_RESTART=1
    echo "Готово"
fi

if [ "$NEEDS_KEYCLOAK_RESTART" == "1" ]; then
    echo "Перезапускаю demo-keycloak, чтобы подхватил рабочее соединение..."
    docker compose restart keycloak
    echo "Жду 25 секунд, пока Keycloak полностью поднимется..."
    sleep 25
fi

echo ""
echo "[4/6] Синхронизация настроек realm demo (Require SSL, Access Token Lifespan)"
docker exec demo-keycloak /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master --user admin --password admin > /dev/null
docker exec demo-keycloak /opt/keycloak/bin/kcadm.sh update realms/demo \
    -s sslRequired=NONE -s accessTokenLifespan=900 > /dev/null
echo "OK: Require SSL=None, Access Token Lifespan=900 применены (идемпотентно, безопасно гонять каждый раз)"

echo ""
echo "[5/6] Сквозная проверка: логин -> /whoami -> /sales"
TOKEN_ALICE=$(curl -s -X POST "http://localhost:8081/realms/demo/protocol/openid-connect/token" \
    -d "client_id=demo-gateway" -d "grant_type=password" \
    -d "username=alice" -d "password=Password123!" | jq -r .access_token)

if [ "$TOKEN_ALICE" == "null" ] || [ -z "$TOKEN_ALICE" ]; then
    echo "ОШИБКА: не удалось получить токен для alice. Смотрите вручную:"
    echo "  docker logs demo-keycloak --tail 50"
    exit 1
fi
echo "OK: токен получен"

SALES_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/sales -H "Authorization: Bearer $TOKEN_ALICE")
if [ "$SALES_STATUS" == "200" ]; then
    echo "OK: /sales отвечает 200"
else
    echo "ОШИБКА: /sales вернул код $SALES_STATUS. Смотрите вручную:"
    echo "  docker logs demo-api --tail 50"
    exit 1
fi

echo ""
echo "[6/7] Проверка ClickHouse (аудит-лог)"
CH_CHECK=$(docker exec demo-clickhouse clickhouse-client --password clickhouse_pass -q "SELECT 1" 2>/dev/null || echo "FAIL")
if [ "$CH_CHECK" == "1" ]; then
    echo "OK: ClickHouse отвечает"
else
    echo "ПРЕДУПРЕЖДЕНИЕ: ClickHouse не отвечает — аудит-лог работать не будет,"
    echo "но остальной функционал (/sales, /db-credentials) не пострадает (best-effort логирование)"
fi

echo ""
echo "[7/7] Тесты OPA-политик"
docker exec demo-opa opa test /policies -v | tail -6

echo ""
echo "===================================="
echo "Preflight-проверка завершена успешно."
echo "Стенд готов к демонстрации."
echo "===================================="
