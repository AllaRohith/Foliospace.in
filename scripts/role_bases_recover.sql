-- role_bases_recover.sql
-- Run on Neon to recover from a broken template_id state.
-- Maps every user to their category's base template atomically.
-- The last statement also catches any user whose category doesn't match the enum
-- (NULL, empty string, or unknown value) — those go to other-base.

UPDATE users SET template_id = 'chef-base',       updated_at = NOW() WHERE deleted_at IS NULL AND category = 'chef';
UPDATE users SET template_id = 'developer-base',  updated_at = NOW() WHERE deleted_at IS NULL AND category = 'developer';
UPDATE users SET template_id = 'designer-base',   updated_at = NOW() WHERE deleted_at IS NULL AND category = 'designer';
UPDATE users SET template_id = 'consultant-base', updated_at = NOW() WHERE deleted_at IS NULL AND category = 'consultant';
UPDATE users SET template_id = 'founder-base',    updated_at = NOW() WHERE deleted_at IS NULL AND category = 'founder';
UPDATE users SET template_id = 'student-base',    updated_at = NOW() WHERE deleted_at IS NULL AND category = 'student';
UPDATE users SET template_id = 'shop-base',       updated_at = NOW() WHERE deleted_at IS NULL AND category = 'shop';
UPDATE users SET template_id = 'artist-base',     updated_at = NOW() WHERE deleted_at IS NULL AND category = 'artist';
UPDATE users SET template_id = 'writer-base',     updated_at = NOW() WHERE deleted_at IS NULL AND category = 'writer';
UPDATE users SET template_id = 'researcher-base', updated_at = NOW() WHERE deleted_at IS NULL AND category = 'researcher';
UPDATE users SET template_id = 'employee-base',   updated_at = NOW() WHERE deleted_at IS NULL AND category = 'employee';
UPDATE users SET template_id = 'business-base',   updated_at = NOW() WHERE deleted_at IS NULL AND category = 'business';
UPDATE users SET template_id = 'other-base',      updated_at = NOW()
WHERE deleted_at IS NULL
  AND (category = 'other' OR category IS NULL OR category = ''
       OR category NOT IN ('chef','developer','designer','consultant','founder','student','shop','artist','writer','researcher','employee','business'));