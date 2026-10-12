-- App version gate. Safe to run more than once.
-- min_app_version: anything older sees a blocking "Update required" screen.
--   Leave at 3.0.0 until most members have 3.1.0, then raise it.
-- latest_app_version: anything older sees an optional "Update available" prompt.
-- ios_store_url: fill in the App Store link (https://apps.apple.com/app/id<your app id>).
INSERT INTO app_content (key, value, label) VALUES
  ('min_app_version', '3.0.0', 'Oldest app version allowed to open (older must update)'),
  ('latest_app_version', '3.1.0', 'Newest app version in the stores (older get an optional prompt)'),
  ('ios_store_url', '', 'App Store link for the update button'),
  ('android_store_url', 'https://play.google.com/store/apps/details?id=com.rrc.app', 'Google Play link for the update button'),
  ('update_message', '', 'Optional text shown on the update screen')
ON CONFLICT (key) DO NOTHING;
