-- UX refresh (client "App Proposed Changes" designs).
-- Safe to run more than once. Run in Supabase → SQL Editor after 002.

-- ── Redemptions: add a "sent" stage after approval ─────────────────────────
ALTER TABLE redemptions DROP CONSTRAINT IF EXISTS redemptions_status_check;
ALTER TABLE redemptions ADD CONSTRAINT redemptions_status_check
  CHECK (status IN ('pending', 'approved', 'sent', 'rejected'));
ALTER TABLE redemptions ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP WITH TIME ZONE;

-- ── Rewards: fields shown on the reward detail page ───────────────────────
ALTER TABLE rewards ADD COLUMN IF NOT EXISTS what_you_get TEXT;
ALTER TABLE rewards ADD COLUMN IF NOT EXISTS delivery_info TEXT;
ALTER TABLE rewards ADD COLUMN IF NOT EXISTS expiry_info TEXT;
ALTER TABLE rewards ADD COLUMN IF NOT EXISTS terms TEXT;
ALTER TABLE rewards ADD COLUMN IF NOT EXISTS dollar_value NUMERIC(10, 2);

-- ── Referrals: the five-stage tracker ─────────────────────────────────────
-- pending/registered are kept for existing rows (shown as "Invited" / "Joined the app").
ALTER TABLE referrals DROP CONSTRAINT IF EXISTS referrals_status_check;
ALTER TABLE referrals ADD CONSTRAINT referrals_status_check
  CHECK (status IN ('pending', 'invited', 'registered', 'contacted',
                    'loan_in_progress', 'settled', 'rewarded', 'closed'));
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS channel TEXT;          -- sms | whatsapp | email | share | form | contacts | code
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS stage_updated_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS admin_note TEXT;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS consent_given BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS notes TEXT;            -- member's note, e.g. best time to call

-- ── Events: category (the admin form and API already send it; the live table lacked it)
ALTER TABLE events ADD COLUMN IF NOT EXISTS category TEXT;

-- ── Event RSVPs: cancel without losing linked guests ──────────────────────
ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS cancelled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE;

-- ── Wish list ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wishlist (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reward_id UUID NOT NULL REFERENCES rewards(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, reward_id)
);
ALTER TABLE wishlist ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "wishlist_service_all" ON wishlist;
CREATE POLICY "wishlist_service_all" ON wishlist FOR ALL USING (auth.role() = 'service_role');

-- ── Tiers ─────────────────────────────────────────────────────────────────
-- PLACEHOLDER thresholds and benefits until Reliance confirms them.
-- Edit these rows in Supabase; the app reads them live, no release needed.
CREATE TABLE IF NOT EXISTS tiers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT UNIQUE NOT NULL,
    min_points INTEGER NOT NULL,
    benefits TEXT,          -- one benefit per line
    sort_order INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE tiers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "tiers_service_all" ON tiers;
CREATE POLICY "tiers_service_all" ON tiers FOR ALL USING (auth.role() = 'service_role');
INSERT INTO tiers (name, min_points, benefits, sort_order) VALUES
  ('Silver',   0,    'Earn points for referrals and events', 1),
  ('Gold',     1000, 'Everything in Silver
Priority event invites', 2),
  ('Platinum', 5000, 'Everything in Gold
Bonus points on referrals', 3)
ON CONFLICT (name) DO NOTHING;

-- ── Program settings (app_content key/value table) ────────────────────────
CREATE TABLE IF NOT EXISTS app_content (
    key TEXT PRIMARY KEY,
    value TEXT,
    label TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
INSERT INTO app_content (key, value, label) VALUES
  ('referral_points', '0', 'Points per referral when the loan settles (0 = not set yet)'),
  ('tier_basis', 'lifetime', 'Tier based on "lifetime" points earned or current "balance"'),
  ('invite_link', '', 'Link included in referral invite messages (app store or landing page)'),
  ('reward_delivery_default', '', 'Default "How it''s delivered" text for rewards without their own')
ON CONFLICT (key) DO NOTHING;
