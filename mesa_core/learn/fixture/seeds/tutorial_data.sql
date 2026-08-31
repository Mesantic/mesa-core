-- ------------------------------------------------------------------------
-- MESA(tm) tutorial fixture -- a Mesantic LLC product -- mesantic.com
-- Copyright (c) 2026 Mesantic LLC. Licensed under the MIT License.
-- MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
-- ------------------------------------------------------------------------

-- DuckDB seed data for `mesa learn` tutorial
-- This fixture demonstrates the fat-finger join collision (Lesson 1) and other lessons.
--
-- THE COLLISION: salesforce_customers.id=123 and netsuite_customers.id=123 are
-- DIFFERENT real customers. A naive LEFT JOIN on just `id` will merge them,
-- silently doubling revenue or corrupting aggregates.

-- ─── Salesforce Customers ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS salesforce_customers (
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    signup_date DATE,
    region VARCHAR,
    source_system VARCHAR DEFAULT 'salesforce'
);

INSERT INTO salesforce_customers (id, name, signup_date, region) VALUES
    (123, 'Acme West Corp',      DATE '2024-01-15', 'west'),    -- THE COLLISION
    (201, 'Globex Industries',   DATE '2024-02-10', 'east'),
    (202, 'Initech Solutions',   DATE '2024-03-05', 'west'),
    (203, 'Hooli Technologies',  DATE '2024-04-12', 'central'),
    (204, 'Pied Piper Inc',      DATE '2024-05-20', 'west'),
    (205, 'Aviato LLC',          DATE '2024-06-08', 'east');

-- ─── NetSuite Customers ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS netsuite_customers (
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    signup_date DATE,
    region VARCHAR,
    source_system VARCHAR DEFAULT 'netsuite'
);

INSERT INTO netsuite_customers (id, name, signup_date, region) VALUES
    (123, 'Cyberdyne Systems',   DATE '2024-07-01', 'central'), -- THE COLLISION (different customer!)
    (301, 'Umbrella Corporation',DATE '2024-07-15', 'east'),
    (302, 'Stark Industries',    DATE '2024-08-03', 'west'),
    (303, 'Wayne Enterprises',   DATE '2024-08-20', 'east'),
    (304, 'Oscorp',              DATE '2024-09-10', 'west'),
    (305, 'LexCorp',             DATE '2024-09-25', 'central');

-- ─── Orders (joinable to customers, used in Lesson 3 retention + Lesson 5 isolation) ─
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    source_system VARCHAR,  -- which customer table this joins to
    order_date DATE,
    amount DECIMAL(10, 2)
);

INSERT INTO orders (order_id, customer_id, source_system, order_date, amount) VALUES
    -- Salesforce customers
    (1001, 123, 'salesforce', DATE '2024-02-01', 1500.00),  -- Acme West's order
    (1002, 123, 'salesforce', DATE '2024-03-15', 2200.00),  -- Acme West again
    (1003, 201, 'salesforce', DATE '2024-03-10',  850.00),  -- Globex
    (1004, 202, 'salesforce', DATE '2024-04-05',  450.00),  -- Initech
    (1005, 203, 'salesforce', DATE '2024-05-20', 3100.00),  -- Hooli
    (1006, 204, 'salesforce', DATE '2024-06-12',  920.00),  -- Pied Piper
    -- NetSuite customers
    (2001, 123, 'netsuite',   DATE '2024-07-18', 5500.00),  -- Cyberdyne's order (DIFFERENT cust!)
    (2002, 123, 'netsuite',   DATE '2024-08-02', 4200.00),  -- Cyberdyne again
    (2003, 301, 'netsuite',   DATE '2024-08-10', 1200.00),  -- Umbrella
    (2004, 302, 'netsuite',   DATE '2024-09-01', 2700.00),  -- Stark
    (2005, 303, 'netsuite',   DATE '2024-09-15', 1800.00);  -- Wayne

-- Summary: if you naively join orders to customers on JUST customer_id (ignoring
-- source_system), order 1001+1002 (Acme West, $3700 total) and order 2001+2002
-- (Cyberdyne, $9700 total) will MERGE into one "customer 123" with $13,400 revenue.
-- That's the fat-finger join. MESA's hashed ID (hash of source_system + id) makes
-- the collision structurally impossible — two hashes, two customers, no merge.
