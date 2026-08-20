UPDATE users
   SET plan_expires_at = plan_expires_at - INTERVAL '1 day'
 WHERE is_trial = TRUE
   AND plan_expires_at > NOW();