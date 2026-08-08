import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Placeholder } from '@telegram-apps/telegram-ui';
import { MapContainer, Marker, TileLayer } from 'react-leaflet';
import { miniApp, openLink } from '@telegram-apps/sdk-react';
import { scanPartnerSticker } from './../scan';
import { api, ApiError, type Partner } from './../api';
import { ErrorState, useMainButton } from './../hooks';
import { markerIcon, TILE_ATTRIBUTION, tileUrl } from './leafletIcon';

type LoadState = Partner | 'loading' | 'notfound' | 'error';

export default function PartnerPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [partner, setPartner] = useState<LoadState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [scanNote, setScanNote] = useState<string | null>(null);

  useEffect(() => {
    setPartner('loading');
    api<Partner>(`/partners/${id}`)
      .then(setPartner)
      .catch((e: unknown) => {
        // 404 — заведение скрыто/удалено; остальное — проблемы сети
        setPartner(e instanceof ApiError && e.status === 404 ? 'notfound' : 'error');
      });
  }, [id, attempt]);

  const loaded = typeof partner === 'object' ? partner : null;

  let mapDark = false;
  try { mapDark = miniApp.isDark(); } catch { /* вне Telegram */ }

  const route2gis = () => {
    if (!loaded) return;
    // 2GIS — стандарт в Казахстане (раздел 4.5)
    const query = encodeURIComponent(`${loaded.name} ${loaded.address ?? 'Экибастуз'}`);
    try { openLink(`https://2gis.kz/search/${query}`); }
    catch { window.open(`https://2gis.kz/search/${query}`); }
  };

  // Главное действие — системная кнопка Telegram
  useMainButton('Маршрут в 2GIS', route2gis, { visible: !!loaded });

  const scanSticker = async () => {
    // Сканер наклейки, не выходя из приложения (общий хелпер scan.ts)
    setScanNote(null);
    try {
      const opened = await scanPartnerSticker(navigate);
      if (!opened) setScanNote('Сканер здесь недоступен — наведите обычную камеру телефона на QR');
    } catch {
      setScanNote('Не удалось открыть сканер — наведите обычную камеру телефона на QR');
    }
  };

  if (partner === 'loading')
    return (
      <div className="vg-page">
        <div className="vg-skel vg-skel-hero" />
        <div className="vg-skel vg-skel-card" />
      </div>
    );
  if (partner === 'error') return <ErrorState onRetry={() => setAttempt((n) => n + 1)} />;
  if (partner === 'notfound')
    return (
      <div className="vg-center">
        <Placeholder
          header="Не найдено"
          description="Заведение недоступно или скрыто из каталога."
          action={<Button onClick={() => navigate('/')}>К каталогу</Button>}
        />
      </div>
    );

  return (
    <div className="vg-page vg-stagger">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 2px 4px' }}>
        {partner.logo_url
          ? <img className="vg-logo" style={{ width: 64, height: 64, borderRadius: 18 }}
                 src={partner.logo_url} alt="" width={64} height={64} decoding="async" />
          : <div className="vg-logo" style={{ width: 64, height: 64, borderRadius: 18, fontSize: 26 }}>{partner.name[0]}</div>}
        <div>
          <div className="vg-display" style={{ fontWeight: 700, fontSize: 20, color: 'var(--tgui--text_color)' }}>
            {partner.name}
          </div>
          {partner.category && (
            <div style={{ fontSize: 13, color: 'var(--tgui--hint_color)', marginTop: 2 }}>
              {partner.category}
            </div>
          )}
        </div>
      </div>

      <div className="vg-stat-grid" style={{ marginTop: 12 }}>
        <div className="vg-stat">
          <div className="vg-stat-num" style={{ color: 'var(--vg-accent)' }}>−{partner.discount_premium}%</div>
          <div className="vg-stat-cap">по подписке</div>
        </div>
      </div>

      {(partner.address || partner.work_hours) && (
        <div className="vg-card" style={{ marginTop: 12, cursor: 'default' }}>
          <div className="vg-card-body">
            {partner.address && <div className="vg-card-name">{partner.address}</div>}
            {partner.work_hours && <div className="vg-card-meta">{partner.work_hours}</div>}
          </div>
        </div>
      )}

      {partner.lat && partner.lng && (
        <div style={{ borderRadius: 'var(--vg-radius)', overflow: 'hidden', marginTop: 2 }}>
          <MapContainer center={[partner.lat, partner.lng]} zoom={16} style={{ height: 190 }}
                        className={mapDark ? 'vg-tiles-dim' : ''}
                        dragging={false} zoomControl={false}>
            <TileLayer url={tileUrl(mapDark)} attribution={TILE_ATTRIBUTION} />
            <Marker position={[partner.lat, partner.lng]} icon={markerIcon} />
          </MapContainer>
        </div>
      )}

      {/* Два пути к скидке; «Маршрут в 2GIS» — системной MainButton внизу */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16 }}>
        <Button stretched size="l" onClick={() => void scanSticker()}>
          Сканировать QR на кассе
        </Button>
        <Button stretched size="l" mode="bezeled" onClick={() => navigate('/qr')}>
          Показать мой QR кассиру
        </Button>
        {scanNote && <div className="vg-note is-err">{scanNote}</div>}
        <div className="vg-empty" style={{ padding: '8px 16px' }}>
          Скидка активируется любым способом: отсканируйте наклейку на кассе
          или дайте кассиру отсканировать ваш QR.
        </div>
      </div>
    </div>
  );
}
