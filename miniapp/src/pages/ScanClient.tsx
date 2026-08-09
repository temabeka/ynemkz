import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Placeholder, Spinner } from '@telegram-apps/telegram-ui';
import { hapticFeedback, qrScanner } from '@telegram-apps/sdk-react';
import { api, ApiError, type ScanResult } from './../api';

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; data: ScanResult }
  | { kind: 'fail'; header: string; message: string };

/** Токен из содержимого QR: deep link t.me/...startapp=c_<token> или голый токен. */
export function tokenFromQr(content: string): string | null {
  const m = /c_([A-Za-z0-9_-]{8,64})/.exec(content);
  return m ? m[1] : null;
}

/** Открыть системный сканер Telegram и уйти на экран результата. */
export async function scanClientQr(navigate: (to: string) => void): Promise<boolean> {
  if (!qrScanner.open.isAvailable()) return false;
  const content = await qrScanner.open({
    text: 'Наведите камеру на QR клиента',
    capture: (q) => tokenFromQr(q) !== null, // чужие QR не закрывают сканер
  });
  const token = content ? tokenFromQr(content) : null;
  if (token) navigate(`/scan/${token}`);
  return true;
}

/** Результат скана QR клиента кассиром (вариант D, раздел 3.2).
 *  Визит записывается при открытии экрана — те же правила, что у наклейки. */
export default function ScanClient() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    setState({ kind: 'loading' });
    api<ScanResult>('/partner/scan', {
      method: 'POST',
      body: JSON.stringify({ qr: token ?? '' }),
    })
      .then((data) => {
        setState({ kind: 'ok', data });
        try { hapticFeedback.notificationOccurred('success'); } catch { /* браузер */ }
      })
      .catch((e: unknown) => {
        try { hapticFeedback.notificationOccurred('error'); } catch { /* браузер */ }
        if (!(e instanceof ApiError)) {
          setState({ kind: 'fail', header: 'Нет связи', message: 'Проверьте интернет и попробуйте ещё раз.' });
          return;
        }
        const detail = String(e.detail);
        // Скан открыл не кассир: роль buyer (403 forbidden), нет заведения (404
        // partner profile) или вовсе не зарегистрирован (401/403 от auth)
        const notCashier =
          (e.status === 404 && detail.includes('partner profile')) ||
          (e.status === 401) ||
          (e.status === 403 && /forbidden|registered/.test(detail));
        if (notCashier) {
          setState({
            kind: 'fail', header: 'Только для кассиров',
            message: 'Это персональный QR клиента клуба — сканировать его может кассир заведения-партнёра.',
          });
        } else if (e.status === 402) {
          setState({ kind: 'fail', header: 'Скидка недоступна', message: detail });
        } else {
          setState({ kind: 'fail', header: 'Не получилось', message: detail });
        }
      });
  }, [token]);

  if (state.kind === 'loading')
    return (
      <div className="vg-act">
        <Spinner size="l" />
        <div className="vg-act-note">Записываем визит…</div>
      </div>
    );

  if (state.kind === 'fail')
    return (
      <div className="vg-center">
        <Placeholder
          header={state.header}
          description={state.message}
          action={
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <Button onClick={() => void scanClientQr(navigate).catch(() => {})}>
                Сканировать ещё
              </Button>
              <Button mode="gray" onClick={() => navigate('/cabinet')}>В кабинет</Button>
            </div>
          }
        />
      </div>
    );

  const { data } = state;
  return (
    <div className="vg-act">
      <div className="vg-act-kind">
        {data.kind === 'free' ? 'Скидка без подписки' : 'Скидка по подписке'} · визит записан
      </div>
      <div className="vg-act-partner">{data.client_name ?? 'Клиент'}</div>
      <div className="vg-act-pct">−{data.discount}%</div>
      <div className="vg-act-client">
        {data.partner_name} · {new Date().toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
      </div>
      <div className="vg-act-note">
        Скидка активирована, клиенту ушло подтверждение в бот. Экран можно закрывать.
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <Button mode="white" onClick={() => void scanClientQr(navigate).catch(() => {})}>
          Сканировать ещё
        </Button>
        <Button mode="outline" onClick={() => navigate('/cabinet')}>В кабинет</Button>
      </div>
    </div>
  );
}
