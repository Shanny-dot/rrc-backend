-- Points integrity: every balance change happens in one database step together with its
-- ledger row, so two requests at the same moment can't spend the same points twice or
-- lose an update. Only the server (service role) can call these functions.

create or replace function public.apply_points(
    p_user uuid, p_points int, p_type text, p_description text, p_reference uuid default null)
returns int language plpgsql security definer set search_path = public as $$
declare v_total int;
begin
    perform set_config('rrc.points_ok', 'on', true);
    update users set total_points = total_points + p_points
     where id = p_user and total_points + p_points >= 0
     returning total_points into v_total;
    if not found then
        if exists (select 1 from users where id = p_user) then
            raise exception 'insufficient_points';
        end if;
        raise exception 'user_not_found';
    end if;
    if p_points <> 0 then
        insert into transactions (user_id, type, points, description, reference_id)
        values (p_user, p_type, p_points, p_description, p_reference);
    end if;
    return v_total;
end $$;

-- Staff set a member's balance to an exact figure; the difference is logged.
create or replace function public.set_points(p_user uuid, p_new int, p_description text)
returns int language plpgsql security definer set search_path = public as $$
declare v_old int;
begin
    if p_new < 0 then raise exception 'negative_balance'; end if;
    select total_points into v_old from users where id = p_user for update;
    if not found then raise exception 'user_not_found'; end if;
    if p_new <> v_old then
        perform set_config('rrc.points_ok', 'on', true);
        update users set total_points = p_new where id = p_user;
        insert into transactions (user_id, type, points, description)
        values (p_user, 'admin_adjustment', p_new - v_old, p_description);
    end if;
    return p_new;
end $$;

-- A member redeems a reward: balance, first-reward minimum and stock are checked and the
-- request, deduction, ledger row and stock change are written together. The member's row is
-- locked, so their redemptions run one at a time. A repeat of the same request within 10
-- seconds (double tap) is refused instead of creating a second.
create or replace function public.redeem_reward(p_user uuid, p_reward uuid, p_min_first int default 0)
returns jsonb language plpgsql security definer set search_path = public as $$
declare u users; r rewards; red redemptions;
begin
    select * into u from users where id = p_user for update;
    if not found then raise exception 'user_not_found'; end if;
    select * into red from redemptions
     where user_id = p_user and reward_id = p_reward and status = 'pending'
       and requested_at > now() - interval '10 seconds'
     order by requested_at desc limit 1;
    if found then return to_jsonb(red) || '{"duplicate": true}'::jsonb; end if;

    select * into r from rewards where id = p_reward for update;
    if not found then raise exception 'reward_not_found'; end if;
    if not coalesce(r.is_active, true) then raise exception 'reward_inactive'; end if;
    if r.stock is not null and r.stock <= 0 then raise exception 'out_of_stock'; end if;
    if p_min_first > 0 and u.total_points < p_min_first
       and not exists (select 1 from redemptions where user_id = p_user and status <> 'rejected') then
        raise exception 'below_minimum';
    end if;
    if u.total_points < r.points_required then raise exception 'insufficient_points'; end if;

    insert into redemptions (user_id, reward_id, status, points_used)
    values (p_user, p_reward, 'pending', r.points_required) returning * into red;
    perform set_config('rrc.points_ok', 'on', true);
    update users set total_points = total_points - r.points_required where id = p_user;
    insert into transactions (user_id, type, points, description, reference_id)
    values (p_user, 'redemption', -r.points_required, 'Redeemed ' || r.title, red.id);
    if r.stock is not null then update rewards set stock = stock - 1 where id = p_reward; end if;
    return to_jsonb(red);
end $$;

revoke all on function public.apply_points(uuid, int, text, text, uuid) from public, anon, authenticated;
revoke all on function public.set_points(uuid, int, text) from public, anon, authenticated;
revoke all on function public.redeem_reward(uuid, uuid, int) from public, anon, authenticated;
grant execute on function public.apply_points(uuid, int, text, text, uuid) to service_role;
grant execute on function public.set_points(uuid, int, text) to service_role;
grant execute on function public.redeem_reward(uuid, uuid, int) to service_role;
