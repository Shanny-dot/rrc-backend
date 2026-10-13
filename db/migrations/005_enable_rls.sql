-- Applied to rrc-production on 2026-10-13.
-- Block direct table access with the public (anon/authenticated) key, which ships in the
-- admin site's code. The backend uses the service-role key, which bypasses RLS, so app and
-- admin behaviour is unchanged. Safe to run more than once.
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rewards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.redemptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_rsvps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_guests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
-- Tables created later by 003 (wishlist, tiers) enable RLS themselves.
