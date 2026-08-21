-- users_template_default.sql
-- Run on Neon once, BEFORE the role-bases deploy.
-- Sets a DB-level DEFAULT on users.template_id so future inserts (signup, OAuth)
-- automatically land on other-base. set_category() will overwrite this with the
-- role-specific base as soon as the user picks a category in /welcome.

ALTER TABLE users
    ALTER COLUMN template_id SET DEFAULT 'other-base';