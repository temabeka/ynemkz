-- 012: вместо лимита «1 активация у партнёра в день» — кулдаун 30 минут
-- между активациями у одного партнёра (раздел 3.2 ARCHITECTURE.md).
-- Атомарность теперь обеспечивает advisory-lock в redemption.issue(),
-- поэтому уникальный индекс дневного лимита больше не нужен.
-- Идемпотентна: повторный прогон не падает.

BEGIN;

DROP INDEX IF EXISTS uq_redemptions_user_partner_day;

-- Быстрый поиск последней активации пары (пользователь, партнёр)
CREATE INDEX IF NOT EXISTS ix_redemptions_user_partner_time
  ON redemptions (user_id, partner_id, issued_at DESC);

COMMIT;
