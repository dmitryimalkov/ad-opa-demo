"""
Всё в одном: получить STS credentials через LDAP-логин и сразу
проверить изоляцию — без ручного копирования SessionToken между
командами (частый источник ошибок при копировании длинных строк).

Требует boto3 (docker exec -i demo-api pip install --quiet boto3).
Запуск: docker exec -i demo-api python3 /dev/stdin <username> <password> < minio_full_test.py
"""
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import boto3
from botocore.exceptions import ClientError

username, password = sys.argv[1], sys.argv[2]

# --- Шаг 1: AssumeRoleWithLDAPIdentity ---
data = urllib.parse.urlencode({
    "Action": "AssumeRoleWithLDAPIdentity",
    "LDAPUsername": username,
    "LDAPPassword": password,
    "Version": "2011-06-15",
}).encode()

req = urllib.request.Request("http://minio:9000/", data=data, method="POST")
try:
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode()
except urllib.error.HTTPError as e:
    print(f"ОШИБКА STS: {e.code} {e.read().decode()}")
    sys.exit(1)

ns = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
root = ET.fromstring(body)
creds = root.find(".//s:Credentials", ns)

if creds is None:
    print("Не удалось получить credentials. Сырой ответ:")
    print(body)
    sys.exit(1)

access_key = creds.find("s:AccessKeyId", ns).text
secret_key = creds.find("s:SecretAccessKey", ns).text
session_token = creds.find("s:SessionToken", ns).text

print(f"Успех — временные credentials для {username} получены (STS).")
print()

# --- Шаг 2: сразу проверяем изоляцию теми же credentials ---
s3 = boto3.client(
    "s3",
    endpoint_url="http://minio:9000",
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    aws_session_token=session_token,
)

for prefix in ["company_a/", "company_b/"]:
    print(f"--- Пытаемся прочитать {prefix} ---")
    try:
        resp = s3.list_objects_v2(Bucket="datasets", Prefix=prefix)
        keys = [obj["Key"] for obj in resp.get("Contents", [])]
        print(f"  Доступно, объектов: {len(keys)} {keys}")
    except ClientError as e:
        print(f"  ОТКАЗАНО: {e.response['Error']['Code']} — {e.response['Error']['Message']}")
