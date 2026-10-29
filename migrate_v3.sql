-- Run ONCE in Supabase > SQL Editor on a database created from the OLD schema.sql / migrate.sql / migrate_v2.sql.
-- Adds the Demographic Form columns to doctors. Nothing is dropped: old name / hospital data stays.
-- (On a brand-new project, run schema.sql instead.)

-- old registration fields become optional (the new form no longer asks for them), and
-- specialization is renamed to specialty. Safe to re-run.
do $$
begin
  if exists (select 1 from information_schema.columns where table_name='doctors' and column_name='specialization') then
    alter table doctors alter column specialization drop not null;
    if not exists (select 1 from information_schema.columns where table_name='doctors' and column_name='specialty') then
      alter table doctors rename column specialization to specialty;
    end if;
  end if;
  if exists (select 1 from information_schema.columns where table_name='doctors' and column_name='name') then
    alter table doctors alter column name drop not null;
  end if;
  if exists (select 1 from information_schema.columns where table_name='doctors' and column_name='hospital') then
    alter table doctors alter column hospital drop not null;
  end if;
end $$;

alter table doctors add column if not exists code                  text;
alter table doctors add column if not exists age                   smallint;
alter table doctors add column if not exists gender                text;
alter table doctors add column if not exists degree                text;
alter table doctors add column if not exists degree_other          text;
alter table doctors add column if not exists specialty             text;
alter table doctors add column if not exists years_since_mbbs      smallint;
alter table doctors add column if not exists designation           text;
alter table doctors add column if not exists designation_other     text;
alter table doctors add column if not exists patient_setting       text;
alter table doctors add column if not exists patient_setting_other text;
alter table doctors add column if not exists ai_allowed            text;
alter table doctors add column if not exists ai_use_any            text;
alter table doctors add column if not exists ai_use_clinical       text;

alter table doctors drop constraint if exists doctors_age_chk;
alter table doctors drop constraint if exists doctors_years_chk;
alter table doctors drop constraint if exists doctors_gender_chk;
alter table doctors drop constraint if exists doctors_degree_chk;
alter table doctors drop constraint if exists doctors_designation_chk;
alter table doctors drop constraint if exists doctors_setting_chk;
alter table doctors drop constraint if exists doctors_ai_allowed_chk;
alter table doctors drop constraint if exists doctors_ai_any_chk;
alter table doctors drop constraint if exists doctors_ai_clin_chk;

alter table doctors add constraint doctors_age_chk         check (age is null or age between 18 and 100);
alter table doctors add constraint doctors_years_chk       check (years_since_mbbs is null or years_since_mbbs between 0 and 70);
alter table doctors add constraint doctors_gender_chk      check (gender is null or gender in ('woman','man','another','prefer_not_to_say'));
alter table doctors add constraint doctors_degree_chk      check (degree is null or degree in ('mbbs','md_ms_dnb','dm_mch','other'));
alter table doctors add constraint doctors_designation_chk check (designation is null or designation in
  ('intern','junior_resident','senior_resident','consultant','senior_consultant','other'));
alter table doctors add constraint doctors_setting_chk     check (patient_setting is null or patient_setting in ('opd','emergency','ward_icu','other'));
alter table doctors add constraint doctors_ai_allowed_chk  check (ai_allowed is null or ai_allowed in ('yes','no','not_sure'));
alter table doctors add constraint doctors_ai_any_chk      check (ai_use_any is null or ai_use_any in
  ('never','lt_monthly','monthly','few_monthly','weekly','few_weekly','daily'));
alter table doctors add constraint doctors_ai_clin_chk     check (ai_use_clinical is null or ai_use_clinical in
  ('never','lt_monthly','monthly','few_monthly','weekly','few_weekly','daily'));

create unique index if not exists doctors_code_uidx on doctors (lower(code)) where code is not null and code <> '';
create index if not exists doctors_created_idx on doctors (created_at);

-- hygiene carried over from schema v8 (safe to re-run)
alter table doctors                  enable row level security;
alter table sessions                 enable row level security;
alter table events                   enable row level security;
alter table patient_records          enable row level security;
alter table if exists treatment_plan_items     enable row level security;
alter table if exists consultation_transcripts enable row level security;
alter table if exists cases                    enable row level security;
create or replace view page_stats with (security_invoker = true) as
select session_id, page,
       count(*) filter (where event_type = 'click') as clicks,
       round(coalesce(sum(duration_ms) filter (where event_type = 'page_time'), 0) / 1000.0, 1) as seconds
from events group by session_id, page;
