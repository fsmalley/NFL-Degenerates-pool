create table if not exists public.games (
  id text primary key,
  season integer not null,
  week integer not null,
  game_date text,
  status text,
  away_team text,
  home_team text,
  away_score integer,
  home_score integer,
  winner text,
  loser text,
  margin integer,
  updated_at timestamptz
);

create table if not exists public.draft_players (
  id integer primary key,
  player_name text not null,
  team1 text default '',
  team2 text default '',
  team3 text default '',
  team4 text default '',
  team5 text default '',
  team6 text default '',
  team7 text default '',
  team8 text default '',
  updated_at timestamptz
);

alter table public.games enable row level security;
alter table public.draft_players enable row level security;
