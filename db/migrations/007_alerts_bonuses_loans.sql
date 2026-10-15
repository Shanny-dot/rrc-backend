-- 3.2: push alerts and settings, birthday/milestone bonuses, loan check-ins, event
-- thank-you emails, points expiry. Safe to run more than once.

-- ── Members ───────────────────────────────────────────────────────────────
-- Settlement date of the member's own home loan (staff enter it on the admin Users page).
-- Drives the yearly "Is your loan still competitive?" check-in and the anniversary bonus.
ALTER TABLE users ADD COLUMN IF NOT EXISTS loan_settled_on DATE;
-- Which phone alerts the member wants, e.g. {"events": false}. Missing keys mean "on".
ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ── New points transaction types ──────────────────────────────────────────
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_type_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_type_check
  CHECK (type IN ('signup_bonus', 'referral', 'event_attend', 'event_guest', 'redemption',
                  'redemption_refund', 'admin_adjustment', 'bonus', 'points_expired'));

-- ── Alerts sent by the daily job (also stops the same alert going out twice) ──
CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,          -- event_reminder | points_expiring | bonus_birthday | loan_checkin | ...
    ref TEXT NOT NULL,           -- what it was about, e.g. the event id or the year
    title TEXT,
    body TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, kind, ref)
);
CREATE INDEX IF NOT EXISTS idx_notification_log_user ON notification_log (user_id, created_at DESC);
ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "notification_log_service_all" ON notification_log;
CREATE POLICY "notification_log_service_all" ON notification_log FOR ALL USING (auth.role() = 'service_role');

-- ── "Request a review" from the loan check-in ─────────────────────────────
CREATE TABLE IF NOT EXISTS loan_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'closed')),
    note TEXT,                   -- member's note, e.g. best time to call
    staff_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_loan_reviews_created_at ON loan_reviews (created_at DESC);
ALTER TABLE loan_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "loan_reviews_service_all" ON loan_reviews;
CREATE POLICY "loan_reviews_service_all" ON loan_reviews FOR ALL USING (auth.role() = 'service_role');

-- ── Event thank-you emails ────────────────────────────────────────────────
ALTER TABLE events ADD COLUMN IF NOT EXISTS thank_you_sent_at TIMESTAMP WITH TIME ZONE;

-- ── Program settings (0 = off until Reliance decides) ─────────────────────
INSERT INTO app_content (key, value, label) VALUES
  ('points_expiry_months', '0', 'Points expire this many months after they''re earned (0 = never)'),
  ('bonus_birthday_points', '0', 'Birthday bonus points (0 = off)'),
  ('bonus_loan_anniversary_points', '0', 'Loan anniversary bonus points (0 = off)'),
  ('bonus_first_referral_points', '0', 'Bonus for a member''s first successful referral (0 = off)')
ON CONFLICT (key) DO NOTHING;
