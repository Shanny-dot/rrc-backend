-- Only the server (service_role key) reads and writes the database; the app and the admin site
-- go through the server. The public (anon) and signed-in (authenticated) roles get no table
-- access at all - not even TRUNCATE, which row-level security does not cover - including for
-- tables created later.
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated, public;
