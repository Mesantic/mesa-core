-- RAW ENTITY: Customer
-- Grain: one row per customer
-- ID: hashed primary key — MD5(CAST(customer_id AS VARCHAR))
-- Doctrine: identity is a hashed surrogate, never the bare source key.
--           1:1 enrichment at top level; system IDs in typed OBJECTs.

SELECT
    md5(CAST(Customer.customer_id AS VARCHAR)) AS ID
    , Customer.customer_name AS Name
    , CAST(Customer.signup_date AS DATE) AS SignupDate
    , Customer.region AS Region
FROM {{ source('quickstart', 'customer') }} AS Customer
