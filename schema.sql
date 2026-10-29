-- =====================================================================
-- Doctor GenAI Simulation: FULL Supabase schema (v8)
-- Run once in Supabase > SQL Editor on a NEW project.
-- Existing database from v1/v2? Run migrate_v3.sql instead (nothing is dropped).
--
-- Tables
--   doctors                    one row per participant: Demographic Form answers (all optional)
--   sessions                   one row per case a doctor plays
--   events                     every click, page view, page time, video skip, timer expiry, add-to-sheet
--   patient_records            saved prescription sheets
--   treatment_plan_items       structured rows of each saved plan (medicines / tests / follow-up)
--   consultation_transcripts   recorded consultation text (+ optional audio path)
--   cases                      optional reference copy of the case set
--   page_stats (view)          clicks and seconds per page, per session
-- Storage: private bucket 'consultation-audio'
-- =====================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid() (already on in Supabase)

-- ---------------------------------------------------------------------
-- 1. doctors  (Demographic Form)
--    Every answer column is NULLABLE: NULL means the doctor skipped it.
--    Choice answers are stored as short keys; the label shown on screen is in the comment.
-- ---------------------------------------------------------------------
create table if not exists doctors (
  id                      uuid primary key default gen_random_uuid(),

  code                    text,        -- "Your code (given by our team)"
  age                     smallint,    -- "Your age" (years)
  gender                  text,        -- woman | man | another | prefer_not_to_say
  degree                  text,        -- "Highest medical degree": mbbs | md_ms_dnb | dm_mch | other
  degree_other            text,        --   free text when degree = 'other'
  specialty               text,        -- "Your specialty"
  years_since_mbbs        smallint,    -- "Years you have worked as a doctor since completing your MBBS"
  designation             text,        -- intern | junior_resident | senior_resident | consultant | senior_consultant | other
  designation_other       text,        --   free text when designation = 'other'
  patient_setting         text,        -- "Where do you see most of your patients?": opd | emergency | ward_icu | other
  patient_setting_other   text,        --   free text when patient_setting = 'other'
  ai_allowed              text,        -- "Are doctors allowed to use AI tools where you work?": yes | no | not_sure
  ai_use_any              text,        -- AI use in the past month, any purpose (see frequency keys below)
  ai_use_clinical         text,        -- AI use in the past month, clinical questions

  created_at              timestamptz not null default now(),

  constraint doctors_age_chk          check (age is null or age between 18 and 100),
  constraint doctors_years_chk        check (years_since_mbbs is null or years_since_mbbs between 0 and 70),
  constraint doctors_gender_chk       check (gender is null or gender in ('woman','man','another','prefer_not_to_say')),
  constraint doctors_degree_chk       check (degree is null or degree in ('mbbs','md_ms_dnb','dm_mch','other')),
  constraint doctors_designation_chk  check (designation is null or designation in
                                       ('intern','junior_resident','senior_resident','consultant','senior_consultant','other')),
  constraint doctors_setting_chk      check (patient_setting is null or patient_setting in ('opd','emergency','ward_icu','other')),
  constraint doctors_ai_allowed_chk   check (ai_allowed is null or ai_allowed in ('yes','no','not_sure')),
  -- frequency keys: never | lt_monthly (less than once a month) | monthly (about once a month)
  --                 few_monthly (a few times a month) | weekly (about once a week)
  --                 few_weekly (a few times a week) | daily (every day)
  constraint doctors_ai_any_chk       check (ai_use_any is null or ai_use_any in
                                       ('never','lt_monthly','monthly','few_monthly','weekly','few_weekly','daily')),
  constraint doctors_ai_clin_chk      check (ai_use_clinical is null or ai_use_clinical in
                                       ('never','lt_monthly','monthly','few_monthly','weekly','few_weekly','daily'))
);
-- the team's code identifies a participant; many NULLs are allowed, duplicates are not
create unique index if not exists doctors_code_uidx on doctors (lower(code)) where code is not null and code <> '';
create index if not exists doctors_created_idx on doctors (created_at);

-- ---------------------------------------------------------------------
-- 2. sessions
-- ---------------------------------------------------------------------
create table if not exists sessions (
  id          uuid primary key default gen_random_uuid(),
  doctor_id   uuid references doctors(id) on delete cascade,
  tab         text,          -- case letter (B, C, G, H)
  story       text,          -- case title
  opening     text,          -- 'Busy' (clock) or 'Quiet' (no clock)
  device      text,          -- mobile | desktop
  user_agent  text,
  screen      text,
  started_at  timestamptz not null default now()
);
create index if not exists sessions_doctor_idx on sessions (doctor_id, started_at);

-- ---------------------------------------------------------------------
-- 3. events
-- ---------------------------------------------------------------------
create table if not exists events (
  id           bigint generated always as identity primary key,
  session_id   uuid references sessions(id) on delete cascade,
  doctor_id    uuid references doctors(id)  on delete cascade,
  page         text,
  event_type   text not null,        -- click, page_view, page_time, skip_video, timer_expired, add_to_sheet, ...
  label        text,
  duration_ms  integer,
  client_ts    timestamptz,                     -- when it happened on the doctor's device
  created_at   timestamptz not null default now()  -- when the server stored it
);
create index if not exists events_session_idx on events (session_id, created_at);
create index if not exists events_doctor_idx  on events (doctor_id,  created_at);
create index if not exists events_type_idx    on events (event_type);

-- ---------------------------------------------------------------------
-- 4. patient_records  (saved prescription sheets)
-- ---------------------------------------------------------------------
create table if not exists patient_records (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid references sessions(id) on delete cascade,
  doctor_id     uuid references doctors(id)  on delete cascade,
  patient_name  text,
  items         jsonb not null default '[]'::jsonb,   -- list of prescription lines
  notes         text,
  payload       jsonb,                                -- case, transcript, plan, follow-up, approval
  created_at    timestamptz not null default now()
);
create index if not exists records_doctor_idx  on patient_records (doctor_id, created_at);
create index if not exists records_session_idx on patient_records (session_id);

-- ---------------------------------------------------------------------
-- 5. treatment_plan_items
-- ---------------------------------------------------------------------
create table if not exists treatment_plan_items (
  id          bigint generated always as identity primary key,
  record_id   uuid references patient_records(id) on delete cascade,
  session_id  uuid references sessions(id)        on delete cascade,
  category    text check (category in ('med','tst','fu')),   -- medicines, tests, follow-up
  source      text check (source in ('global','own')),       -- global evidence vs doctor's own
  text        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists tpi_session_idx on treatment_plan_items (session_id);
create index if not exists tpi_record_idx  on treatment_plan_items (record_id);

-- ---------------------------------------------------------------------
-- 6. consultation_transcripts
-- ---------------------------------------------------------------------
create table if not exists consultation_transcripts (
  id                uuid primary key default gen_random_uuid(),
  session_id        uuid references sessions(id) on delete cascade,
  doctor_id         uuid references doctors(id)  on delete cascade,
  case_code         char(1),     -- A..H
  transcript        text,
  audio_path        text,        -- path in the 'consultation-audio' storage bucket (optional)
  duration_seconds  integer,
  created_at        timestamptz not null default now()
);
create index if not exists ct_session_idx on consultation_transcripts (session_id);
create index if not exists ct_doctor_idx  on consultation_transcripts (doctor_id);

-- ---------------------------------------------------------------------
-- 7. cases  (optional reference data: edit cases without redeploying)
-- ---------------------------------------------------------------------
create table if not exists cases (
  code         char(1) primary key,   -- A..H
  title        text,
  patient      text,
  high_stakes  boolean,
  has_clock    boolean,
  content      jsonb                  -- complaint, questions, medicines, tests, follow-up, trends
);

-- ---------------------------------------------------------------------
-- 8. page_stats view: clicks and seconds per page, per session
-- ---------------------------------------------------------------------
create or replace view page_stats with (security_invoker = true) as
select session_id,
       page,
       count(*) filter (where event_type = 'click') as clicks,
       round(coalesce(sum(duration_ms) filter (where event_type = 'page_time'), 0) / 1000.0, 1) as seconds
from events
group by session_id, page;

-- ---------------------------------------------------------------------
-- 9. Security
--    The app talks to Supabase only from the server with the service-role key, which bypasses RLS.
--    Turning RLS on with NO policies means the public anon key can read or write nothing.
--    (Participants' answers are personal data: keep it that way.)
-- ---------------------------------------------------------------------
alter table doctors                  enable row level security;
alter table sessions                 enable row level security;
alter table events                   enable row level security;
alter table patient_records          enable row level security;
alter table treatment_plan_items     enable row level security;
alter table consultation_transcripts enable row level security;
alter table cases                    enable row level security;

-- ---------------------------------------------------------------------
-- 10. Storage: private bucket for optional consultation audio
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('consultation-audio', 'consultation-audio', false)
on conflict (id) do nothing;
