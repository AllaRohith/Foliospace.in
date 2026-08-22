-- Set test slugs to private so they drop out of /sitemap.xml
-- (audit fix #207 Orphaned sitemap pages — 3 of the 7 orphans were test accounts).
-- Reversible: re-set is_public=true to bring them back.

BEGIN;

UPDATE users
   SET is_public = FALSE,
       updated_at = NOW()
 WHERE slug IN (
       'me-test-1787121726',
       'avatar-test-1787115647',
       'fm-test-1787072689'
 );

COMMIT;
