-- Демо-партнёры для витрины и карты (Экибастуз).
-- Идемпотентен: партнёры вставляются по проверке имени (WHERE NOT EXISTS).
-- Запуск: psql "$DATABASE_URL" -f migrations/seed_demo_partners.sql

BEGIN;

-- Кофейня в центре, у площади (центр города ~51.723, 75.323)
INSERT INTO partners (user_id, name, category, address, discount_premium,
                      avg_check, work_hours, is_active, is_paused, lat, lng, logo_url)
SELECT NULL, 'Кофейня «Bereke Coffee»', 'Еда', 'ул. Мәшһүр Жүсіпа, 41',
       12, 2500, 'Пн–Вс 09:00–22:00', true, false,
       51.7268, 75.3196,
       'https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?w=400&q=80'
WHERE NOT EXISTS (SELECT 1 FROM partners WHERE name = 'Кофейня «Bereke Coffee»');

-- Автомойка ближе к промзоне, северо-восток.
-- Категории каталога канонические (Еда/Красота/Фитнес/Развлечения/Шопинг);
-- автомойка не подходит ни под одну — NULL, витрина покажет «Другое».
INSERT INTO partners (user_id, name, category, address, discount_premium,
                      avg_check, work_hours, is_active, is_paused, lat, lng, logo_url)
SELECT NULL, 'Автомойка «Тұлпар»', NULL, 'ул. Энергетиков, 12',
       10, 3000, 'Пн–Вс 08:00–21:00', true, false,
       51.7331, 75.3402,
       'https://images.unsplash.com/photo-1520340356584-f9917d1eea6f?w=400&q=80'
WHERE NOT EXISTS (SELECT 1 FROM partners WHERE name = 'Автомойка «Тұлпар»');

-- Салон красоты в жилом квартале, юго-запад
INSERT INTO partners (user_id, name, category, address, discount_premium,
                      avg_check, work_hours, is_active, is_paused, lat, lng, logo_url)
SELECT NULL, 'Салон красоты «Айгерім»', 'Красота', 'ул. Беркимбаева, 87',
       15, 8000, 'Пн–Сб 10:00–20:00', true, false,
       51.7146, 75.3087,
       'https://images.unsplash.com/photo-1560066984-138dadb4c035?w=400&q=80'
WHERE NOT EXISTS (SELECT 1 FROM partners WHERE name = 'Салон красоты «Айгерім»');

COMMIT;
