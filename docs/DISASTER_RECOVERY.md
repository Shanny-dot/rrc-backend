# Disaster recovery runbook - Reliiance Rewards

Who this is for: whoever has to get the platform back after something goes wrong (Cybria,
or a developer the business brings in). The plain-language version for the business is the
"Disaster Recovery Plan" PDF.

Last reviewed: 30 Oct 2026. Review after every incident and at least every 6 months.

## 1. What runs where

| Part | Where | Notes |
|---|---|---|
| Database (members, points history, rewards, events, referrals, activity log) | Supabase project `rrc-production` (tmsdysbyvapdkbmlcurl), Singapore, PostgreSQL 17 | Free plan: no Supabase backups you can restore yourself - our nightly backup covers this |
| Sign-in accounts | Supabase Auth (same project, `auth` schema) | Included in the nightly backup |
| Images (rewards, events) | Supabase Storage buckets `reward-images`, `arc-media` | Included in the nightly backup |
| Backend API | Render `rrc-backend` (srv-d8lr2usm0tmc73aoaoo0), Singapore, deploys `main` | Code in GitHub `Shanny-dot/rrc-backend`; settings in Render environment |
| Admin site | Panthur cPanel (admin.reliiancerewards.com.au) and Vercel (rrc-admin.vercel.app) | Code in GitHub `Shanny-dot/rrc-admin` |
| Mobile app | Google Play / App Store | Talks only to the backend API |
| Email | Google Workspace SMTP (info@ / membership@) | |
| SMS codes | Guni SMS | |

## 2. Targets

| | Today (free database plan + our nightly backup) | With Supabase Pro + PITR add-on |
|---|---|---|
| Most data that could be lost (RPO) | up to 24 hours | a few minutes |
| Time to be back online (RTO) - server or admin site problem | under 1 hour | under 1 hour |
| Time to be back online - database lost | 4-8 hours (restore into a new project) | 1-2 hours |

Points and redemptions between the last backup and an incident can also be rebuilt from the
activity log, emails sent to members and the reward confirmation emails, but this is manual.

## 3. Backups

- **Nightly backup** (`.github/workflows/nightly-backup.yml`, ~3am Sydney): full database
  dump (`public`, `auth`, `storage`), the table structure (`schema-public.sql`), row counts,
  and every uploaded image. Encrypted with AES-256 using `BACKUP_PASSPHRASE`, kept 30 days as a
  GitHub Actions artifact.
- **Restore test** (same workflow, every night): the backup is restored into a throwaway
  database and every table's row count and the members' points total are compared. A failed
  backup or restore test is emailed by GitHub.
- **Passphrase**: stored in the business password manager AND with Cybria. Without it the
  backups can't be opened - by anyone, including us.
- **Monthly**: download the latest backup and keep it somewhere outside GitHub (e.g. the
  business's Google Drive), still encrypted. Keep 12 monthly copies.
- **Code**: GitHub keeps every version of the backend, admin site and app.
- **Settings**: Render environment values are not in GitHub. Keep a copy of the variable
  names and where each value comes from in the password manager (never in a file or email).

### Turning the backup on (one-off)

1. Supabase > `rrc-production` > Connect > "Session pooler": copy the connection string and
   put the database password in it (reset it in Database settings if nobody has it).
2. GitHub `rrc-backend` > Settings > Secrets and variables > Actions > New secret:
   `BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE` (generate 30+ random characters), `SUPABASE_URL`,
   `SUPABASE_SERVICE_KEY`.
3. Merge the workflow into `main` (scheduled workflows only run from the main branch).
4. Actions > "Nightly backup and restore test" > Run workflow. Check both jobs are green and
   the summary table shows matching counts.

## 4. Scenarios

### A. A staff member made a mistake (wrong points, closed the wrong account)
1. Activity log (admin site) shows who changed what and the values before and after.
2. Points: set the correct balance on the Users page with a clear reason - the change and
   its reason are added to the member's history (history rows can't be edited or deleted).
3. Closed account: Users > Deleted Users > Restore. Nothing is erased when an account is closed.

### B. Backend down or a bad update
1. Render > `rrc-backend` > Events: is a deploy failing or the service crashing?
2. Bad update: Render > Deploys > the last good deploy > "Rollback". Then fix and redeploy.
3. Render itself down: wait, or create a new Render web service from the same repo with the
   same environment values (copy them from the password manager) and point the app/admin
   `API URL` to it (the app needs a release for a new URL - avoid unless Render is down for days).

### C. Admin site down
- One copy down: use the other (admin.reliiancerewards.com.au <-> rrc-admin.vercel.app).
- Rebuild: `npm ci && npm run build` in `rrc-admin` and upload `dist/` to cPanel.

### D. Database lost or corrupted
1. Stop changes: Render > Suspend the backend (members see "can't connect" instead of errors
   that write half-finished data).
2. Get the backup: GitHub > Actions > Nightly backup > latest green run > Artifacts.
   `sha256sum -c rrc-backup-*.sha256`, then
   `gpg -d rrc-backup-*.tar.gz.gpg | tar -xzf -`
3. New Supabase project (Singapore). Same auth settings: TOTP on, min password 8, Site URL and
   redirect URLs, email templates.
4. Restore (PostgreSQL 17 client):
   - tables: `pg_restore --no-owner --no-privileges -n public -d "$NEW_DB" database.dump`
   - sign-in accounts: `pg_restore --no-owner --no-privileges --data-only -n auth -t users -t identities -t mfa_factors -d "$NEW_DB" database.dump`
   - re-run `db/migrations/014_revoke_public_table_access.sql` (public roles get no table access)
   - images: upload the `storage/<bucket>/...` folders to buckets of the same names (public).
5. Point the backend at it: Render environment `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_KEY`, `DATABASE_URL`. Admin site: update `src/lib/supabase.js` (URL and
   publishable key), rebuild, upload to cPanel and push for Vercel.
6. Resume the backend. Check: sign in on the app and admin site (two-step), member counts and
   points totals against `row-counts.tsv` / `points-total.txt`, a test redemption.
7. Tell staff what happened and the time of the backup used; re-enter changes made since.

Rehearse D on the staging project at least every 6 months (docs/STAGING.md).

### E. Leaked key or password
1. Supabase secret key: Settings > API keys > create a new secret key, set it on Render
   (`SUPABASE_SERVICE_KEY`), deploy, then delete the old key.
2. `JWT_SECRET` (member app sign-in): set a new random value on Render. Every member must
   sign in again - only do this if it actually leaked.
3. Database password: Supabase > Database > Reset password; update `BACKUP_DATABASE_URL`.
4. Firebase key: Google Cloud > service accounts > new key, set `FIREBASE_CREDENTIALS_JSON`,
   delete the old key.
5. Check the activity log and Supabase logs for use of the old key.

### F. A staff account is compromised
1. Owner: Staff & access > Remove access (signs them out everywhere immediately) - or
   "Reset two-step" if only the phone was lost.
2. Activity log: filter by their email for the period; undo changes (scenario A).
3. They reset their password before access is given again.

### G. Member reports their account was used by someone else
1. Users > the member > "Sign out of all devices"; ask them to reset their password.
2. Check their points history and redemptions; reverse anything they didn't do.

### H. Personal information may have been exposed (data breach)
1. Contain it (scenarios E/F), keep evidence (activity log export, Supabase/Render logs).
2. Assess within 30 days whether serious harm is likely. If the business is covered by the
   Privacy Act 1988, an eligible data breach must be reported to the OAIC and the affected
   members told (Notifiable Data Breaches scheme). Get the business's adviser involved early.
3. Record what happened, what was done and what changes to prevent it.

## 5. Monitoring

- **Uptime**: `.github/workflows/uptime-check.yml` checks `/health/db` every hour (needs
  merging into `main`). For checks every 5 minutes add the same URL to a free uptime monitor
  (e.g. UptimeRobot) with alerts to membership@.
- **Render health check**: set Render > Settings > Health Check Path to `/health/db`, so a
  broken update isn't switched in.
- **Security alerts** (repeated wrong passwords, large points changes, staff access changes)
  are emailed to the address in Program settings.

## 6. Contacts and accounts

| What | Who / where |
|---|---|
| Supabase, Render, GitHub, Vercel, Firebase owner | Shantanu (Shanny-dot) |
| cPanel (Panthur) | Reliiance Rewards |
| Google Workspace, Play Console, App Store | Reliiance Rewards / Shantanu |
| Technical support | Cybria - info@cybria.in, +91 99814 11102 |
