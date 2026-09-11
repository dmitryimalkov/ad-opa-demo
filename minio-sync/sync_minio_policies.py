"""
sync_minio_policies.py — настоящий связующий код между authz.rego (OPA)
и MinIO. В отличие от прежней версии minio-init/init.sh (где привязки
были захардкожены вручную), этот скрипт РЕАЛЬНО спрашивает OPA про
каждую LDAP-группу и приводит фактические IAM-привязки в MinIO в
соответствие с ответом.

ЧЕСТНАЯ ОГОВОРКА (см. диаграмму "authz_sync_job_flow" в чате и
minio-multitenancy.md): это НЕ live-синхронизация. authz.rego и MinIO
совпадают только НА МОМЕНТ запуска этого скрипта — сам MinIO ничего
не перезапускать не нужно, привязки применяются мгновенно через API,
но их применяет именно этот скрипт, и не имеет доступа к authz.rego
сам по себе. Запускайте заново после каждой правки authz.rego:

    docker compose run --rm minio-sync

Также можно поставить на cron / систему CI, если хочется, чтобы это
происходило само по расписанию — сам скрипт для этого не делает
ничего особенного, просто выполняется от начала до конца и завершается.
"""
import os
import subprocess
import sys

import ldap
import httpx

OPA_URL = os.environ.get("OPA_URL", "http://opa:8181/v1/data/platform/authz")
LDAP_URI = os.environ.get("LDAP_URI", "ldap://ldap:389")
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "cn=admin,dc=demo,dc=local")
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "AdminPass123!")
LDAP_GROUPS_DN = os.environ.get("LDAP_GROUPS_DN", "ou=groups,dc=demo,dc=local")

MC_ALIAS = "myminio"
MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_ROOT_USER = os.environ["MINIO_ROOT_USER"]
MINIO_ROOT_PASSWORD = os.environ["MINIO_ROOT_PASSWORD"]

# Та же логика разбора имени группы, что в demo-api и opa_auth_manager.py —
# намеренно продублирована (независимость сервисов друг от друга).
TENANT_MAP = {"CompanyA": "company_a", "CompanyB": "company_b"}
ROLE_MAP = {"Analysts": "analyst", "Admins": "admin", "Viewers": "viewer"}
TENANT_POLICY_MAP = {"company_a": "company-a-policy", "company_b": "company-b-policy"}


def fetch_all_groups():
    """Возвращает список (dn, cn) всех групп groupOfNames в LDAP."""
    conn = ldap.initialize(LDAP_URI)
    conn.simple_bind_s(LDAP_BIND_DN, LDAP_BIND_PASSWORD)
    results = conn.search_s(LDAP_GROUPS_DN, ldap.SCOPE_SUBTREE, "(objectClass=groupOfNames)", ["cn"])
    conn.unbind_s()
    groups = []
    for dn, attrs in results:
        cn_values = attrs.get("cn", [])
        if cn_values:
            cn = cn_values[0].decode() if isinstance(cn_values[0], bytes) else cn_values[0]
            groups.append((dn, cn))
    return groups


def parse_group(cn):
    """CompanyA-Analysts -> ('company_a', 'analyst')."""
    parts = cn.split("-", 1)
    if len(parts) != 2:
        return None, None
    company_part, role_part = parts
    return TENANT_MAP.get(company_part), ROLE_MAP.get(role_part)


def check_opa(tenant_id, role):
    """Реальный вызов OPA — тот же authz.rego, что у Gateway и Airflow."""
    payload = {
        "input": {
            "user": {"tenant_id": tenant_id, "roles": [role]},
            "action": "s3_access",
            "resource": {"type": "s3_bucket", "tenant_id": tenant_id},
        }
    }
    resp = httpx.post(OPA_URL, json=payload, timeout=5.0)
    resp.raise_for_status()
    return bool(resp.json().get("result", {}).get("allow"))


def get_currently_attached_policies(group_dn):
    """
    Смотрит, что СЕЙЧАС реально привязано в MinIO для этой группы.
    Разбор вывода mc намеренно простой (проверка вхождения имени
    политики в текст) — формат вывода mc не строго документирован,
    это самый устойчивый к его изменению способ. Если что-то пойдёт
    не так — здесь первое место для отладки: раскомментируйте print(result.stdout).
    """
    result = subprocess.run(
        ["mc", "idp", "ldap", "policy", "entities", MC_ALIAS, "--group", group_dn],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  WARNING: не удалось прочитать текущие привязки для {group_dn}: {result.stderr.strip()}")
        return set()
    return {p for p in TENANT_POLICY_MAP.values() if p in result.stdout}


def attach_policy(group_dn, policy_name):
    subprocess.run(
        ["mc", "idp", "ldap", "policy", "attach", MC_ALIAS, policy_name, "--group", group_dn],
        check=True,
    )


def detach_policy(group_dn, policy_name):
    subprocess.run(
        ["mc", "idp", "ldap", "policy", "detach", MC_ALIAS, policy_name, "--group", group_dn],
        check=True,
    )


def main():
    subprocess.run(
        ["mc", "alias", "set", MC_ALIAS, MINIO_URL, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD],
        check=True, capture_output=True,
    )

    groups = fetch_all_groups()
    print(f"[minio-sync] Найдено групп в LDAP: {len(groups)}")

    for group_dn, cn in groups:
        tenant_id, role = parse_group(cn)
        if tenant_id is None or role is None:
            print(f"[minio-sync] {cn}: не по нашему шаблону имени, пропускаю")
            continue

        allowed = check_opa(tenant_id, role)
        desired_policy = TENANT_POLICY_MAP.get(tenant_id)
        current = get_currently_attached_policies(group_dn)

        if allowed and desired_policy not in current:
            print(f"[minio-sync] {cn}: OPA allow, политики нет -> ПРИВЯЗЫВАЮ {desired_policy}")
            attach_policy(group_dn, desired_policy)
        elif not allowed and desired_policy in current:
            print(f"[minio-sync] {cn}: OPA deny, политика привязана -> ОТВЯЗЫВАЮ {desired_policy}")
            detach_policy(group_dn, desired_policy)
        else:
            print(f"[minio-sync] {cn}: уже в нужном состоянии (OPA allow={allowed})")

    print("[minio-sync] Синхронизация завершена.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[minio-sync] ОШИБКА: {e}")
        sys.exit(1)
