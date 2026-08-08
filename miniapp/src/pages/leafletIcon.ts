// Дефолтные иконки Leaflet ломаются под бандлерами — собираем явно.
// CSS Leaflet импортируем здесь же: leafletIcon тянут только Map и Partner,
// поэтому стили уезжают в их ленивый чанк, а не в общий index.css.
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import iconUrl from 'leaflet/dist/images/marker-icon.png';
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png';
import shadowUrl from 'leaflet/dist/images/marker-shadow.png';

export const markerIcon = L.icon({
  iconUrl,
  iconRetinaUrl,
  shadowUrl,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

// --- Тайлы: светлая/тёмная подложка под тему Telegram (CARTO, бесплатно
// с атрибуцией). При переходе на 2ГИС MapGL меняется только компонент карты.

export const TILE_ATTRIBUTION = '© OpenStreetMap · © CARTO';

export function tileUrl(dark: boolean): string {
  return dark
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
}

/** Пин партнёра: логотип (или инициал) в круге + бейдж скидки.
 *  selected — тап по пину. */
export function partnerPin(
  name: string,
  logoUrl: string | null | undefined,
  discount: number,
  { selected = false } = {},
): L.DivIcon {
  const inner = logoUrl
    ? `<img src="${logoUrl.replace(/"/g, '&quot;')}" alt="" />`
    : `<span>${(name[0] ?? '•').toUpperCase()}</span>`;
  const cls = `vg-pin${selected ? ' is-on' : ''}`;
  return L.divIcon({
    className: 'vg-pin-wrap',
    html: `<div class="${cls}">${inner}<b>−${discount}%</b></div>`,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
}
