/** Интеграция с Telegram (MainButton/BackButton), загрузка с кэшем
 *  и общие состояния экранов (Loader / ErrorState / PageSkeleton).
 *  Все вызовы SDK в try/catch — в браузере без Telegram хуки тихо бездействуют. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { backButton, mainButton } from '@telegram-apps/sdk-react';
import { Button, Placeholder, Spinner } from '@telegram-apps/telegram-ui';
import { ApiError, apiGet, readCache } from './api';

// Фирменные цвета MainButton: кислотно-жёлтый на чернильном (стиль лендинга)
const BRAND_BG = '#f5ec00';
const BRAND_FG = '#0c0c0c';

/** Системная нижняя кнопка Telegram как главное действие экрана. */
export function useMainButton(
  text: string,
  onClick: () => void,
  { visible = true, enabled = true, loading = false } = {},
) {
  const cb = useRef(onClick);
  cb.current = onClick;

  useEffect(() => {
    try {
      const off = mainButton.onClick(() => cb.current());
      return off;
    } catch { return; }
  }, []);

  useEffect(() => {
    try {
      if (mainButton.mount.isAvailable() && !mainButton.isMounted()) mainButton.mount();
      mainButton.setParams({
        text,
        isVisible: visible,
        isEnabled: enabled && !loading,
        isLoaderVisible: loading,
        backgroundColor: BRAND_BG,
        textColor: BRAND_FG,
      });
    } catch { /* вне Telegram */ }
    return () => {
      try { mainButton.setParams({ isVisible: false }); } catch { /* вне Telegram */ }
    };
  }, [text, visible, enabled, loading]);
}

/** Системная стрелка «назад» в шапке Telegram. */
export function useBackButton(onBack: () => void) {
  const cb = useRef(onBack);
  cb.current = onBack;

  useEffect(() => {
    try {
      if (backButton.show.isAvailable()) backButton.show();
      const off = backButton.onClick(() => cb.current());
      return () => {
        off();
        try { backButton.hide(); } catch { /* вне Telegram */ }
      };
    } catch { return; }
  }, []);
}

/** GET с кэшем: undefined — грузится впервые, null — ошибка без кэша.
 *  Из sessionStorage отдаёт мгновенно; сеть — через apiGet, т.е. свежий
 *  (моложе TTL) ответ берётся из памяти без повторного запроса.
 *  Второй элемент кортежа — retry: сбрасывает ошибку в «загрузку» и повторяет запрос.
 *  Третий — HTTP-статус последней ошибки (403 — не зарегистрирован, 0 — нет сети). */
export function useCachedApi<T>(path: string): [T | null | undefined, () => void, number | null] {
  const [data, setData] = useState<T | null | undefined>(() => readCache<T>(path));
  const [errStatus, setErrStatus] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    // attempt > 0 — пользователь нажал «Повторить»: идём в сеть мимо кэша
    apiGet<T>(path, { force: attempt > 0 })
      .then((fresh) => {
        if (!alive) return;
        setErrStatus(null);
        setData(fresh);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setErrStatus(e instanceof ApiError ? e.status : 0);
        setData((d) => (d === undefined ? null : d));
      });
    return () => { alive = false; };
  }, [path, attempt]);

  const retry = useCallback(() => {
    setData((d) => (d === null ? undefined : d)); // ошибка → снова скелетон
    setAttempt((n) => n + 1);
  }, []);

  return [data, retry, errStatus];
}

/** Плавный набег числа (ease-out, ~0.9 c) — для суммы «Вы сэкономили». */
export function useCountUp(target: number, durationMs = 900): number {
  const [value, setValue] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;
    const start = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min((now - start) / durationMs, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const current = Math.round(from + (target - from) * eased);
      setValue(current);
      if (p < 1) raf = requestAnimationFrame(step);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return value;
}

/** Мерцающая заглушка страницы (fallback для lazy-роутов и первой загрузки). */
export function PageSkeleton() {
  return (
    <div className="vg-page">
      <div className="vg-skel vg-skel-hero" />
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="vg-skel vg-skel-card" />
      ))}
    </div>
  );
}

/** Центрированный спиннер tgui — единый вид «идёт загрузка». */
export function Loader() {
  return (
    <div className="vg-loader">
      <Spinner size="l" />
    </div>
  );
}

/** Экран ошибки сети с кнопкой повтора — единый вид «нет связи».
 *  status — HTTP-код из useCachedApi: мелкой строкой, ускоряет диагностику по скриншоту. */
export function ErrorState({
  onRetry,
  header = 'Нет связи',
  description = 'Проверьте интернет и попробуйте ещё раз.',
  status,
}: {
  onRetry?: () => void;
  header?: string;
  description?: string;
  status?: number | null;
}) {
  return (
    <div className="vg-center">
      <Placeholder
        header={header}
        description={status ? `${description} Код: ${status}.` : description}
        action={onRetry && <Button onClick={onRetry}>Повторить</Button>}
      />
    </div>
  );
}
