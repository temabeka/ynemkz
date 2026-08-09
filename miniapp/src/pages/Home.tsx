import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { openTelegramLink } from '@telegram-apps/sdk-react';
import { Button, Input } from '@telegram-apps/telegram-ui';
import { categoryRank, type Me, type Partner } from './../api';
import { ErrorState, useCachedApi } from './../hooks';
import { QrIcon } from './../icons';

const BOT = import.meta.env.VITE_BOT_USERNAME as string | undefined;

/** Лендинг клуба: питч + «как это работает» + CTA.
 *  guest — не зарегистрирован (каталог отдал 403): единственный CTA — запустить бота. */
function Landing({ guest, partners }: { guest?: boolean; partners?: Partner[] }) {
  const navigate = useNavigate();
  const maxPct = Math.max(15, ...(partners ?? []).map((p) => p.discount_premium));
  const botLink = `https://t.me/${BOT}`;

  return (
    <div className="vg-land">
      <div className="vg-land-title">Одна подписка — скидки каждый день</div>
      <div className="vg-land-sub">
        Ynem — дисконт-клуб Экибастуза: до −{maxPct}% у партнёров города по подписке.
      </div>
      <div className="vg-land-steps">
        <div className="vg-land-step"><span>1</span>Сканируете QR-наклейку на кассе заведения</div>
        <div className="vg-land-step"><span>2</span>Показываете экран активации кассиру</div>
        <div className="vg-land-step"><span>3</span>Скидка применяется сразу же</div>
      </div>
      {guest ? (
        BOT && (
          <Button size="l" stretched
                  onClick={() => { try { openTelegramLink(botLink); } catch { window.open(botLink); } }}>
            Запустить бота и вступить в клуб
          </Button>
        )
      ) : (
        <div className="vg-land-cta">
          <Button size="l" stretched onClick={() => navigate('/profile')}>
            Оформить подписку
          </Button>
          <Button size="l" stretched mode="bezeled" onClick={() => navigate('/map')}>
            Карта
          </Button>
        </div>
      )}
    </div>
  );
}

function Logo({ src, name }: { src: string | null; name: string }) {
  // lazy — логотипы ниже экрана не качаются, пока не доскроллили;
  // width/height — браузер резервирует место до загрузки CSS/картинки
  return src
    ? <img className="vg-logo" src={src} alt="" width={46} height={46}
           loading="lazy" decoding="async" />
    : <div className="vg-logo">{name[0]}</div>;
}

export default function Home() {
  const navigate = useNavigate();
  const [partners, retryPartners, catalogErr] = useCachedApi<Partner[]>('/catalog');
  // /me уже запрошен в App — здесь ответ придёт из кэша без второго запроса
  const [me] = useCachedApi<Me>('/me');
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const categories = useMemo(
    () =>
      [...new Set((partners ?? []).map((p) => p.category ?? 'Другое'))]
        .sort((a, b) => categoryRank(a) - categoryRank(b)),
    [partners],
  );
  const shown = (partners ?? []).filter(
    (p) =>
      (!category || (p.category ?? 'Другое') === category) &&
      (!search || p.name.toLowerCase().includes(search.toLowerCase())),
  );

  const brand = (
    <div className="vg-brand">
      <span className="vg-brand-name">Ynem</span>
      <span className="vg-brand-city">Экибастуз</span>
      {/* Быстрый доступ к персональному QR — то, что достают у кассы */}
      {me && (
        <button className="vg-qr-fab" aria-label="Мой QR" onClick={() => navigate('/qr')}>
          <QrIcon />
        </button>
      )}
    </div>
  );

  if (partners === undefined)
    return (
      <div className="vg-page">
        {brand}
        <div className="vg-skel vg-skel-hero" />
        {Array.from({ length: 4 }, (_, i) => <div key={i} className="vg-skel vg-skel-card" />)}
      </div>
    );

  // Не зарегистрирован (403) — лендинг клуба с единственным шагом: запустить бота
  if (partners === null && catalogErr === 403)
    return (
      <div className="vg-page vg-stagger">
        {brand}
        <Landing guest />
        <div className="vg-empty">
          Каталог и карта заведений откроются после быстрой регистрации в боте.
        </div>
      </div>
    );

  // Каталог не загрузился и кэша нет — честная ошибка с повтором
  if (partners === null)
    return (
      <div className="vg-page">
        {brand}
        <ErrorState onRetry={retryPartners} status={catalogErr} />
      </div>
    );

  return (
    <div className="vg-page vg-stagger">
      {brand}

      {/* Лендинг — пока нет активной подписки; подписчику питч не нужен */}
      {me?.subscription.active !== true && <Landing partners={partners} />}

      <div className="vg-h">Каталог</div>

      <Input placeholder="Поиск заведения" value={search}
             onChange={(e) => setSearch(e.target.value)} />

      <div className="vg-chips" style={{ marginTop: 10 }}>
        <button className={`vg-chip ${category === null ? 'is-on' : ''}`}
                onClick={() => setCategory(null)}>Все</button>
        {categories.map((c) => (
          <button key={c} className={`vg-chip ${category === c ? 'is-on' : ''}`}
                  onClick={() => setCategory(c)}>{c}</button>
        ))}
      </div>

      <div style={{ marginTop: 6 }}>
        {shown.map((p) => (
          <div key={p.id} className="vg-card" onClick={() => navigate(`/partners/${p.id}`)}>
            <Logo src={p.logo_url} name={p.name} />
            <div className="vg-card-body">
              <div className="vg-card-name">{p.name}</div>
              <div className="vg-card-meta">
                {p.address ?? ''}{p.work_hours ? ` · ${p.work_hours}` : ''}
                {p.discount_free > 0 ? ` · без подписки −${p.discount_free}%` : ''}
                {p.deal_note && (
                  <span style={{ color: 'var(--vg-accent)', fontWeight: 600 }}> · 💵 {p.deal_note}</span>
                )}
              </div>
            </div>
            <div className="vg-pct">−{p.discount_premium}%</div>
          </div>
        ))}
        {shown.length === 0 && (
          <div className="vg-empty">
            {partners.length === 0
              ? 'Каталог пока пуст — партнёры скоро появятся'
              : 'Ничего не нашлось. Попробуйте другой запрос или категорию.'}
          </div>
        )}
      </div>
    </div>
  );
}
