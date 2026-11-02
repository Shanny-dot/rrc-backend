# Security release: go-live steps

Releases the held security work from branch `release/security-go-live` in `rrc-backend` and
`rrc-admin`. Do not release the older `security-*` branches. Only start with the client's go-ahead.

**The order matters.** The new server refuses staff who haven't used two-step, and the old admin
sites can't do two-step, so the admin sites and staff set-up must come before the server.

## Before the day

- [ ] The full release has been rehearsed on the test copy (docs/STAGING.md).
- [ ] Nightly backup and restore test are passing.
- [ ] The client has named staff, their roles and a second Owner.
- [ ] Both branches are up to date with `main` (`git fetch`; `main` must be an ancestor).
- [ ] A quiet time is agreed. Allow about an hour, and tell staff when they'll need their phones.

## On the day

| # | Step | Check |
|---|---|---|
| 1 | Run "Nightly backup and restore test" by hand | Run is green; note the backup's name |
| 2 | Apply `db/migrations/015_staff_roles_audit_log.sql` in the Supabase SQL editor | `audit_log` exists; existing admins have `admin_role = owner` |
| 3 | Admin: nothing to do on Vercel. rrc-admin.vercel.app is the staging / demo copy (admin screens on the test copy; `/join`, `/download` and `/faq` on the live server) and stays that way | Member invite links still open and record on the live server |
| 4 | Admin: `npm run build`, back up the current cPanel files, upload `dist` | admin.reliiancerewards.com.au does the same |
| 5 | Each Owner signs in and sets up the authenticator app | Dashboard opens. Pages work as before; Staff and Activity log appear after step 6 |
| 6 | Server: fast-forward `main` to the release branch and push (Render deploys) | Deploy is live; `/health` and `/health/db` return ok |
| 7 | Render: set Health Check Path to `/health/db` | Service stays live |
| 8 | Owner adds the other staff with their roles; each sets up two-step | Each signs in and sees only their role's pages |
| 9 | Run the checks below | All pass |

Set the health check only after step 6: until then `/health/db` doesn't exist and Render would
treat the server as failing.

## Checks after release

Use demo accounts only.

- [ ] Admin request without two-step is refused; with two-step it works.
- [ ] A Viewer can't change anything.
- [ ] A staff action appears in the Activity log with who, what and when.
- [ ] A demo member can sign in, receives the new sign-in email, and earns and redeems points.
- [ ] A large point change sends the security alert email.
- [ ] "Sign out of all devices" ends the demo member's old session.
- [ ] Render logs show no new errors for an hour.

## Rolling back

Undo in the reverse order. The server goes first, because the old server accepts sessions from
the new admin site, but the new server refuses staff on the old site.

1. **Server:** in Render, roll back to the previous deploy, and clear the Health Check Path first.
   Then `git revert` on `main` or switch off auto-deploy, or the next push will redeploy it.
2. **Admin:** restore the cPanel backup from step 4.
3. **Database:** leave update 015 in place. It only adds things, and the old server ignores them.
   Authenticator links can stay too; the old site doesn't use them.
4. **Data emergency only:** if data is damaged, follow docs/DISASTER_RECOVERY.md scenario D using
   the backup from step 1. This loses anything entered since, so it's the business's decision.

Tell the client what happened and what was rolled back.
