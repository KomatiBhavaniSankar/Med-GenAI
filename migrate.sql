-- Run ONCE in Supabase > SQL Editor if you already created the tables from the old schema.sql.
-- Adds precise per-event timestamps, device info, and indexes for the admin portal.
alter table events   add column if not exists client_ts timestamptz;
alter table sessions add column if not exists device text;
alter table sessions add column if not exists user_agent text;
alter table sessions add column if not exists screen text;
create index if not exists events_session_idx on events(session_id, created_at);
create index if not exists events_doctor_idx  on events(doctor_id, created_at);
create index if not exists sessions_doctor_idx on sessions(doctor_id, started_at);
