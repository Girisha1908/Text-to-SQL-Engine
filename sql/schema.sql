-- Ask Your Data demo schema.
-- Mirrors the canonical InsightCart model (customers, orders, order_items, products)
-- plus Olist-style payments. Lives in its own schema so it never collides with
-- ingested data in `public`.

DROP SCHEMA IF EXISTS ask_demo CASCADE;
CREATE SCHEMA ask_demo;
SET search_path TO ask_demo;

CREATE TABLE customers (
    customer_id        VARCHAR(64) PRIMARY KEY,
    customer_unique_id VARCHAR(64) NOT NULL,
    customer_city      VARCHAR(128),
    customer_state     VARCHAR(32),
    customer_country   VARCHAR(64) DEFAULT 'BR',
    created_at         TIMESTAMPTZ NOT NULL            -- sign-up date
);

CREATE TABLE products (
    product_id   VARCHAR(64) PRIMARY KEY,
    product_name VARCHAR(256) NOT NULL,
    category     VARCHAR(128),
    brand        VARCHAR(128),
    price        NUMERIC(10, 2) NOT NULL,              -- list price
    cost         NUMERIC(10, 2),
    created_at   TIMESTAMPTZ
);

CREATE TABLE orders (
    order_id     VARCHAR(64) PRIMARY KEY,
    customer_id  VARCHAR(64) NOT NULL REFERENCES customers (customer_id),
    order_date   TIMESTAMPTZ NOT NULL,
    order_status VARCHAR(32) NOT NULL,                 -- delivered | shipped | processing | canceled
    order_value  NUMERIC(10, 2) NOT NULL               -- = SUM(quantity * unit_price - discount) of its items
);

CREATE TABLE order_items (
    order_id    VARCHAR(64) NOT NULL REFERENCES orders (order_id),
    product_id  VARCHAR(64) NOT NULL REFERENCES products (product_id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customers (customer_id),
    quantity    INTEGER NOT NULL,
    unit_price  NUMERIC(10, 2) NOT NULL,
    discount    NUMERIC(10, 2) NOT NULL DEFAULT 0,     -- absolute amount off the line
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE payments (
    order_id             VARCHAR(64) NOT NULL REFERENCES orders (order_id),
    payment_sequential   INTEGER NOT NULL,
    payment_type         VARCHAR(32) NOT NULL,         -- credit_card | debit_card | boleto | voucher
    payment_installments INTEGER NOT NULL DEFAULT 1,
    payment_value        NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE INDEX ON orders (order_date);
CREATE INDEX ON orders (customer_id);
CREATE INDEX ON customers (created_at);
