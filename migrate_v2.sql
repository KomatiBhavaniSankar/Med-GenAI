-- Run ONCE in Supabase > SQL Editor on an existing database (v2: 8 cases, 10 features).
-- Nothing is dropped. The app still works before this runs; structured plan data is just not stored.
alter table patient_records add column if not exists payload jsonb;  -- case, transcript, plan, follow-up, approval
create table if not exists consultation_transcripts (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete cascade,
  doctor_id uuid references doctors(id),
  case_code char(1),                 -- A..H
  transcript text,
  audio_path text,                   -- path in the 'consultation-audio' storage bucket (optional)
  duration_seconds int,
  created_at timestamptz default now()
);
create table if not exists treatment_plan_items (
  id bigint generated always as identity primary key,
  record_id uuid references patient_records(id) on delete cascade,
  session_id uuid references sessions(id) on delete cascade,
  category text check (category in ('med','tst','fu')),   -- medicines, tests, follow-up
  source text check (source in ('global','own')),         -- global evidence vs doctor's own
  text text not null,
  created_at timestamptz default now()
);
create table if not exists cases (          -- reference data, optional: lets you edit cases without redeploying
  code char(1) primary key, title text, patient text,
  high_stakes boolean, has_clock boolean,
  content jsonb                              -- complaint, questions, medicines, tests, follow-up, trends
);
create index if not exists tpi_session_idx on treatment_plan_items(session_id);
create index if not exists ct_session_idx on consultation_transcripts(session_id);
-- Optional audio storage: create a private bucket named consultation-audio in Storage.
