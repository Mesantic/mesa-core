{{ config(tags=['metric_order']) }}

-- METRIC: IsLargeOrder
-- 1 if the order amount exceeds 100, else 0.
-- Owner: Analytics
-- Contract: 1 row per order ID = 1:1

SELECT
    Order.ID AS ID
    , CASE WHEN Order.Amount > 100 THEN 1 ELSE 0 END AS IsLargeOrder
FROM {{ ref('OrderRaw') }} AS Order
