"""Аналог company_a__load_dataset.py, но для Company B — см. комментарии там."""
from datetime import datetime

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

TENANT_ID = "company_b"


def load_dataset(**context):
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
