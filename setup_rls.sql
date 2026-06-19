-- ============================================================
-- RRC App — Row Level Security Policies
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- ── USERS ────────────────────────────────────────────────────
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Users can only read/update their own profile
CREATE POLICY "users_select_own" ON public.users
  FOR SELECT USING (auth.uid() = id);

CREATE POLICY "users_update_own" ON public.users
  FOR UPDATE USING (auth.uid() = id);

-- Service role (backend) can do everything
CREATE POLICY "users_service_all" ON public.users
  FOR ALL USING (auth.role() = 'service_role');

-- ── EVENTS ───────────────────────────────────────────────────
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

-- Anyone (including anon) can read active events
CREATE POLICY "events_select_active" ON public.events
  FOR SELECT USING (is_active = true);

-- Only service role can insert/update/delete events
CREATE POLICY "events_service_all" ON public.events
  FOR ALL USING (auth.role() = 'service_role');

-- ── REWARDS ──────────────────────────────────────────────────
ALTER TABLE public.rewards ENABLE ROW LEVEL SECURITY;

-- Anyone can read active rewards
CREATE POLICY "rewards_select_active" ON public.rewards
  FOR SELECT USING (is_active = true);

-- Only service role can manage rewards
CREATE POLICY "rewards_service_all" ON public.rewards
  FOR ALL USING (auth.role() = 'service_role');

-- ── EVENT_RSVPS ──────────────────────────────────────────────
ALTER TABLE public.event_rsvps ENABLE ROW LEVEL SECURITY;

-- Users can read only their own RSVPs
CREATE POLICY "rsvps_select_own" ON public.event_rsvps
  FOR SELECT USING (auth.uid() = user_id);

-- Authenticated users can insert their own RSVPs
CREATE POLICY "rsvps_insert_own" ON public.event_rsvps
  FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Service role can do everything (needed for admin QR scan)
CREATE POLICY "rsvps_service_all" ON public.event_rsvps
  FOR ALL USING (auth.role() = 'service_role');

-- ── REFERRALS ────────────────────────────────────────────────
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;

-- Users can see referrals they sent or received
CREATE POLICY "referrals_select_own" ON public.referrals
  FOR SELECT USING (auth.uid() = referrer_id OR auth.uid() = referred_user_id);

-- Authenticated users can create referrals as themselves
CREATE POLICY "referrals_insert_own" ON public.referrals
  FOR INSERT WITH CHECK (auth.uid() = referrer_id);

-- Service role full access
CREATE POLICY "referrals_service_all" ON public.referrals
  FOR ALL USING (auth.role() = 'service_role');

-- ── TRANSACTIONS ─────────────────────────────────────────────
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;

-- Users can only see their own transactions
CREATE POLICY "transactions_select_own" ON public.transactions
  FOR SELECT USING (auth.uid() = user_id);

-- Service role full access (needed for awarding points)
CREATE POLICY "transactions_service_all" ON public.transactions
  FOR ALL USING (auth.role() = 'service_role');

-- ── REDEMPTIONS ──────────────────────────────────────────────
ALTER TABLE public.redemptions ENABLE ROW LEVEL SECURITY;

-- Users can see their own redemptions
CREATE POLICY "redemptions_select_own" ON public.redemptions
  FOR SELECT USING (auth.uid() = user_id);

-- Authenticated users can create redemptions as themselves
CREATE POLICY "redemptions_insert_own" ON public.redemptions
  FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Service role full access (for admin approval/rejection)
CREATE POLICY "redemptions_service_all" ON public.redemptions
  FOR ALL USING (auth.role() = 'service_role');
