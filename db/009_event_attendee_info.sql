-- 009: "Good to know" details for people going to an event (parking, webinar link, dress code).
-- Shown on the event page in the app and in the RSVP, reminder and change emails.
alter table events add column if not exists attendee_info text;
