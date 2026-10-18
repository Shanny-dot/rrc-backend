-- 008: changes from the client's review of test APK 3.2.0 (launch feedback).
-- Safe to run more than once.

-- Rewards: "In progress" between Pending and Approved/Rejected.
alter table redemptions drop constraint if exists redemptions_status_check;
alter table redemptions add constraint redemptions_status_check
    check (status in ('pending', 'in_progress', 'approved', 'sent', 'rejected'));

-- Events: optional top of a points range ("50–100 pts for attending").
-- points_for_attending / points_for_referring stay the amount awarded automatically.
alter table events add column if not exists points_for_attending_max integer;
alter table events add column if not exists points_for_referring_max integer;

-- New settings edited on the admin website (defaults also live in the backend).
insert into app_content (key, value, label) values
    ('welcome_points', '100', 'Welcome points for new members'),
    ('contact_card_title', 'Contact us', 'Contact card title on Home'),
    ('tiers_intro', '', 'Intro text on the member tiers page')
on conflict (key) do nothing;
