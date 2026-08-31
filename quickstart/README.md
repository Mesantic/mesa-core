# MESA Core Quickstart

A runnable two-entity (Customer + Order) four-tier project backed by DuckDB —
zero external warehouse required.

## 1. Install

```
pip install mesa-core
```

## 2. Seed the DuckDB data (optional — for running, not just compiling)

```
duckdb quickstart.duckdb < seeds/duckdb_data.sql
```

## 3. Build

```
cd quickstart
mesa build
```

This compiles all four tiers to `target/`:

```
target/
  raw_layer/       CustomerRaw.sql, OrderRaw.sql
  metric_layer/    CustomerMetric.sql, OrderMetric.sql
  wide_layer/      CustomerWide.sql, OrderWide.sql
  view_layer/      CustomerSignupAge.sql
```

## 4. Validate

```
mesa validate
```

## 5. Try the scaffolder

```
printf "customer_id\nname\nsignup_date\n" > cols.txt
mesa new entity Lead --from-columns cols.txt
mesa validate   # -> surfaces the <FILL IN ...> placeholders, as intended
```
