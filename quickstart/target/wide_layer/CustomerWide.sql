-- WIDETABLE: Customer
-- Struct-based join of the Customer raw base and all its metrics.
-- No explicit columns. Publish a new metric and recompile — this widetable picks it up automatically.

SELECT
  {{ dbt_utils.star(ref('customer'), relation_alias='Customer') }}
  , {{ dbt_utils.star(ref('CustomerMetric'), relation_alias='CustomerMetric') }}
FROM {{ source('quickstart', 'customer') }} AS Customer
JOIN {{ ref('CustomerMetric') }} AS CustomerMetric
  ON CustomerMetric.ID = Customer.ID
