-- MUMO — Supabase schema for user accounts + persistent chat history
-- Run this once in the Supabase dashboard: Project → SQL Editor → New query → Run.
-- Requires nothing extra: Supabase's built-in `auth.users` table already
-- handles signup/login; this just adds the two tables MUMO needs on top.

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New session',
  results jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_conversations_user on conversations(user_id, updated_at desc);
create index if not exists idx_messages_conversation on messages(conversation_id, created_at);
create index if not exists idx_messages_user on messages(user_id, created_at desc);

-- Row Level Security: every user can only ever see/write their own rows.
alter table conversations enable row level security;
alter table messages enable row level security;

create policy "own conversations" on conversations
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own messages" on messages
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
