-- 004_verify.sql
-- Check that migrations applied correctly

\echo '--- hospitals columns ---'
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'hospitals'
ORDER BY ordinal_position;

\echo '--- patients new columns ---'
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'patients'
  AND column_name IN ('hospital_id', 'registration_source');

\echo '--- hospitals seeded ---'
SELECT id, name, username, county, is_active FROM hospitals ORDER BY id;

\echo '--- patients linked ---'
SELECT
    COUNT(*) FILTER (WHERE hospital_id IS NULL) AS unlinked,
    COUNT(*) FILTER (WHERE hospital_id IS NOT NULL) AS linked
FROM patients;