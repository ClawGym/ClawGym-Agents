# ETL Plan: daily_user_etl

This plan enumerates the ETL operations to be logged. Use the exact value text on each line when recording entries.

pipeline
- daily_user_etl: ingest(input/users_2026-04.csv) -> transform(normalize email) -> validate -> aggregate -> export(postgresql://warehouse/public.users_dim)

ingest
- input/users_2026-04.csv - 35,214 rows, CSV format

transform
- Normalize email to lowercase; cast signup_date to DATE (UTC)

filter
- Exclude email domains: test.com

sample
- Sample 10000 rows stratified by country (seed=42)

query
- Top 10 email domains

aggregate
- Daily signups by country

visualize
- Daily signups by country - bar chart (x=signup_date, y=count, by=country)

profile
- Profile users table: null counts, distributions, and domain anomalies

schema
- users_dim v2: id INT PK, email VARCHAR(255), signup_date DATE, country CHAR(2), created_at TIMESTAMP

export
- postgresql://warehouse/public.users_dim - upsert mode