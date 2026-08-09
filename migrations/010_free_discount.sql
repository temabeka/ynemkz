-- 010: два типа скидки без механики «скидка дня» (раздел 3.2 ARCHITECTURE.md).
-- discount_free > 0 — базовая скидка, доступная всем зарегистрированным без
-- подписки; 0 — только по подписке (активация без неё отвечает 402).
-- daily_deals не возвращается: бесплатная скидка не привязана к дню.
-- Идемпотентна: повторный прогон не падает.

BEGIN;

ALTER TABLE partners ADD COLUMN IF NOT EXISTS discount_free int NOT NULL DEFAULT 0;

-- Продовые значения для партнёров, заведённых в августе 2026
-- (из partners/parnters.txt; повторный прогон просто перезапишет те же цифры).
UPDATE partners SET discount_free = 10 WHERE name = 'Mofani';
UPDATE partners SET discount_free = 7  WHERE name = 'Yami Yami';
UPDATE partners SET discount_free = 7  WHERE name = 'Yumi Market';
UPDATE partners SET discount_free = 7  WHERE name = 'Tor.ekb';
UPDATE partners SET discount_free = 7  WHERE name = 'La Roza';
UPDATE partners SET discount_free = 5  WHERE name = 'Jump Park';

COMMIT;
