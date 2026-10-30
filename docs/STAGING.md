# Test (staging) copy

A separate copy of the backend and database for trying changes before they reach members.
Nothing in it touches live data, sends real texts or pushes alerts to members' phones.

| Part | Live | Staging |
|---|---|---|
| Backend | Render `rrc-backend` (branch `main`, Starter plan) | Render `rrc-backend-staging` (branch `staging`, free plan) |
| Database | Supabase `rrc-production` | Supabase `rrc-staging` (second project; the free plan allows two) |
| Admin site | admin.reliiancerewards.com.au / rrc-admin.vercel.app | Vercel preview of the admin `staging` branch |
| Email / SMS / phone alerts | On | Email to a test inbox only; SMS and phone alerts off |

Cost: nothing on the free plans (the staging backend sleeps when idle, so the first request
after a while takes ~30 s). Needs the account owners' approval because it adds a Supabase
project and a Render service to their accounts.

## One-off setup (about 1-2 hours)

1. **Database.** In Supabase create a project `rrc-staging` (same region, Singapore). In its
   SQL editor run, in order:
   1. `schema-public.sql` from the latest nightly backup (the exact live table structure -
      the migration files alone don't rebuild it, because 008, 009 and 011 were applied by hand),
   2. `db/migrations/015_staff_roles_audit_log.sql` if the backup is from before 015 went live.
   Then `python seed_demo_members.py` (pointed at staging) for demo members, rewards and events.
   **Never copy live members' personal data into staging.**
2. **Auth settings** in the staging project: minimum password length 8, authenticator (TOTP)
   two-step on, Site URL = the staging admin URL.
3. **Backend.** Render > New > Blueprint > `rrc-backend` > `render.staging.yaml`. Fill in the
   staging Supabase URL and keys, a staging `DATABASE_URL` and a test `ADMIN_EMAIL`.
4. **Branches.** Create `staging` in `rrc-backend` and `rrc-admin`. In Vercel set the admin's
   `VITE_API_URL` for the `staging` branch (Preview environment) to the staging backend URL.
5. **App.** For app testing, build a test APK with the API base URL set to the staging
   backend (test package `com.rrc.app.test`).

## Everyday use

1. Merge the change into `staging`; Render and Vercel deploy it to the test copy.
2. Run the checks on the test copy (sign-up, sign-in with two-step, points, redemptions,
   events, the admin pages the change touches).
3. Only then merge into `main` (live). Database changes are run in staging first, then live.
