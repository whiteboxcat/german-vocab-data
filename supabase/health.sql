-- Run once in Supabase: SQL Editor → New query → paste → Run.
-- One row per day from the sync job: words found on verbformen vs. local files vs. this database.

create table if not exists public.sync_health (
  check_date         date primary key,
  checked_at         timestamptz not null,
  status             text not null,       -- ok | downloading | repaired | problem
  target_levels      text[],
  source_nouns       int,                 -- target-level nouns found on verbformen so far
  source_verbs       int,
  downloaded_nouns   int,                 -- of those, already downloaded
  downloaded_verbs   int,
  waiting_nouns      int,                 -- found but not downloaded yet
  waiting_verbs      int,
  unreadable         int,                 -- pages the parser couldn't read
  local_nouns        int,                 -- rows in data/nouns.json
  local_verbs        int,
  db_nouns           int,                 -- rows in public.nouns after the check
  db_verbs           int,
  data_version       int,
  candidates_checked int,                 -- search words looked up so far
  last_sync_result   text,
  requests           int,                 -- requests to verbformen in the last sync
  rate_limited       int,                 -- of those, answered "too many requests"
  problems           text[],
  actions            text[],
  saved_to_supabase  text
);

alter table public.sync_health enable row level security;
drop policy if exists "public read" on public.sync_health;
create policy "public read" on public.sync_health for select using (true);
