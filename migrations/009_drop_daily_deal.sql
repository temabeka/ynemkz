-- 009: отказ от механики «скидка дня» (раздел 3.2 ARCHITECTURE.md).
-- Скидки теперь только по подписке (discount_premium); утренняя рассылка
-- покупателям и календарь скидки дня удалены. Знак дня партнёрам остаётся.
-- Исторические redemptions.type = 'daily' не трогаем — это история визитов.
-- Идемпотентна: повторный прогон не падает.

BEGIN;

DROP TABLE IF EXISTS daily_deals;
ALTER TABLE partners DROP COLUMN IF EXISTS discount_free;
ALTER TABLE users DROP COLUMN IF EXISTS notify_daily;

COMMIT;
