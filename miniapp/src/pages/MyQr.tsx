import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Placeholder } from '@telegram-apps/telegram-ui';
import { openTelegramLink } from '@telegram-apps/sdk-react';
import QRCodeStyling from 'qr-code-styling';
import { apiBlob, type Me } from './../api';
import { scanPartnerSticker } from './../scan';

const BOT = import.meta.env.VITE_BOT_USERNAME as string | undefined;

/** Аватар-заглушка, когда у клиента нет фото: инициал на градиенте. */
function initialsAvatar(name: string | null, premium: boolean): string {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const grad = g.createLinearGradient(0, 0, 128, 128);
  if (premium) {
    grad.addColorStop(0, '#ff5e2b');
    grad.addColorStop(1, '#ffc069');
  } else {
    grad.addColorStop(0, '#4b5563');
    grad.addColorStop(1, '#6b7280');
  }
  g.fillStyle = grad;
  g.beginPath();
  g.arc(64, 64, 64, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = '#fff';
  g.font = "700 58px 'Golos Text', -apple-system, sans-serif";
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText((name ?? '').trim().charAt(0).toUpperCase() || 'Y', 64, 72);
  return c.toDataURL();
}

/** Фото профиля квадратное — обрезаем в круг, чтобы красиво легло в центр QR. */
async function roundAvatar(blob: Blob): Promise<string> {
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    await new Promise<void>((ok, err) => {
      img.onload = () => ok();
      img.onerror = err;
      img.src = url;
    });
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d')!;
    g.beginPath();
    g.arc(64, 64, 64, 0, Math.PI * 2);
    g.clip();
    g.drawImage(img, 0, 0, 128, 128);
    return c.toDataURL();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Персональный QR клиента (вариант D): кассир сканирует — визит пишется сразу.
 *  Дизайн зависит от подписки: фирменный янтарный для подписчиков, графит без.
 *  Уровень коррекции H — аватар в центре не мешает считыванию. */
export default function MyQr({ me }: { me: Me | null | undefined }) {
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);
  // undefined — аватар грузится (QR ждём, чтобы не перерисовывать), null — фото нет
  const [avatar, setAvatar] = useState<string | null | undefined>(undefined);
  const [scanNote, setScanNote] = useState<string | null>(null);

  const scanSticker = async () => {
    // Второй путь к скидке, не выходя с экрана QR: клиент сам сканирует наклейку
    setScanNote(null);
    try {
      const opened = await scanPartnerSticker(navigate);
      if (!opened) setScanNote('Сканер здесь недоступен — наведите обычную камеру телефона на QR');
    } catch {
      setScanNote('Не удалось открыть сканер — наведите обычную камеру телефона на QR');
    }
  };

  const premium = !!me?.subscription.active;

  useEffect(() => {
    let alive = true;
    apiBlob('/me/avatar')
      .then((b) => (b ? roundAvatar(b) : null))
      .then((u) => { if (alive) setAvatar(u); })
      .catch(() => { if (alive) setAvatar(null); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!me || avatar === undefined || !boxRef.current) return;
    // Deep link: камера телефона откроет Mini App кассира сразу на активации
    const data = BOT ? `https://t.me/${BOT}/app?startapp=c_${me.qr_token}` : `c_${me.qr_token}`;
    const qr = new QRCodeStyling({
      width: 272,
      height: 272,
      type: 'svg',
      data,
      margin: 0,
      qrOptions: { errorCorrectionLevel: 'H' },
      image: avatar ?? initialsAvatar(me.full_name, premium),
      imageOptions: { margin: 4, imageSize: 0.3, crossOrigin: 'anonymous' },
      dotsOptions: premium
        ? {
            type: 'rounded',
            gradient: {
              type: 'linear',
              rotation: Math.PI / 3,
              // Тёмные оттенки бренда: на белой карточке QR остаётся контрастным
              colorStops: [
                { offset: 0, color: '#e2491f' },
                { offset: 1, color: '#b45309' },
              ],
            },
          }
        : { type: 'rounded', color: '#374151' },
      cornersSquareOptions: { type: 'extra-rounded', color: premium ? '#e2491f' : '#16181d' },
      cornersDotOptions: { type: 'dot', color: premium ? '#b45309' : '#16181d' },
      backgroundOptions: { color: 'transparent' },
    });
    boxRef.current.innerHTML = '';
    qr.append(boxRef.current);
  }, [me, avatar, premium]);

  if (me === undefined)
    return (
      <div className="vg-qr">
        <div className="vg-skel" style={{ width: 308, height: 308, borderRadius: 28 }} />
      </div>
    );

  if (me === null)
    return (
      <div className="vg-center">
        <Placeholder header="Нужна регистрация"
                     description="Нажмите Start в боте — QR появится сразу после."
                     action={BOT && (
                       <Button onClick={() => { try { openTelegramLink(`https://t.me/${BOT}`); } catch { /* dev */ } }}>
                         Открыть бота
                       </Button>
                     )} />
      </div>
    );

  return (
    <div className={`vg-qr ${premium ? 'is-premium' : ''}`}>
      <div className="vg-qr-badge">
        {premium ? `Клуб Ynem · подписка · ${me.subscription.days_left} дн.` : 'Без подписки'}
      </div>
      <div className="vg-qr-name vg-display">{me.full_name ?? 'Мой QR'}</div>

      <div className="vg-qr-frame">
        <div className="vg-qr-card" ref={boxRef} />
      </div>

      <div className="vg-qr-note">
        {premium
          ? 'Покажите QR кассиру — он отсканирует, и скидка запишется сразу.'
          : 'Скидки доступны по подписке — оформите её, и QR заработает у всех партнёров.'}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%', maxWidth: 320 }}>
        <Button size="m" mode="white" onClick={() => void scanSticker()}>
          Сканировать QR на кассе
        </Button>
        {!premium && (
          <Button size="m" onClick={() => navigate('/profile')}>Оформить подписку</Button>
        )}
      </div>
      {scanNote && <div className="vg-note is-err">{scanNote}</div>}
    </div>
  );
}
