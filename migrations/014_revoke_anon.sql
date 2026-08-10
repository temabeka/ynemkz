-- 014: отозвать привилегии у ролей anon/authenticated (defense-in-depth к RLS).
--
-- Supabase по умолчанию грантит anon и authenticated ВСЕ привилегии на каждую
-- таблицу public. Сейчас доступ держит только RLS (миграция 013). Это одиночный
-- замок: отключат RLS на таблице — публичный ключ сразу вернёт полный r/w.
--
-- Приложение PostgREST (anon/authenticated) не использует вообще: фронт ходит
-- через FastAPI, бэкенд — под ролью postgres (asyncpg/DATABASE_URL) и service_role
-- (supabase-client, Storage). Обе роли имеют bypassrls и own-привилегии, отзыв их
-- не касается. Поэтому у anon/authenticated можно забрать всё — второй замок.
--
-- Идемпотентна: REVOKE повторно не падает.

BEGIN;

REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

-- Будущие таблицы (их создаёт роль postgres) не должны авто-грантиться этим ролям
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM anon, authenticated;

COMMIT;
