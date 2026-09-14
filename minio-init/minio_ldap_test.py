"""
Тест AssumeRoleWithLDAPIdentity — живая проверка STS MinIO с LDAP-логином.
Только stdlib (urllib, xml.etree) — не требует дополнительных пакетов,
запускать через: docker exec demo-api python3 minio_ldap_test.py <username> <password>
"""
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

username, password = sys.argv[1], sys.argv[2]

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
expiration = creds.find("s:Expiration", ns).text

print(f"Успех — временные credentials для {username}:")
print(f"  AccessKeyId:     {access_key}")
print(f"  SecretAccessKey: {secret_key}")
print(f"  SessionToken:    {session_token[:40]}...")
print(f"  Истекает:        {expiration}")
