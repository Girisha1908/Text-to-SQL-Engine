"""Create and seed the `ask_demo` schema used by Ask Your Data.

Deterministic: the same seed always produces the same rows, so evaluation
results are reproducible. Data runs from 2025-01-01 up to the day before
ANCHOR (the demo "today").

Planted for September 2026 ("last month" relative to the anchor), so that
"best customer" really has three different answers:
  C-WHALE  one very large order          -> highest spend
  C-MANY   many orders on only 4 days    -> most orders
  C-FREQ   one order on each of 10 days  -> came back most often

Usage (from backend/):  python ../scripts/seed_ask_demo.py
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

ANCHOR = date(2026, 10, 13)
START = date(2025, 1, 1)
SCHEMA_SQL = ROOT / "sql" / "ask" / "schema.sql"

CITIES = [
    ("Sao Paulo", "SP", 30), ("Campinas", "SP", 8), ("Rio de Janeiro", "RJ", 15),
    ("Belo Horizonte", "MG", 10), ("Curitiba", "PR", 7), ("Porto Alegre", "RS", 7),
    ("Salvador", "BA", 6), ("Brasilia", "DF", 6), ("Recife", "PE", 5), ("Fortaleza", "CE", 4),
]

# (name, category, brand, price, popularity weight)
PRODUCTS = [
    ("4K Television", "Electronics", "Vistra", "3499.00", 1),
    ("Laptop 14in", "Electronics", "Nimbus", "4299.00", 1),
    ("Smartphone X", "Electronics", "Nimbus", "2199.00", 2),
    ("Wireless Headphones", "Electronics", "Sonora", "399.90", 5),
    ("Bluetooth Speaker", "Electronics", "Sonora", "249.90", 4),
    ("Smartwatch", "Electronics", "Pulse", "899.00", 2),
    ("Phone Case", "Accessories", "Shieldy", "29.90", 14),
    ("Charging Cable", "Accessories", "Volt", "19.90", 12),
    ("Power Bank", "Accessories", "Volt", "129.90", 6),
    ("Screen Protector", "Accessories", "Shieldy", "24.90", 10),
    ("Laptop Sleeve", "Accessories", "Carry", "89.90", 4),
    ("Coffee Maker", "Home", "Brewly", "349.00", 3),
    ("Air Fryer", "Home", "Crispa", "599.00", 3),
    ("Bed Sheet Set", "Home", "Linho", "159.90", 5),
    ("Desk Lamp", "Home", "Lumo", "119.90", 4),
    ("Cookware Set", "Home", "Crispa", "699.00", 2),
    ("Running Shoes", "Sports", "Stride", "449.90", 4),
    ("Yoga Mat", "Sports", "Zenfit", "99.90", 5),
    ("Dumbbell Pair", "Sports", "IronCo", "199.90", 3),
    ("Water Bottle", "Sports", "Zenfit", "39.90", 8),
    ("Cotton T-Shirt", "Fashion", "Basico", "59.90", 9),
    ("Denim Jeans", "Fashion", "Basico", "179.90", 5),
    ("Leather Wallet", "Fashion", "Couro", "139.90", 3),
    ("Sunglasses", "Fashion", "Solar", "229.90", 3),
    ("Face Serum", "Beauty", "Glow", "119.90", 5),
    ("Shampoo", "Beauty", "Glow", "34.90", 9),
    ("Perfume", "Beauty", "Essenza", "289.90", 3),
    ("Novel Paperback", "Books", "Leitura", "49.90", 7),
    ("Cookbook", "Books", "Leitura", "89.90", 3),
    ("Building Blocks", "Toys", "Brincar", "199.90", 3),
    ("Board Game", "Toys", "Brincar", "149.90", 3),
    ("Plush Toy", "Toys", "Brincar", "59.90", 4),
]

D = Decimal
CENT = D("0.01")


def _ts(rng: random.Random, day: date) -> datetime:
    return datetime(day.year, day.month, day.day, rng.randint(8, 21), rng.randint(0, 59), tzinfo=timezone.utc)


def _rand_day(rng: random.Random, lo: date, hi: date) -> date:
    """Uniform day in [lo, hi]."""
    return lo + timedelta(days=rng.randint(0, (hi - lo).days))


def build_dataset(seed: int = 42) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    last_day = ANCHOR - timedelta(days=1)

    products = [
        {"product_id": f"P-{i + 1:03d}", "product_name": n, "category": c, "brand": b,
         "price": D(p), "cost": (D(p) * D(rng.choice(["0.55", "0.6", "0.65", "0.7"]))).quantize(CENT),
         "created_at": datetime(2024, 12, 1, tzinfo=timezone.utc)}
        for i, (n, c, b, p, _w) in enumerate(PRODUCTS)
    ]
    weights = [w for *_, w in PRODUCTS]
    by_name = {p["product_name"]: p for p in products}

    customers: list[dict] = []
    order_plans: list[tuple[str, date, list[tuple[dict, int]]]] = []  # (customer_id, day, [(product, qty)])

    city_w = [w for *_, w in CITIES]
    for i in range(1, 401):
        cid = f"C-{i:04d}"
        city, state, _ = rng.choices(CITIES, weights=city_w)[0]
        signup = _rand_day(rng, START, last_day)
        customers.append({"customer_id": cid, "customer_unique_id": f"U-{i:04d}", "customer_city": city,
                          "customer_state": state, "customer_country": "BR", "created_at": _ts(rng, signup)})
        if rng.random() < 0.15:  # signed up, never ordered
            continue
        first = signup + timedelta(days=rng.choice([0, 0, 0, 1, 3, 7, 14, 30, 60, 120]))
        if first > last_day:
            continue
        n_orders = rng.choices(range(1, 11), weights=[30, 20, 14, 10, 8, 6, 5, 3, 2, 2])[0]
        days = [first] + [_rand_day(rng, first, last_day) for _ in range(n_orders - 1)]
        for day in days:
            items = {}
            for _ in range(rng.choices([1, 2, 3], weights=[60, 30, 10])[0]):
                prod = rng.choices(products, weights=weights)[0]
                items[prod["product_id"]] = (prod, rng.choices([1, 2, 3], weights=[75, 18, 7])[0])
            order_plans.append((cid, day, list(items.values())))

    # Planted September 2026 customers (signed up long before, so they are not "new").
    planted = [
        ("C-WHALE", "U-WHALE", [(date(2026, 9, 18), [(by_name["4K Television"], 4), (by_name["Laptop 14in"], 1)])]),
        ("C-MANY", "U-MANY", [(date(2026, 9, d), [(by_name["Phone Case"], 1)])
                              for d in (3, 3, 3, 3, 10, 10, 10, 10, 17, 17, 17, 24, 24, 24)]),
        ("C-FREQ", "U-FREQ", [(date(2026, 9, d), [(by_name["Charging Cable"], 1)])
                              for d in (1, 4, 7, 10, 13, 16, 19, 22, 25, 28)]),
    ]
    for cid, uid, plans in planted:
        customers.append({"customer_id": cid, "customer_unique_id": uid, "customer_city": "Sao Paulo",
                          "customer_state": "SP", "customer_country": "BR",
                          "created_at": _ts(rng, date(2025, 3, 1))})
        order_plans.extend((cid, day, items) for day, items in plans)

    order_plans.sort(key=lambda p: (p[1], p[0]))
    orders, order_items, payments = [], [], []
    for n, (cid, day, items) in enumerate(order_plans, start=1):
        oid = f"O-{n:05d}"
        if cid.startswith("C-0"):
            status = rng.choices(["delivered", "shipped", "canceled"], weights=[90, 5, 5])[0]
            if (last_day - day).days < 5 and status == "delivered":
                status = "processing"
        else:
            status = "delivered"
        value = D(0)
        for prod, qty in items:
            discount = D(0)
            if rng.random() < 0.2:
                discount = (prod["price"] * qty * D(rng.choice(["0.05", "0.1", "0.15"]))).quantize(CENT)
            value += prod["price"] * qty - discount
            order_items.append({"order_id": oid, "product_id": prod["product_id"], "customer_id": cid,
                                "quantity": qty, "unit_price": prod["price"], "discount": discount})
        orders.append({"order_id": oid, "customer_id": cid, "order_date": _ts(rng, day),
                       "order_status": status, "order_value": value})
        if rng.random() < 0.2 and value > 50:
            voucher = (value * D(rng.choice(["0.1", "0.2", "0.3"]))).quantize(CENT)
            payments.append({"order_id": oid, "payment_sequential": 1, "payment_type": "voucher",
                             "payment_installments": 1, "payment_value": voucher})
            payments.append({"order_id": oid, "payment_sequential": 2, "payment_type": "credit_card",
                             "payment_installments": rng.choice([1, 2, 3, 6]), "payment_value": value - voucher})
        else:
            ptype = rng.choices(["credit_card", "boleto", "debit_card", "voucher"], weights=[60, 20, 12, 8])[0]
            payments.append({"order_id": oid, "payment_sequential": 1, "payment_type": ptype,
                             "payment_installments": rng.choice([1, 2, 3, 6, 10]) if ptype == "credit_card" else 1,
                             "payment_value": value})

    return {"customers": customers, "products": products, "orders": orders,
            "order_items": order_items, "payments": payments}


def seed(database_url: str, seed_value: int = 42) -> dict[str, int]:
    """Recreate ask_demo and load the dataset. Returns row counts."""
    data = build_dataset(seed_value)
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
        conn.exec_driver_sql("SET search_path TO ask_demo")
        for table in ("customers", "products", "orders", "order_items", "payments"):
            rows = data[table]
            cols = list(rows[0])
            conn.execute(
                text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"),
                rows,
            )
    engine.dispose()
    return {t: len(r) for t, r in data.items()}


if __name__ == "__main__":
    from app.ask.config import get_ask_settings

    counts = seed(get_ask_settings().database_url)
    print("Seeded ask_demo:", ", ".join(f"{t}={n}" for t, n in counts.items()))
