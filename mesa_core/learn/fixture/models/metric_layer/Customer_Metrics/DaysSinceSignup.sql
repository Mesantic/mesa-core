-- ------------------------------------------------------------------------
-- MESA(tm) tutorial fixture -- a Mesantic LLC product -- mesantic.com
-- Copyright (c) 2026 Mesantic LLC. Licensed under the MIT License.
-- MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
-- ------------------------------------------------------------------------

-- METRIC: DaysSinceSignup
-- Owner: tutorial
-- Contract: one row per customer, days between signup and today

{{ config(tags=['metric_customer']) }}

SELECT
    Customer.ID,
    DATEDIFF('day', Customer.SignupDate, CURRENT_DATE) AS DaysSinceSignup
FROM {{ ref('CustomerRaw') }} AS Customer
