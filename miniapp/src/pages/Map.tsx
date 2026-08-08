import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Spinner } from '@telegram-apps/telegram-ui';
import { miniApp, openLink } from '@telegram-apps/sdk-react';
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import { type Partner } from './../api';
import { useCachedApi } from './../hooks';
import { partnerPin, TILE_ATTRIBUTION, tileUrl } from './leafletIcon';

const EKIBASTUZ: [number, number] = [51.7298, 75.3266];

function LocateButton() {
  const map = useMap();
  const locate = () => {
    navigator.geolocation?.getCurrentPosition((pos) =>
      map.setView([pos.coords.latitude, pos.coords.longitude], 15),
    );
  };
  return (
    <button className="vg-locate" onClick={locate}>Рядом со мной</button>
  );
}

/** Тап по пустой карте закрывает карточку заведения. */
function ClickCatcher({ onClick }: { onClick: () => void }) {
  useMapEvents({ click: onClick });
  return null;
}

/** Leaflet-реализация карты. Вся движко-специфика живёт здесь: при переходе
 *  на 2ГИС MapGL заменяется только этот компонент, страница не меняется. */
function LeafletMap({ points, selected, onSelect }: {
  points: Partner[];
  selected: Partner | null;
  onSelect: (p: Partner | null) => void;
}) {
  let dark = false;
  try { dark = miniApp.isDark(); } catch { /* вне Telegram */ }

  return (
    <MapContainer center={EKIBASTUZ} zoom={13} maxZoom={19} zoomControl={false}
                  className={dark ? 'vg-tiles-dim' : ''} style={{ height: '100%' }}>
      <TileLayer url={tileUrl(dark)} attribution={TILE_ATTRIBUTION} />
      <ClickCatcher onClick={() => onSelect(null)} />
      {points.map((p) => (
        <Marker key={p.id} position={[p.lat!, p.lng!]}
                icon={partnerPin(p.name, p.logo_url, p.discount_premium,
                                 { selected: selected?.id === p.id })}
                eventHandlers={{ click: () => onSelect(p) }} />
      ))}
      {!selected && <LocateButton />}
    </MapContainer>
  );
}

export default function MapPage() {
  const navigate = useNavigate();
  // undefined — грузим точки, null — ошибка сети (карта при этом работает).
  // useCachedApi: точки из кэша рисуются мгновенно, свежий запрос — только
  // если прошлый ответ старше TTL (переключение вкладок не дёргает сеть).
  const [pins, retryPins] = useCachedApi<Partner[]>('/map');
  const [selected, setSelected] = useState<Partner | null>(null);

  // Партнёры без координат на карту не попадают
  const shown = (pins ?? []).filter((p) => p.lat != null && p.lng != null);

  const route2gis = (p: Partner) => {
    // 2GIS — стандарт в Казахстане (раздел 4.5)
    const query = encodeURIComponent(`${p.name} ${p.address ?? 'Экибастуз'}`);
    try { openLink(`https://2gis.kz/search/${query}`); }
    catch { window.open(`https://2gis.kz/search/${query}`); }
  };

  return (
    <div className="map-full">
      <LeafletMap points={shown} selected={selected} onSelect={setSelected} />

      {/* Карточка выбранного заведения — вместо тесного Leaflet-попапа */}
      {selected && (
        <div className="vg-map-card">
          {selected.logo_url
            ? <img className="vg-logo" src={selected.logo_url} alt="" width={46} height={46} />
            : <div className="vg-logo">{selected.name[0]}</div>}
          <div className="vg-card-body">
            <div className="vg-card-name">
              {selected.name} <span className="vg-pct">−{selected.discount_premium}%</span>
            </div>
            <div className="vg-card-meta">
              {[selected.category, selected.address].filter(Boolean).join(' · ') || 'Экибастуз'}
            </div>
            <div className="vg-map-card-actions">
              <Button size="s" onClick={() => navigate(`/partners/${selected.id}`)}>
                Подробнее
              </Button>
              <Button size="s" mode="gray" onClick={() => route2gis(selected)}>
                Маршрут в 2ГИС
              </Button>
            </div>
          </div>
          <button className="vg-map-card-close" aria-label="Закрыть"
                  onClick={() => setSelected(null)}>✕</button>
        </div>
      )}

      {/* Статус загрузки точек — плашкой поверх карты, сама карта живая */}
      {pins === undefined && (
        <div className="vg-map-note">
          <Spinner size="s" />
          Загружаем заведения…
        </div>
      )}
      {pins === null && (
        <div className="vg-map-note">
          Точки не загрузились.
          <button onClick={retryPins}>Повторить</button>
        </div>
      )}
      {pins !== undefined && pins !== null && shown.length === 0 && (
        <div className="vg-map-note">На карте пока нет заведений</div>
      )}
    </div>
  );
}
