INSERT INTO admin_settings (key, value, updated_at)
VALUES ('templates', jsonb_build_array(
  jsonb_build_object('id','t1','name','Editorial','description','Cream editorial spread with proof rail, what-I-do grid, and WhatsApp CTA.','is_visible',true,'is_default',true,'is_pro_only',false,'thumb','t1.svg','sort',1),
  jsonb_build_object('id','t2','name','Developer','description','Mono accents, repo-first, contribution graph hero.','is_visible',true,'is_default',false,'is_pro_only',false,'thumb','t2.svg','sort',2),
  jsonb_build_object('id','t3','name','Designer','description','Photo-led portfolio, large type, generous whitespace.','is_visible',true,'is_default',false,'is_pro_only',false,'thumb','t3.svg','sort',3),
  jsonb_build_object('id','t4','name','Chef','description','Photo gallery, tasting menu rail, hours card.','is_visible',true,'is_default',false,'is_pro_only',true,'thumb','t4.svg','sort',4),
  jsonb_build_object('id','t5','name','Consultant','description','Strategy rail, advisory pricing, calendar CTA.','is_visible',true,'is_default',false,'is_pro_only',true,'thumb','t5.svg','sort',5),
  jsonb_build_object('id','t6','name','Shop','description','Product grid, hours, walk-in CTA.','is_visible',true,'is_default',false,'is_pro_only',true,'thumb','t6.svg','sort',6),
  jsonb_build_object('id','t7','name','Founder','description','Thesis-led, advisory rails, angel CTA.','is_visible',true,'is_default',false,'is_pro_only',true,'thumb','t7.svg','sort',7),
  jsonb_build_object('id','t8','name','Student','description','Coursework, internships, open-source PR list.','is_visible',true,'is_default',false,'is_pro_only',false,'thumb','t8.svg','sort',8)
)::jsonb, now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;
