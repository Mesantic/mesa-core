-- RAW ENTITY: Order
-- Grain: one row per order
-- ID: hashed primary key — MD5(CAST(order_id AS VARCHAR))
-- Doctrine: identity is a hashed surrogate, never the bare source key.
--           Customer link carried as a typed OBJECT — hash-only doctrine.

SELECT
    md5(CAST(Order.order_id AS VARCHAR)) AS ID
    , Order.customer_id AS CustomerId
    , CAST(Order.order_date AS DATE) AS OrderDate
    , Order.amount AS Amount
    , STRUCT(Order.customer_id) AS Customer
FROM {{ source('quickstart', 'orders') }} AS Order
