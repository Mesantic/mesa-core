-- VIEW: CustomerSignupAge
-- Flat SELECT from CustomerWide for BI consumption.
-- No aggregation, no derivation — all measures pre-computed in the Metric layer.

SELECT
    Customer.Customer:ID AS CustomerID
    , Customer.Customer:Name AS CustomerName
    , Customer.Customer:SignupDate AS SignupDate
    , Customer.DaysSinceSignup:DaysSinceSignup AS DaysSinceSignup
FROM {{ ref('CustomerWide') }} AS Customer
