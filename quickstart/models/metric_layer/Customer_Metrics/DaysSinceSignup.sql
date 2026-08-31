{{ config(tags=['metric_customer']) }}

-- METRIC: DaysSinceSignup
-- Days between the customer's signup date and today.
-- Owner: Analytics
-- Contract: 1 row per customer ID = 1:1

SELECT
    Customer.ID AS ID
    , datediff('day', Customer.SignupDate, CURRENT_DATE) AS DaysSinceSignup
FROM {{ ref('CustomerRaw') }} AS Customer
