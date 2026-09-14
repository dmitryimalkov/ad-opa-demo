"""
Проверка реальной изоляции: с временными credentials пытаемся
почитать ОБА префикса (company_a/ и company_b/) — должен быть виден
только свой. Требует boto3 (не входит в demo-api по умолчанию —
поставьте разово: docker exec demo-api pip install --quiet boto3).

Запуск: docker exec demo-api python3 minio_list_test.py <access_key> <secret_key> <session_token>
"""
import sys
import boto3
from botocore.exceptions import ClientError

access_key, secret_key, session_token = sys.argv[1], sys.argv[2], sys.argv[3]

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
