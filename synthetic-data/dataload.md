Чтобы залить это в MinIO (layout как раз под текущие префиксы company_a/, company_b/):

```bash
mc cp company_a/raw/*.csv <alias>/company_a/raw/
mc cp company_b/raw/*.csv <alias>/company_b/raw/
```
(<alias> — твой mc-алиас на MinIO демо-стенда; если не помнишь имя — скажи, гляну в записях по проекту.)
После заливки — переходим к доработке Airflow DAG'ов, чтобы они обрабатывали файлы по одному за запуск (месяц = один DAG run), а не разовой загрузкой. Готов писать DAG?
