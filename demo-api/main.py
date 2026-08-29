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
import httpx
import jwt
from jwt import PyJWKClient
from fastapi import FastAPI, Header, HTTPException, Query
import psycopg2

app = FastAPI(title="Demo Gateway (AD + OPA + RLS)")

OPA_URL = os.environ["OPA_URL"]
DB_DSN = os.environ["DB_DSN"]
KEYCLOAK_REALM_URL = os.environ["KEYCLOAK_REALM_URL"]

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

    # tenant_id и roles должны быть проброшены Keycloak-маппером
    # из групп LDAP/AD в custom claims токена (см. README, шаг настройки Keycloak)
    tenant_id = claims.get("tenant_id")
    roles = claims.get("roles", [])

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
