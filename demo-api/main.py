"""
Демо-Gateway для стенда AD + Keycloak + OPA + Postgres RLS.

Показывает ровно тот flow, что на диаграмме:
1. Извлекаем JWT из заголовка Authorization.
2. Валидируем подпись через JWKS Keycloak.
3. Достаём tenant_id и roles ИЗ ТОКЕНА (не из query/body).
4. Зовём OPA: allow/deny.
5. Если allow — открываем сессию в Postgres и делаем
   SET app.tenant_id = <из токена> перед запросом (RLS доделает остальное).
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
import httpx
import jwt
from jwt import PyJWKClient
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
import psycopg2
from psycopg2 import sql

app = FastAPI(title="Demo Gateway (AD + OPA + RLS)")

OPA_URL = os.environ["OPA_URL"]
DB_DSN = os.environ["DB_DSN"]
ADMIN_DB_DSN = os.environ["ADMIN_DB_DSN"]
KEYCLOAK_REALM_URL = os.environ["KEYCLOAK_REALM_URL"]

# Единый TTL для ВСЕХ выдаваемых доступов платформы — JWT (настраивается
# отдельно в Keycloak, см. README), пароль от Postgres (эта константа),
# и presigned URL для S3 (когда будет реализован — тоже 15 минут).
# Согласованность важна: разные TTL для разных механизмов доступа
# создают путаницу и самое слабое звено становится реальным сроком
# жизни утечки, даже если остальные компоненты были короче.
CREDENTIAL_TTL_MINUTES = 15

# Соответствие tenant_id -> групповая роль в Postgres с RLS-политикой,
# привязанной именно к роли (см. postgres-init/02-tenant-roles.sql)
TENANT_ROLE_MAP = {"company_a": "tenant_company_a_role", "company_b": "tenant_company_b_role"}

# Публичные ключи Keycloak для проверки подписи JWT (JWKS)
_jwk_client = PyJWKClient(f"{KEYCLOAK_REALM_URL}/protocol/openid-connect/certs")


def extract_user_context(authorization: str) -> dict:
    """Проверяет JWT и достаёт tenant_id/roles из claims, выданных Keycloak."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience="account",
            options={"verify_aud": False},  # для демо; в проде — проверять audience
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Группы в LDAP названы так: "CompanyA-Analysts", "CompanyB-Viewers" и т.д.
    # Отдельного атрибута tenant_id в LDAP нет — вся нужная информация уже
    # закодирована прямо в названии группы, поэтому разбираем её здесь,
    # а не через дополнительный custom-атрибут в Keycloak.
    TENANT_MAP = {"CompanyA": "company_a", "CompanyB": "company_b"}
    ROLE_MAP = {"Analysts": "analyst", "Admins": "admin", "Viewers": "viewer"}

    raw_groups = claims.get("roles", [])  # это claim "roles" из Group Membership mapper
    tenant_id = None
    roles = []
    for group_name in raw_groups:
        parts = group_name.split("-", 1)
        if len(parts) != 2:
            continue  # группа не по нашему шаблону — пропускаем
        company_part, role_part = parts
        if company_part in TENANT_MAP:
            tenant_id = TENANT_MAP[company_part]  # предполагаем, что пользователь в одном tenant
        if role_part in ROLE_MAP:
            roles.append(ROLE_MAP[role_part])

    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Token has no tenant_id claim — check Keycloak group mapper",
        )

    return {"tenant_id": tenant_id, "roles": roles, "sub": claims.get("preferred_username")}


def check_opa(user: dict, action: str, resource: dict) -> dict:
    """Синхронный вызов OPA. Возвращает {"allow": bool, "deny_reason": [...]}."""
    payload = {"input": {"user": user, "action": action, "resource": resource}}
    resp = httpx.post(OPA_URL, json=payload, timeout=5.0)
    resp.raise_for_status()
    result = resp.json().get("result", {})
    return result


@app.get("/whoami")
def whoami(authorization: str = Header(None)):
    """Показывает, что именно Gateway увидел в токене — полезно для демо."""
    user = extract_user_context(authorization)
    return {"extracted_from_jwt": user}


@app.get("/sales")
def get_sales(
    authorization: str = Header(None),
    # ВАЖНО ДЛЯ ДЕМО: этот query-параметр здесь специально,
    # чтобы показать разработчикам, что даже если его подделать —
    # Gateway его ИГНОРИРУЕТ и берёт tenant_id только из JWT.
    tenant_id_attempt: str | None = Query(default=None, alias="tenant_id"),
):
    user = extract_user_context(authorization)

    resource = {"type": "sales_data", "tenant_id": user["tenant_id"]}
    decision = check_opa(user, "read", resource)

    if not decision.get("allow"):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Access denied by OPA",
                "deny_reason": decision.get("deny_reason", []),
            },
        )

    # Реальный запрос — tenant_id берём ТОЛЬКО из user (из JWT), никогда из tenant_id_attempt
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.tenant_id = %s", (user["tenant_id"],))
            cur.execute(
                "SELECT id, tenant_id, region, product, amount, sale_date FROM sales ORDER BY id"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return {
        "authenticated_as": user["sub"],
        "tenant_id_from_jwt": user["tenant_id"],
        "note_ignored_query_param": tenant_id_attempt,
        "rows_returned": [
            {
                "id": r[0], "tenant_id": r[1], "region": r[2],
                "product": r[3], "amount": float(r[4]), "sale_date": str(r[5]),
            }
            for r in rows
        ],
    }


@app.post("/db-credentials")
def get_db_credentials(authorization: str = Header(None)):
    """
    Self-service выдача учётных данных для ПРЯМОГО подключения к Postgres
    (например, через DBeaver) — моделирует "портал Мои доступы" из
    обсуждения: OPA проверяется СИНХРОННО на каждый вызов, а не по
    расписанию. Каждый вызов генерирует НОВЫЙ пароль и делает
    предыдущий недействительным — пароль возвращается только один раз,
    прямо в этом ответе, нигде не сохраняется.
    """
    user = extract_user_context(authorization)

    resource = {"type": "database", "tenant_id": user["tenant_id"]}
    decision = check_opa(user, "grant_direct_db_access", resource)

    if not decision.get("allow"):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Access denied by OPA",
                "deny_reason": decision.get("deny_reason", []),
            },
        )

    tenant_role = TENANT_ROLE_MAP.get(user["tenant_id"])
    if not tenant_role:
        raise HTTPException(status_code=500, detail="Unknown tenant_id — нет соответствующей роли в Postgres")

    # Имя роли собираем сами (username из JWT + известный tenant_id) —
    # но даже так подставляем его в SQL только через sql.Identifier,
    # а не f-строкой, чтобы не зависеть от того, что именно может
    # прийти в preferred_username
    db_username = f"{user['sub']}_{user['tenant_id']}"
    new_password = secrets.token_urlsafe(16)
    valid_until = datetime.now(timezone.utc) + timedelta(minutes=CREDENTIAL_TTL_MINUTES)

    conn = psycopg2.connect(ADMIN_DB_DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (db_username,))
            role_exists = cur.fetchone() is not None

            if role_exists:
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH PASSWORD %s VALID UNTIL %s").format(
                        sql.Identifier(db_username)
                    ),
                    (new_password, valid_until.isoformat()),
                )
            else:
                cur.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s VALID UNTIL %s IN ROLE {}").format(
                        sql.Identifier(db_username), sql.Identifier(tenant_role)
                    ),
                    (new_password, valid_until.isoformat()),
                )
    finally:
        conn.close()

    return {
        "warning": f"Сохраните пароль сейчас — повторно он показан не будет. "
                   f"Действителен {CREDENTIAL_TTL_MINUTES} минут, после чего Postgres "
                   f"физически откажет в подключении (VALID UNTIL), не дожидаясь ручного отзыва.",
        "host": "192.144.13.138",
        "port": 5432,
        "database": "salesdb",
        "username": db_username,
        "password": new_password,
        "valid_until": valid_until.isoformat(),
    }


@app.get("/portal", response_class=HTMLResponse)
def portal():
    """
    УПРОЩЁННАЯ демонстрация портала "Мои доступы".

    ВАЖНО для демо разработчикам: это НЕ то, как должен выглядеть
    настоящий self-service портал в проде. Здесь форма логина сама
    отправляет пароль пользователя в Keycloak через JS (Direct Grant,
    как наш curl) — реальный портал должен делать редирект на страницу
    логина Keycloak (Authorization Code flow), чтобы пароль пользователя
    вообще никогда не проходил через код этой страницы. Мы срезаем угол
    здесь только потому, что настройка полноценного redirect-флоу —
    отдельный, больший кусок конфигурации Keycloak (Standard flow +
    redirect URI), которую мы сознательно оставили за рамками демо.
    """
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Мои доступы — демо-портал</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 480px; margin: 60px auto; padding: 0 20px; color: #222; }
  h1 { font-size: 20px; }
  input { display: block; width: 100%; padding: 8px; margin: 6px 0 14px; box-sizing: border-box; }
  button { padding: 10px 16px; cursor: pointer; }
  .warn { background: #fff3cd; padding: 12px; border-radius: 6px; font-size: 13px; margin-bottom: 20px; }
  .result { background: #f0f0f0; padding: 14px; border-radius: 6px; font-family: monospace; white-space: pre-wrap; margin-top: 16px; }
  .error { background: #fde2e2; padding: 14px; border-radius: 6px; margin-top: 16px; }
</style>
</head>
<body>
<h1>Мои доступы к базе данных</h1>
<div class="warn">
  Демо-версия: пароль вводится прямо здесь и уходит в Keycloak через
  JS (упрощение специально для демо). В настоящем портале это был бы
  редирект на страницу логина Keycloak.
</div>

<label>Логин (AD username)</label>
<input id="username" value="alice">
<label>Пароль</label>
<input id="password" type="password" value="Password123!">
<button onclick="getCredentials()">Получить доступ к БД</button>

<div id="output"></div>

<script>
async function getCredentials() {
  const output = document.getElementById('output');
  output.innerHTML = 'Запрашиваю...';
  const host = window.location.hostname;

  try {
    const tokenResp = await fetch(`http://${host}:8081/realms/demo/protocol/openid-connect/token`, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({
        client_id: 'demo-gateway',
        grant_type: 'password',
        username: document.getElementById('username').value,
        password: document.getElementById('password').value,
      }),
    });
    const tokenData = await tokenResp.json();
    if (!tokenData.access_token) {
      output.innerHTML = `<div class="error">Не удалось войти: ${JSON.stringify(tokenData)}</div>`;
      return;
    }

    const credResp = await fetch(`http://${host}:8000/db-credentials`, {
      method: 'POST',
      headers: {'Authorization': `Bearer ${tokenData.access_token}`},
    });
    const credData = await credResp.json();

    if (!credResp.ok) {
      output.innerHTML = `<div class="error">Доступ запрещён (${credResp.status}): ${JSON.stringify(credData.detail)}</div>`;
      return;
    }

    output.innerHTML = `<div class="result">Host: ${credData.host}
Port: ${credData.port}
Database: ${credData.database}
Username: ${credData.username}
Password: ${credData.password}
Действителен до: ${credData.valid_until}

${credData.warning}</div>`;
  } catch (e) {
    output.innerHTML = `<div class="error">Ошибка сети: ${e}</div>`;
  }
}
</script>
</body>
</html>
"""
