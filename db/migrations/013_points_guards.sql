-- Apply after the server uses the functions in 012 (it must not update total_points directly).
-- 1. A balance can only change through apply_points / set_points / redeem_reward, which also
--    write the ledger row, so the balance and the ledger always agree.
-- 2. The ledger (transactions) can't be edited, and rows can't be deleted unless a deletion
--    is explicitly allowed for that transaction (set_config('rrc.ledger_delete_ok','on',true)),
--    e.g. for a member's lawful erasure request.
-- 3. Balances and stock can't go below zero.

create or replace function public.guard_points_change() returns trigger
language plpgsql set search_path = public as $$
begin
    if new.total_points is distinct from old.total_points
       and coalesce(current_setting('rrc.points_ok', true), '') <> 'on' then
        raise exception 'points_change_not_allowed: use apply_points / set_points';
    end if;
    return new;
end $$;

drop trigger if exists guard_points_change on public.users;
create trigger guard_points_change before update of total_points on public.users
    for each row execute function public.guard_points_change();

create or replace function public.guard_ledger() returns trigger
language plpgsql set search_path = public as $$
begin
    if tg_op = 'UPDATE' then
        raise exception 'ledger_rows_are_read_only';
    end if;
    if coalesce(current_setting('rrc.ledger_delete_ok', true), '') <> 'on' then
        raise exception 'ledger_delete_not_allowed';
    end if;
    return old;
end $$;

drop trigger if exists guard_ledger on public.transactions;
create trigger guard_ledger before update or delete on public.transactions
    for each row execute function public.guard_ledger();

alter table public.users drop constraint if exists users_points_not_negative;
alter table public.users add constraint users_points_not_negative check (total_points >= 0);
alter table public.rewards drop constraint if exists rewards_stock_not_negative;
alter table public.rewards add constraint rewards_stock_not_negative check (stock is null or stock >= 0);
