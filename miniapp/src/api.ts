// Обёртка над fetch: initData в каждом запросе (валидация HMAC на бэке).
import { retrieveRawInitData } from '@telegram-apps/sdk-react';

const BASE = import.meta.env.VITE_API_URL ?? '';

let initDataRaw = '';
try {
  initDataRaw = retrieveRawInitData() ?? '';
} catch {
  // вне Telegram (dev в браузере) — запросы вернут 401, экраны покажут заглушку
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

// --- Кэш последних ответов (sessionStorage): мгновенный повторный рендер ----

export function readCache<T>(path: string): T | undefined {
  try {
    const raw = sessionStorage.getItem(`vg:${path}`);
    return raw ? (JSON.parse(raw) as T) : undefined;
  } catch {
    return undefined;
  }
}

export function writeCache(path: string, value: unknown): void {
  try {
    sessionStorage.setItem(`vg:${path}`, JSON.stringify(value));
  } catch { /* приватный режим и т.п. */ }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `tma ${initDataRaw}`,
      ...options.headers,
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch { /* не JSON */ }
    throw new ApiError(res.status, detail);
  }
  // Любая мутация (активация, оплата, настройки) может изменить каталог,
  // профиль или визиты — сбрасываем свежесть, следующий GET пойдёт в сеть
  if (options.method && options.method !== 'GET') memCache.clear();
  return res.json();
}

/** POST multipart (загрузка файла): Content-Type с boundary ставит браузер сам. */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    method: 'POST',
    headers: { Authorization: `tma ${initDataRaw}` },
    body: form,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch { /* не JSON */ }
    throw new ApiError(res.status, detail);
  }
  memCache.clear(); // мутация — как в api()
  return res.json();
}

/** GET бинарного ответа (аватар для QR): null — нет фото или нет сети. */
export async function apiBlob(path: string): Promise<Blob | null> {
  try {
    const res = await fetch(`${BASE}/api${path}`, {
      headers: { Authorization: `tma ${initDataRaw}` },
    });
    return res.ok ? await res.blob() : null;
  } catch {
    return null;
  }
}

// --- Кэш GET в памяти (TTL): между вкладками не гоняем одни и те же запросы --
// sessionStorage выше даёт мгновенный рендер из прошлого ответа, но фоновый
// refetch раньше уходил при каждом монтировании экрана. Здесь: ответ моложе
// TTL отдаём из памяти без сети, а параллельные GET одного пути склеиваем
// в один fetch. Мутации чистят кэш (см. api выше).
const FRESH_TTL_MS = 60_000;
const memCache = new Map<string, { at: number; data: unknown }>();
const inflight = new Map<string, Promise<unknown>>();

/** GET с памятью: `force` — мимо кэша (кнопка «Повторить»). */
export function apiGet<T>(path: string, { force = false } = {}): Promise<T> {
  if (!force) {
    const hit = memCache.get(path);
    if (hit && Date.now() - hit.at < FRESH_TTL_MS) return Promise.resolve(hit.data as T);
    const running = inflight.get(path);
    if (running) return running as Promise<T>;
  }
  const p = api<T>(path)
    .then((data) => {
      memCache.set(path, { at: Date.now(), data });
      writeCache(path, data); // и в sessionStorage — для мгновенного рендера потом
      return data;
    })
    .finally(() => { inflight.delete(path); });
  inflight.set(path, p);
  return p;
}

// --- Категории каталога -----------------------------------------------------
// Канонический список и порядок чипов; должен совпадать с Literal в api/routes/admin.py.
// Партнёр без категории попадает в «Другое».

export const CATEGORIES = ['Еда', 'Красота', 'Фитнес', 'Развлечения', 'Шопинг'] as const;

/** Порядок чипов: канон по списку, легаси-значения после, «Другое» всегда в конце. */
export function categoryRank(c: string): number {
  const i = (CATEGORIES as readonly string[]).indexOf(c);
  return i >= 0 ? i : c === 'Другое' ? 999 : 500;
}

// --- Типы ответов ---------------------------------------------------------

export interface Partner {
  id: number;
  name: string;
  category: string | null;
  address: string | null;
  /** Базовая скидка без подписки; 0 — только по подписке */
  discount_free: number;
  discount_premium: number;
  work_hours: string | null;
  logo_url: string | null;
  lat?: number | null;
  lng?: number | null;
}

export interface Me {
  id: number;
  full_name: string | null;
  role: 'buyer' | 'partner' | 'admin';
  subscription: { active: boolean; days_left: number | null; pending: boolean };
  visits: number;
  saved: number;
  daily_sign: string;
  qr_token: string;
}

/** Результат скана QR клиента кассиром (POST /partner/scan). */
export interface ScanResult {
  client_name: string | null;
  discount: number;
  kind: 'free' | 'premium';
  partner_name: string;
}

export interface Visit {
  name: string;
  used_at: string;
  discount: number;
}

export interface Activation {
  partner_name: string;
  discount: number;
  kind: 'free' | 'premium';
  client_name: string | null;
  daily_sign: string;
  server_time: string;
  expires_at: string;
}
