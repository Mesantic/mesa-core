-- ------------------------------------------------------------------------
-- MESA(tm) tutorial fixture -- a Mesantic LLC product -- mesantic.com
-- Copyright (c) 2026 Mesantic LLC. Licensed under the MIT License.
-- MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
-- ------------------------------------------------------------------------

-- METRIC: TotalRevenue
-- Owner: tutorial
-- Contract: one row per customer, sum of all order amounts

{{ config(tags=['metric_customer']) }}

WITH OrdersByCustomer AS (
    SELECT
        O.Customer.ID AS CustomerID,
        SUM(O.Amount) AS TotalAmount
    FROM {{ ref('OrderRaw') }} AS O
    GROUP BY O.Customer.ID
)

SELECT
    Customer.ID,
    COALESCE(OBC.TotalAmount, 0.0) AS TotalRevenue
FROM {{ ref('CustomerRaw') }} AS Customer
LEFT JOIN OrdersByCustomer AS OBC
    ON Customer.ID = OBC.CustomerID
