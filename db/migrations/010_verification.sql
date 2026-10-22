-- Mobile and email verification: a new member's welcome points, welcome email and the
-- staff "new member" email wait until both their mobile and email are verified.
alter table public.users add column if not exists mobile_verified_at timestamptz;
alter table public.users add column if not exists email_verified_at timestamptz;
alter table public.users add column if not exists welcomed_at timestamptz;
alter table public.users add column if not exists signup_method text;

-- Everyone who joined before this change counts as verified and already welcomed.
update public.users set
    mobile_verified_at = coalesce(mobile_verified_at, created_at, now()),
    email_verified_at = coalesce(email_verified_at, created_at, now()),
    welcomed_at = coalesce(welcomed_at, created_at, now())
where welcomed_at is null;
