#!/usr/bin/env python3
"""
Генератор синтетических датасетов продаж для демо-стенда ad-opa-demo.

Company A — сеть фэшн-ритейла (одежда/обувь/аксессуары), сезонность
привязана к коллекциям (весна/осень), средний чек выше, частота ниже.

Company B — сеть продуктовых магазинов (FMCG), высокая частота покупок,
низкий средний чек, всплески по выходным.

Вывод: по одному CSV-файлу на месяц на каждую компанию, в layout,
имитирующем структуру MinIO-бакета:
    company_a/raw/sales_2026-04.csv
    company_a/raw/sales_2026-05.csv
    ...
    company_b/raw/sales_2026-09.csv

Каждый файл — это то, что Airflow DAG обработает за один запуск
(как будто это ежемесячная выгрузка из POS-системы).
"""

import csv
import random
from datetime import date, timedelta

random.seed(42)

MONTHS = [
    (2026, 4), (2026, 5), (2026, 6),
    (2026, 7), (2026, 8), (2026, 9),
]

OUT_ROOT = "/home/claude/synthetic-sales"

PAYMENT_METHODS = ["Карта", "Онлайн", "Наличные", "СБП"]

# ---------------------------------------------------------------------------
# Company A — фэшн-ритейл
# ---------------------------------------------------------------------------

COMPANY_A_REGIONS = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"]

COMPANY_A_CATALOG = {
    "Верхняя одежда": [("Шерстяное пальто", 9500, 18000), ("Пуховик", 7000, 14000), ("Тренч", 8500, 16000)],
    "Платья":         [("Вечернее платье", 6000, 13000), ("Повседневное платье", 2500, 5500), ("Платье миди", 3500, 7000)],
    "Обувь":          [("Кожаные ботинки", 5500, 11000), ("Кроссовки", 3000, 6500), ("Туфли на каблуке", 4000, 9000)],
    "Аксессуары":     [("Кожаная сумка", 4500, 12000), ("Шёлковый платок", 1500, 3500), ("Ремень", 1200, 2800)],
    "Джинсы":         [("Джинсы slim", 2800, 5500), ("Джинсы wide leg", 3200, 6000)],
    "Трикотаж":       [("Кашемировый свитер", 5000, 9500), ("Хлопковый кардиган", 2200, 4500)],
}

# месяцы запуска новых коллекций — всплеск объёма и среднего чека
COMPANY_A_COLLECTION_MONTHS = {4, 9}   # апрель (весна/лето), сентябрь (осень/зима)

# ---------------------------------------------------------------------------
# Company B — FMCG / продуктовая розница
# ---------------------------------------------------------------------------

COMPANY_B_REGIONS = ["Москва", "Санкт-Петербург", "Краснодар", "Воронеж", "Самара"]

COMPANY_B_CATALOG = {
    "Молочные продукты": [("Молоко 1л", 75, 110), ("Йогурт 4 шт.", 140, 210), ("Сыр 200г", 220, 380)],
    "Хлебобулочные":     [("Хлеб белый", 45, 70), ("Хлеб ржаной", 55, 85), ("Круассан", 60, 95)],
    "Напитки":           [("Вода газированная 1.5л", 65, 110), ("Сок апельсиновый 1л", 130, 190), ("Кофе 250г", 350, 650)],
    "Овощи и фрукты":    [("Бананы 1кг", 90, 140), ("Помидоры 1кг", 120, 220), ("Картофель 1кг", 40, 70)],
    "Бытовая химия":     [("Средство для посуды", 150, 260), ("Стиральный порошок", 350, 600), ("Бумажные полотенца", 180, 300)],
    "Кондитерские изделия": [("Шоколад", 90, 160), ("Печенье 300г", 120, 220), ("Мороженое 500мл", 180, 320)],
}


def daterange_for_month(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days)]


def gen_company_a_month(year, month, order_id_start):
    days = daterange_for_month(year, month)
    is_collection_month = month in COMPANY_A_COLLECTION_MONTHS
    base_orders_per_day = 14
    rows = []
    order_id = order_id_start
    for day in days:
        # лёгкий weekend-эффект + сильный collection-эффект
        weekday_factor = 1.25 if day.weekday() >= 5 else 1.0
        collection_factor = 1.8 if is_collection_month else 1.0
        n_orders = max(1, int(random.gauss(base_orders_per_day * weekday_factor * collection_factor, 3)))
        for _ in range(n_orders):
            category = random.choice(list(COMPANY_A_CATALOG.keys()))
            product, lo, hi = random.choice(COMPANY_A_CATALOG[category])
            unit_price = random.randint(lo, hi)
            if is_collection_month:
                unit_price = int(unit_price * random.uniform(1.05, 1.15))
            quantity = random.choices([1, 2, 3], weights=[70, 25, 5])[0]
            rows.append({
                "order_id": f"A-{order_id:06d}",
                "order_date": day.isoformat(),
                "tenant_id": "company_a",
                "store_region": random.choice(COMPANY_A_REGIONS),
                "product_category": category,
                "product_name": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": unit_price * quantity,
                "payment_method": random.choices(PAYMENT_METHODS, weights=[45, 30, 15, 10])[0],
            })
            order_id += 1
    return rows, order_id


def gen_company_b_month(year, month, order_id_start):
    days = daterange_for_month(year, month)
    base_orders_per_day = 55
    rows = []
    order_id = order_id_start
    for day in days:
        weekday_factor = 1.5 if day.weekday() >= 5 else 1.0  # сильный weekend-эффект
        n_orders = max(1, int(random.gauss(base_orders_per_day * weekday_factor, 6)))
        for _ in range(n_orders):
            category = random.choice(list(COMPANY_B_CATALOG.keys()))
            product, lo, hi = random.choice(COMPANY_B_CATALOG[category])
            unit_price = random.randint(lo, hi)
            quantity = random.choices([1, 2, 3, 4, 5], weights=[35, 30, 15, 12, 8])[0]
            rows.append({
                "order_id": f"B-{order_id:06d}",
                "order_date": day.isoformat(),
                "tenant_id": "company_b",
                "store_region": random.choice(COMPANY_B_REGIONS),
                "product_category": category,
                "product_name": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": unit_price * quantity,
                "payment_method": random.choices(PAYMENT_METHODS, weights=[35, 20, 30, 15])[0],
            })
            order_id += 1
    return rows, order_id


FIELDNAMES = [
    "order_id", "order_date", "tenant_id", "store_region",
    "product_category", "product_name", "quantity", "unit_price",
    "total_amount", "payment_method",
]


def write_csv(path, rows):
    # utf-8-sig (BOM) — чтобы Excel на Windows сразу корректно показывал кириллицу
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main():
    a_order_id = 1
    b_order_id = 1
    total_a = 0
    total_b = 0
    for year, month in MONTHS:
        a_rows, a_order_id = gen_company_a_month(year, month, a_order_id)
        b_rows, b_order_id = gen_company_b_month(year, month, b_order_id)
        a_path = f"{OUT_ROOT}/company_a/raw/sales_{year}-{month:02d}.csv"
        b_path = f"{OUT_ROOT}/company_b/raw/sales_{year}-{month:02d}.csv"
        write_csv(a_path, a_rows)
        write_csv(b_path, b_rows)
        total_a += len(a_rows)
        total_b += len(b_rows)
        print(f"{year}-{month:02d}: company_a={len(a_rows):4d} rows -> {a_path}")
        print(f"{year}-{month:02d}: company_b={len(b_rows):4d} rows -> {b_path}")
    print(f"\nИТОГО: company_a={total_a} rows, company_b={total_b} rows")


if __name__ == "__main__":
    main()
