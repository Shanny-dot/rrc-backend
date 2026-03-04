-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    mobile TEXT,
    dob DATE,
    gender TEXT,
    industry TEXT,
    street_address TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    country TEXT DEFAULT 'Australia',
    home_ownership TEXT,
    annual_income TEXT,
    total_points INTEGER NOT NULL DEFAULT 0,
    bonus_points_granted BOOLEAN NOT NULL DEFAULT false,
    profile_complete BOOLEAN NOT NULL DEFAULT false,
    referral_code VARCHAR(8) UNIQUE NOT NULL,
    referred_by UUID REFERENCES users(id) ON DELETE SET NULL,
    is_admin BOOLEAN NOT NULL DEFAULT false,
    fcm_token TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Events Table
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT,
    location TEXT,
    event_date TIMESTAMP WITH TIME ZONE NOT NULL,
    image_url TEXT,
    points_for_attending INTEGER NOT NULL DEFAULT 0,
    points_for_referring INTEGER NOT NULL DEFAULT 0,
    capacity INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Rewards Table
CREATE TABLE IF NOT EXISTS rewards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    points_required INTEGER NOT NULL,
    image_url TEXT,
    stock INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Redemptions Table
CREATE TABLE IF NOT EXISTS redemptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reward_id UUID NOT NULL REFERENCES rewards(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    points_used INTEGER NOT NULL,
    admin_note TEXT,
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    actioned_at TIMESTAMP WITH TIME ZONE
);

-- Referrals Table
CREATE TABLE IF NOT EXISTS referrals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referrer_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_name TEXT NOT NULL,
    referred_mobile TEXT,
    referred_email TEXT,
    referred_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'registered', 'rewarded')),
    points_earned INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Event RSVPs Table
CREATE TABLE IF NOT EXISTS event_rsvps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    qr_token TEXT UNIQUE NOT NULL,
    attended BOOLEAN NOT NULL DEFAULT false,
    points_awarded BOOLEAN NOT NULL DEFAULT false,
    rsvp_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    attended_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(event_id, user_id)
);

-- Event Guests Table
CREATE TABLE IF NOT EXISTS event_guests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rsvp_id UUID NOT NULL REFERENCES event_rsvps(id) ON DELETE CASCADE,
    inviter_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guest_name TEXT NOT NULL,
    guest_mobile TEXT,
    guest_email TEXT,
    attended BOOLEAN NOT NULL DEFAULT false,
    points_awarded_to_inviter BOOLEAN NOT NULL DEFAULT false
);

-- Transactions Table
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('signup_bonus', 'referral', 'event_attend', 'event_guest', 'redemption', 'redemption_refund', 'admin_adjustment')),
    points INTEGER NOT NULL,
    reference_id UUID,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
