INSERT INTO admin_settings (key, value, updated_at)
VALUES ('templates', jsonb_build_array(
  jsonb_build_object('id','t1','name','Editorial','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',false,'is_selectable',false,'thumb','t1.svg','sort',1),
  jsonb_build_object('id','t2','name','Developer','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',false,'is_selectable',false,'thumb','t2.svg','sort',2),
  jsonb_build_object('id','t3','name','Folio','description','Dark editorial canvas, big portrait, outlined type. The FolioSpace default.','is_visible',true,'is_default',true,'is_pro_only',false,'is_selectable',true,'thumb','t3.svg','sort',3),
  jsonb_build_object('id','t4','name','Chef','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',true,'is_selectable',false,'thumb','t4.svg','sort',4),
  jsonb_build_object('id','t5','name','Consultant','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',true,'is_selectable',false,'thumb','t5.svg','sort',5),
  jsonb_build_object('id','t6','name','Shop','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',true,'is_selectable',false,'thumb','t6.svg','sort',6),
  jsonb_build_object('id','t7','name','Founder','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',true,'is_selectable',false,'thumb','t7.svg','sort',7),
  jsonb_build_object('id','t8','name','Student','description','Coming soon','is_visible',true,'is_default',false,'is_pro_only',false,'is_selectable',false,'thumb','t8.svg','sort',8)
)::jsonb, now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;
