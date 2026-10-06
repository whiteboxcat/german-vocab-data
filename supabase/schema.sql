-- Run this once in Supabase: Dashboard → SQL Editor → New query → paste → Run.
-- The app reads with the public (anon/publishable) key; only the sync job (secret key) can write.

create table if not exists public.nouns (
  id          text primary key,          -- verbformen slug, e.g. "Tisch"
  lemma       text not null,
  article     text,                      -- der / die / das
  plural      text,
  level       text,                      -- A1, A2, ...
  english     text[],
  hash        text not null,             -- changes whenever the word's data changes
  data        jsonb not null,            -- full record: examples, audio links, IPA, ...
  updated_at  timestamptz not null default now()
);

create table if not exists public.verbs (
  id                text primary key,    -- verbformen slug, e.g. "anrufen"
  infinitive        text not null,
  level             text,
  auxiliaries       text[],              -- {haben} / {sein} / both
  present_3sg       text,                -- er ruft an
  praeteritum_3sg   text,                -- er rief an
  partizip2         text,                -- angerufen
  separable_prefix  text,                -- "an" for anrufen, null otherwise
  english           text[],
  hash              text not null,
  data              jsonb not null,      -- full record: conjugation tables, cases/prepositions, examples, audio
  updated_at        timestamptz not null default now()
);

create table if not exists public.meta (
  key    text primary key,               -- data_version, counts, changed_at
  value  jsonb
);

create index if not exists nouns_level_idx on public.nouns (level);
create index if not exists verbs_level_idx on public.verbs (level);
create index if not exists nouns_updated_idx on public.nouns (updated_at);
create index if not exists verbs_updated_idx on public.verbs (updated_at);

alter table public.nouns enable row level security;
alter table public.verbs enable row level security;
alter table public.meta  enable row level security;

drop policy if exists "public read" on public.nouns;
drop policy if exists "public read" on public.verbs;
drop policy if exists "public read" on public.meta;
create policy "public read" on public.nouns for select using (true);
create policy "public read" on public.verbs for select using (true);
create policy "public read" on public.meta  for select using (true);
