-- 013: включить Row Level Security на всех таблицах (КРИТИЧНО, безопасность).
--
-- Проблема: публичный ключ Supabase (sb_publishable_/anon) по замыслу
-- предназначен быть публичным, а вся защита PostgREST-эндпоинта
-- (<project>.supabase.co/rest/v1/*) держится на RLS. При выключенной RLS
-- любой, у кого есть anon-ключ, читает и пишет ВСЕ таблицы напрямую —
-- users (telegram_id, телефон), subscriptions, redemptions и т.д.
--
-- Фикс: включаем RLS без единой policy → для ролей anon/authenticated
-- доступ запрещён по умолчанию. Бэкенд не затронут: он ходит либо под
-- ролью postgres (rolbypassrls=t) через asyncpg/DATABASE_URL, либо под
-- service_role (rolbypassrls=t) через supabase-client для Storage —
-- обе роли обходят RLS.
--
-- Идемпотентна: ENABLE ROW LEVEL SECURITY повторно не падает.

BEGIN;

ALTER TABLE users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE partners       ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE redemptions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_staff  ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff_invites  ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_edits  ENABLE ROW LEVEL SECURITY;
ALTER TABLE broadcasts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE raffles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE raffle_entries ENABLE ROW LEVEL SECURITY;

COMMIT;
