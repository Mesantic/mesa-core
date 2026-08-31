-- ------------------------------------------------------------------------
-- MESA(tm) tutorial fixture -- a Mesantic LLC product -- mesantic.com
-- Copyright (c) 2026 Mesantic LLC. Licensed under the MIT License.
-- MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
-- ------------------------------------------------------------------------

-- METRIC: IsLargeOrder
-- Owner: tutorial
-- Contract: one row per order, 1 if amount > $1000, else 0

{{ config(tags=['metric_order']) }}

SELECT
    O.ID,
    CASE WHEN O.Amount > 1000.0 THEN 1 ELSE 0 END AS IsLargeOrder
FROM {{ ref('OrderRaw') }} AS O
