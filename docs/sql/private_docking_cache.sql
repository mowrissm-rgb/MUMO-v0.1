-- LOCAL DRAFT ONLY. Not applied to any database. Inspect and test before rollout.
-- Losslessly compressed evidence is private; no storage bucket or service-role client.
begin;
create table public.private_docking_cache (
    owner_id uuid not null references auth.users(id) on delete cascade,
    pair_key text not null check (pair_key ~ '^[0-9a-f]{64}$'),
    source_run_id text not null check (length(source_run_id) between 1 and 128),
    created_at timestamptz not null,
    evidence text not null check (octet_length(evidence) between 1 and 4194304),
    primary key (owner_id, pair_key)
);
alter table public.private_docking_cache enable row level security;
alter table public.private_docking_cache force row level security;
revoke all on public.private_docking_cache from public, anon, authenticated;
grant select, insert, delete on public.private_docking_cache to authenticated;
create policy private_docking_read on public.private_docking_cache
    for select to authenticated using ((select auth.uid()) = owner_id);
create policy private_docking_insert on public.private_docking_cache
    for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy private_docking_delete on public.private_docking_cache
    for delete to authenticated using ((select auth.uid()) = owner_id);
-- No UPDATE grant/policy: scores, coordinates and original calculation dates are immutable.
-- Serialized owner quota prevents concurrent inserts bypassing the storage budget.
create function public.bound_private_docking_cache() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare
    row_count bigint;
    stored_bytes bigint;
begin
    if auth.uid() is null or auth.uid() <> new.owner_id then
        raise exception 'Private docking cache owner mismatch';
    end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(new.owner_id::text, 0));
    -- Duplicate exact keys keep original evidence without spending additional quota.
    if exists (select 1 from public.private_docking_cache
               where owner_id = new.owner_id and pair_key = new.pair_key) then
        return null;
    end if;
    select count(*), coalesce(sum(octet_length(evidence)), 0) into row_count, stored_bytes
        from public.private_docking_cache where owner_id = new.owner_id;
    if row_count >= 64 or stored_bytes + octet_length(new.evidence) > 67108864 then
        raise exception 'Private docking cache storage limit reached';
    end if;
    return new;
end;
$$;
revoke all on function public.bound_private_docking_cache() from public, anon, authenticated;
create trigger bound_private_docking_cache before insert on public.private_docking_cache
    for each row execute function public.bound_private_docking_cache();
commit;
-- Rollback (separate approved migration): drop table public.private_docking_cache;
-- drop function public.bound_private_docking_cache();
