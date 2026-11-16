-- MarsWalk store for https://kcgoeljumzgnkrvraldr.supabase.co
-- Rows the app keeps in SQLite, plus a private bucket for the files Vercel was writing under /tmp.
-- Row Level Security is on and there are no policies, so the publishable key cannot read or write.
-- The database owner (and the service role) bypass that and can.

create table public.sites (
  id text primary key,
  name text not null
);

create table public.stops (
  pk bigint generated always as identity primary key,
  site_id text not null references public.sites (id) on delete cascade,
  code text not null,
  seq integer not null,
  kind text not null check (kind in ('start', 'stop', 'user')),
  name text not null,
  lat double precision not null,
  lon double precision not null,
  dtm_z_m double precision,
  science text not null default '',
  work_time_min double precision not null default 0,
  unique (site_id, code)
);

create index stops_site_id_idx on public.stops (site_id);

create table public.plans (
  id uuid primary key,
  site_id text not null references public.sites (id) on delete cascade,
  created_at timestamptz not null default now(),
  name text not null default '',
  cost_model text not null,
  stop_order text not null,
  stop_codes jsonb not null,
  status text not null default 'requested' check (status in ('requested', 'computed', 'failed')),
  result jsonb
);

create index plans_site_id_idx on public.plans (site_id);
create index plans_created_at_idx on public.plans (created_at desc);

create table public.observations (
  id bigint generated always as identity primary key,
  site_id text not null references public.sites (id) on delete cascade,
  stop_code text not null,
  created_at timestamptz not null default now(),
  author text not null default 'crew',
  note text not null,
  sample_id text
);

create index observations_site_id_idx on public.observations (site_id);
create index observations_site_stop_idx on public.observations (site_id, stop_code);

create table public.settings (
  key text primary key,
  value text not null
);

create table public.bases (
  id text primary key,
  info jsonb not null,
  site_toml text,
  stops jsonb,
  created_at timestamptz not null default now()
);

create table public.stored_objects (
  id bigint generated always as identity primary key,
  site_id text references public.sites (id) on delete cascade,
  kind text not null check (kind in ('catalog', 'dtm', 'ortho', 'thermal', 'base', 'other')),
  bucket text not null default 'marswalk',
  object_path text not null,
  byte_size bigint,
  created_at timestamptz not null default now(),
  unique (bucket, object_path)
);

create index stored_objects_site_id_idx on public.stored_objects (site_id);

alter table public.sites enable row level security;
alter table public.stops enable row level security;
alter table public.plans enable row level security;
alter table public.observations enable row level security;
alter table public.settings enable row level security;
alter table public.bases enable row level security;
alter table public.stored_objects enable row level security;

revoke all on table public.sites from anon, authenticated;
revoke all on table public.stops from anon, authenticated;
revoke all on table public.plans from anon, authenticated;
revoke all on table public.observations from anon, authenticated;
revoke all on table public.settings from anon, authenticated;
revoke all on table public.bases from anon, authenticated;
revoke all on table public.stored_objects from anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit)
values ('marswalk', 'marswalk', false, 1073741824)
on conflict (id) do nothing;
