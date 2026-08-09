-- 011: условие скидки партнёра (deal_note) — например «при оплате наличными».
-- Показывается выделенно в карточке заведения, каталоге и боте.
-- Идемпотентна: повторный прогон не падает.

BEGIN;

ALTER TABLE partners ADD COLUMN IF NOT EXISTS deal_note text;

COMMIT;
