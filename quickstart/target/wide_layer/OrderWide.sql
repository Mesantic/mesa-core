-- WIDETABLE: Order
-- Struct-based join of the Order raw base and all its metrics.
-- No explicit columns. Publish a new metric and recompile — this widetable picks it up automatically.

SELECT
  {{ dbt_utils.star(ref('orders'), relation_alias='Order') }}
  , {{ dbt_utils.star(ref('OrderMetric'), relation_alias='OrderMetric') }}
FROM {{ source('quickstart', 'orders') }} AS Order
JOIN {{ ref('OrderMetric') }} AS OrderMetric
  ON OrderMetric.ID = Order.ID
