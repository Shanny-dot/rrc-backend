-- 3.2: in-app feedback and personal invite links. Safe to run more than once.

-- ── Feedback sent from the app's "Send feedback" form ─────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    category TEXT,                       -- idea | problem | praise | other
    message TEXT NOT NULL,
    app_version TEXT,
    platform TEXT,                       -- ios | android
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'read', 'resolved')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback (created_at DESC);
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "feedback_service_all" ON feedback;
CREATE POLICY "feedback_service_all" ON feedback FOR ALL USING (auth.role() = 'service_role');

-- ── Invite link opens, so a friend who installs the app gets the code filled in ──
-- Only a keyed hash of the network address is kept, and rows older than 48 hours are
-- deleted by the backend whenever a new one is recorded.
CREATE TABLE IF NOT EXISTS invite_clicks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_code VARCHAR(8) NOT NULL,
    ip_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invite_clicks_ip ON invite_clicks (ip_hash, created_at DESC);
ALTER TABLE invite_clicks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "invite_clicks_service_all" ON invite_clicks;
CREATE POLICY "invite_clicks_service_all" ON invite_clicks FOR ALL USING (auth.role() = 'service_role');

-- Base of each member's personal invite link (the member's code is added to the end).
INSERT INTO app_content (key, value, label) VALUES
  ('invite_base_url', 'https://rrc-admin.vercel.app/join', 'Personal invite links start with this address')
ON CONFLICT (key) DO NOTHING;
