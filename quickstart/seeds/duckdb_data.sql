-- DuckDB example data for the MESA Core quickstart.
-- Run:  duckdb quickstart.duckdb < seeds/duckdb_data.sql
-- Then `mesa build` compiles the four tiers against these source tables.

CREATE TABLE IF NOT EXISTS customer (
    customer_id INTEGER,
    customer_name VARCHAR,
    signup_date DATE,
    region VARCHAR
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER,
    customer_id INTEGER,
    order_date DATE,
    amount DECIMAL(10, 2)
);

INSERT INTO customer VALUES
    (101, 'Acme Corp',    DATE '2024-01-15', 'west'),
    (102, 'Globex Inc',   DATE '2024-03-02', 'east'),
    (103, 'Initech LLC',  DATE '2024-06-20', 'west');

INSERT INTO orders VALUES
    (1, 101, DATE '2024-02-01', 250.00),
    (2, 101, DATE '2024-05-10',  40.00),
    (3, 102, DATE '2024-04-01', 500.00),
    (4, 103, DATE '2024-07-15',  75.00);
