"""
DAG называется company_a__load_dataset — префикс до "__" читается
opa_auth_manager.py как tenant_id напрямую, без дополнительного
маппинга. Это и есть механизм изоляции на уровне списка DAG.
"""
from datetime import datetime

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

TENANT_ID = "company_a"


def load_dataset(**context):
    # В реальной реализации: запросить у Gateway presigned URL
    # (POST /s3-upload-url, тот же OPA-проверенный паттерн, что и
    # /db-credentials) и скачать/обработать объект оттуда. Постоянные
    # S3-credentials в Airflow Connection специально НЕ хранятся —
    # тот же принцип, что мы обсуждали для прямого доступа к БД.
    print(f"[{TENANT_ID}] Загружаем датасет (демо: без реального S3)")


def write_metadata(**context):
    Variable.set(f"{TENANT_ID}__last_run", str(context["ts"]))
    print(f"[{TENANT_ID}] Метаданные записаны в Variable '{TENANT_ID}__last_run'")


with DAG(
    dag_id=f"{TENANT_ID}__load_dataset",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=[TENANT_ID],
) as dag:
    t1 = PythonOperator(task_id="load_dataset", python_callable=load_dataset)
    t2 = PythonOperator(task_id="write_metadata", python_callable=write_metadata)
    t1 >> t2
