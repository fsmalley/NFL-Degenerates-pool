create table if not exists public.site_settings (
  setting_key text primary key,
  setting_value text not null,
  updated_at timestamptz default now()
);

alter table public.site_settings enable row level security;
