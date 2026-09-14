#!/bin/sh
# Одноразовая настройка MinIO: только bucket + IAM-политики (их СОДЕРЖИМОЕ).
# Привязку "какой группе какая политика" теперь делает ОТДЕЛЬНЫЙ сервис
# minio-sync, который реально спрашивает OPA — см. minio-sync/sync_minio_policies.py.
# Раньше привязки были захардкожены прямо здесь; убрано, чтобы не было двух
# источников истины (см. minio-multitenancy.md, "Честное уточнение").

set -e

echo "[minio-init] Ждём готовности MinIO..."
until mc alias set myminio http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" > /dev/null 2>&1; do
  sleep 2
done
echo "[minio-init] MinIO доступен"

mc mb --ignore-existing myminio/datasets
echo "[minio-init] Bucket 'datasets' готов"

mc admin policy create myminio company-a-policy /policies/company-a-policy.json
mc admin policy create myminio company-b-policy /policies/company-b-policy.json
echo "[minio-init] Политики company-a-policy / company-b-policy созданы"

echo "[minio-init] Готово (привязку к группам сделает minio-sync)"
