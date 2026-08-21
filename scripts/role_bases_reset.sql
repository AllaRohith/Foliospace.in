-- role_bases_reset.sql
-- Replaces the old t1-t8 catalog with 13 role-aware base templates.
-- Each role gets exactly one "<Role> Base" template.
-- Run this BEFORE the code deploy.

DELETE FROM admin_settings WHERE key = 'templates';

INSERT INTO admin_settings (key, value, updated_at) VALUES (
  'templates',
  '[
    {"id":"chef-base",       "name":"Chef Base",       "role":"chef",       "is_visible":true, "is_selectable":true, "is_default":true,  "is_pro_only":false, "sort":1,  "thumb":"chef.svg",       "description":"Showcase dishes, experience, and a direct message CTA."},
    {"id":"developer-base",  "name":"Developer Base",  "role":"developer",  "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":2,  "thumb":"developer.svg",  "description":"Repos, contribution graph, tech stack, project history."},
    {"id":"designer-base",   "name":"Designer Base",   "role":"designer",   "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":3,  "thumb":"designer.svg",   "description":"Cover-led case studies, process, tools, experience."},
    {"id":"consultant-base", "name":"Consultant Base", "role":"consultant", "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":4,  "thumb":"consultant.svg", "description":"Engagements with outcomes, niche, industries."},
    {"id":"founder-base",    "name":"Founder Base",    "role":"founder",    "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":5,  "thumb":"founder.svg",    "description":"Companies, traction, team, vision, hiring CTA."},
    {"id":"student-base",    "name":"Student Base",    "role":"student",    "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":6,  "thumb":"student.svg",    "description":"Education, internships, side projects, first-role CTA."},
    {"id":"shop-base",       "name":"Shop Base",       "role":"shop",       "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":7,  "thumb":"shop.svg",       "description":"Made-to-order gallery, walk-in hours, location."},
    {"id":"artist-base",     "name":"Artist Base",     "role":"artist",     "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":8,  "thumb":"artist.svg",     "description":"Curated work, exhibitions, galleries, commission CTA."},
    {"id":"writer-base",     "name":"Writer Base",     "role":"writer",     "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":9,  "thumb":"writer.svg",     "description":"Best clips with publication logos, topics covered."},
    {"id":"researcher-base", "name":"Researcher Base", "role":"researcher", "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":10, "thumb":"researcher.svg", "description":"Publications, affiliations, current focus, collab CTA."},
    {"id":"employee-base",   "name":"Employee Base",   "role":"employee",   "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":11, "thumb":"employee.svg",   "description":"Internal mobility, side projects, skills matrix."},
    {"id":"business-base",   "name":"Business Base",   "role":"business",   "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":12, "thumb":"business.svg",   "description":"Company tagline, services, team, metrics, quote CTA."},
    {"id":"other-base",      "name":"Other Base",      "role":"other",      "is_visible":true, "is_selectable":true, "is_default":false, "is_pro_only":false, "sort":13, "thumb":"other.svg",      "description":"Generic-but-distinctive storytelling folio."}
  ]'::jsonb,
  NOW()
)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;

-- Map each user to their category's base template
UPDATE users SET template_id = 'chef-base',       updated_at = NOW() WHERE category = 'chef';
UPDATE users SET template_id = 'developer-base',  updated_at = NOW() WHERE category = 'developer';
UPDATE users SET template_id = 'designer-base',   updated_at = NOW() WHERE category = 'designer';
UPDATE users SET template_id = 'consultant-base', updated_at = NOW() WHERE category = 'consultant';
UPDATE users SET template_id = 'founder-base',    updated_at = NOW() WHERE category = 'founder';
UPDATE users SET template_id = 'student-base',    updated_at = NOW() WHERE category = 'student';
UPDATE users SET template_id = 'shop-base',       updated_at = NOW() WHERE category = 'shop';
UPDATE users SET template_id = 'artist-base',     updated_at = NOW() WHERE category = 'artist';
UPDATE users SET template_id = 'writer-base',     updated_at = NOW() WHERE category = 'writer';
UPDATE users SET template_id = 'researcher-base', updated_at = NOW() WHERE category = 'researcher';
UPDATE users SET template_id = 'employee-base',   updated_at = NOW() WHERE category = 'employee';
UPDATE users SET template_id = 'business-base',   updated_at = NOW() WHERE category = 'business';
UPDATE users SET template_id = 'other-base',      updated_at = NOW() WHERE category = 'other' OR category IS NULL;
