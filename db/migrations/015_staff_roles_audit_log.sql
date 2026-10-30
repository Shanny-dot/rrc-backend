-- Security phase 2: staff access levels, a permanent activity log, and "sign out everywhere".
--
-- 1. Staff roles. is_admin still says "may use the admin site"; admin_role says what they may do
--    there (see app/core/permissions.py). Existing admins become owners.
-- 2. audit_log: every change made on the admin site and every security event (locked sign-ins,
--    staff access changes, sign-outs). Rows can only be added - never edited or deleted.
-- 3. users.signed_out_at: sign-in tokens issued before this moment stop working.

alter table public.users add column if not exists admin_role text;
alter table public.users drop constraint if exists users_admin_role_valid;
alter table public.users add constraint users_admin_role_valid
    check (admin_role is null or admin_role in ('owner', 'manager', 'staff', 'viewer'));
update public.users set admin_role = 'owner' where is_admin and admin_role is null;

alter table public.users add column if not exists signed_out_at timestamptz;

create table if not exists public.audit_log (
    id          bigserial primary key,
    at          timestamptz not null default now(),
    kind        text not null check (kind in ('admin', 'security')),
    action      text not null,
    actor_id    uuid,
    actor_email text,
    actor_role  text,
    target      text,
    details     jsonb,
    status      int,
    ip          text,
    user_agent  text
);
create index if not exists audit_log_at_idx on public.audit_log (at desc);
create index if not exists audit_log_actor_idx on public.audit_log (actor_id, at desc);

alter table public.audit_log enable row level security;
revoke all on public.audit_log from anon, authenticated;
revoke all on sequence public.audit_log_id_seq from anon, authenticated;

create or replace function public.guard_audit_log() returns trigger
language plpgsql set search_path = public as $$
begin
    raise exception 'audit_log_is_append_only';
end $$;

drop trigger if exists guard_audit_log on public.audit_log;
create trigger guard_audit_log before update or delete on public.audit_log
    for each row execute function public.guard_audit_log();
-- (TRUNCATE is not row-level: only the database owner can run it, the server key cannot.)
revoke truncate on public.audit_log from service_role;
