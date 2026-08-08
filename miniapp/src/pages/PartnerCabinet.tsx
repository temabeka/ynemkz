import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { openTelegramLink } from '@telegram-apps/sdk-react';
import { Button, Cell, Input, List, Placeholder, Section, Switch } from '@telegram-apps/telegram-ui';
import { api, ApiError, CATEGORIES } from './../api';
import { ErrorState, Loader } from './../hooks';
import { scanClientQr } from './ScanClient';

const BOT = import.meta.env.VITE_BOT_USERNAME as string | undefined;

// Человеческие подписи полей заявки (совпадают с EDIT_FIELDS на бэке)
const EDIT_LABELS: Record<string, string> = {
  name: 'Название', category: 'Категория', address: 'Адрес',
  work_hours: 'Часы работы', avg_check: 'Средний чек, ₸',
};

interface Stats {
  today: number;
  week: number;
  month: number;
  unique_month: number;
  new_clients: number;
  repeat_clients: number;
  by_day: { day: string; visits: number }[];
}

interface Card {
  id: number;
  name: string;
  category: string | null;
  address: string | null;
  work_hours: string | null;
  discount_premium: number;
  avg_check: number | null;
  is_paused: boolean;
  is_owner: boolean;
}

interface Staff {
  user_id: number;
  full_name: string | null;
  username: string | null;
  added_at: string;
}

interface PendingEdit {
  id: number;
  changes: Record<string, string | number>;
  created_at: string;
}

interface EditForm {
  name: string;
  category: string;
  address: string;
  work_hours: string;
  avg_check: string;
}

// Пределы «Моей скидки» — как в bot/services/partners.py (10–15, раздел 3.3)
const DISCOUNTS = [10, 11, 12, 13, 14, 15];

interface Activation {
  full_name: string | null;
  used_at: string;
  discount: number;
}

type StatsState = Stats | 'loading' | 'forbidden' | 'error';

export default function PartnerCabinet() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsState>('loading');
  const [scanNote, setScanNote] = useState<string | null>(null);
  const [card, setCard] = useState<Card | null>(null);
  // undefined — лента грузится, null — не загрузилась
  const [feed, setFeed] = useState<Activation[] | null | undefined>(undefined);
  const [code, setCode] = useState('');
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [redeeming, setRedeeming] = useState(false);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffQuery, setStaffQuery] = useState('');
  const [staffNote, setStaffNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [staffBusy, setStaffBusy] = useState(false);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [discountNote, setDiscountNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [pendingEdit, setPendingEdit] = useState<PendingEdit | null>(null);
  const [editForm, setEditForm] = useState<EditForm | null>(null);
  const [editNote, setEditNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [editBusy, setEditBusy] = useState(false);

  const load = () => {
    api<Stats>('/partner/stats')
      .then(setStats)
      .catch((e: unknown) => {
        // 401/403 — не партнёр; остальное — сеть
        const forbidden = e instanceof ApiError && (e.status === 401 || e.status === 403);
        setStats(forbidden ? 'forbidden' : 'error');
      });
    api<Card>('/partner/me')
      .then((c) => {
        setCard(c);
        setEditForm({
          name: c.name, category: c.category ?? '', address: c.address ?? '',
          work_hours: c.work_hours ?? '', avg_check: c.avg_check ? String(c.avg_check) : '',
        });
        // Сотрудники и заявка — только владельцу
        if (c.is_owner) {
          api<Staff[]>('/partner/staff').then(setStaff).catch(() => {});
          api<PendingEdit | null>('/partner/edit').then(setPendingEdit).catch(() => {});
        }
      })
      .catch(() => {});
    api<Activation[]>('/partner/activations').then(setFeed).catch(() => setFeed(null));
  };
  useEffect(load, []);

  const scanClient = async () => {
    // Системный сканер Telegram; недоступен (десктоп/старый клиент) — фолбэк-код ниже
    setScanNote(null);
    try {
      const opened = await scanClientQr(navigate);
      if (!opened) setScanNote('Сканер недоступен на этом устройстве — введите код клиента ниже');
    } catch {
      setScanNote('Не удалось открыть сканер — введите код клиента ниже');
    }
  };

  const redeem = async () => {
    setResult(null);
    setRedeeming(true);
    try {
      const r = await api<{ client_name: string | null }>('/partner/redeem', {
        method: 'POST',
        body: JSON.stringify({ code: code.trim().toUpperCase() }),
      });
      setResult({ ok: true, text: `Визит записан: ${r.client_name ?? 'клиент'}` });
      setCode('');
      load();
    } catch (e) {
      setResult({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
    setRedeeming(false);
  };

  const togglePause = async (paused: boolean) => {
    // Оптимистично; при ошибке сети возвращаем как было
    setCard((c) => (c ? { ...c, is_paused: paused } : c));
    try {
      await api('/partner/pause', { method: 'POST', body: JSON.stringify({ paused }) });
    } catch {
      setCard((c) => (c ? { ...c, is_paused: !paused } : c));
    }
  };

  const setDiscount = async (value: number) => {
    if (!card || value === card.discount_premium) return;
    const prev = card.discount_premium;
    setDiscountNote(null);
    setCard((c) => (c ? { ...c, discount_premium: value } : c)); // оптимистично
    try {
      await api('/partner/discount', { method: 'POST', body: JSON.stringify({ discount: value }) });
      setDiscountNote({ ok: true, text: `Скидка подписчикам теперь −${value}%` });
    } catch (e) {
      setCard((c) => (c ? { ...c, discount_premium: prev } : c)); // откат
      setDiscountNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
  };

  const addStaff = async () => {
    setStaffNote(null);
    setStaffBusy(true);
    try {
      await api('/partner/staff', {
        method: 'POST',
        body: JSON.stringify({ query: staffQuery.trim() }),
      });
      setStaffNote({ ok: true, text: 'Кассир добавлен — пинги активаций теперь приходят и ему' });
      setStaffQuery('');
      api<Staff[]>('/partner/staff').then(setStaff).catch(() => {});
    } catch (e) {
      setStaffNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
    setStaffBusy(false);
  };

  // Поля, реально отличающиеся от текущей карточки (их и отправляем)
  const editDiff = (): Record<string, string | number> => {
    if (!editForm || !card) return {};
    const out: Record<string, string | number> = {};
    if (editForm.name.trim() && editForm.name.trim() !== card.name) out.name = editForm.name.trim();
    if (editForm.category && editForm.category !== (card.category ?? '')) out.category = editForm.category;
    if (editForm.address.trim() && editForm.address.trim() !== (card.address ?? '')) out.address = editForm.address.trim();
    if (editForm.work_hours.trim() && editForm.work_hours.trim() !== (card.work_hours ?? '')) out.work_hours = editForm.work_hours.trim();
    const check = Number(editForm.avg_check);
    if (editForm.avg_check && check !== (card.avg_check ?? 0)) out.avg_check = check;
    return out;
  };

  const submitEdit = async () => {
    setEditNote(null);
    setEditBusy(true);
    try {
      const created = await api<PendingEdit>('/partner/edit', {
        method: 'POST', body: JSON.stringify(editDiff()),
      });
      setPendingEdit(created);
      setEditNote({ ok: true, text: 'Заявка отправлена админу — изменения появятся после одобрения' });
    } catch (e) {
      setEditNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
    setEditBusy(false);
  };

  const cancelEdit = async () => {
    try {
      await api('/partner/edit', { method: 'DELETE' });
      setPendingEdit(null);
      setEditNote(null);
    } catch (e) {
      setEditNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
  };

  const invite = async () => {
    // Одноразовая ссылка (24 ч) → шеринг в Telegram: кассир открывает и сразу привязан
    setStaffNote(null);
    setInviteBusy(true);
    try {
      const { token } = await api<{ token: string }>('/partner/staff/invite', { method: 'POST' });
      const link = `https://t.me/${BOT}?start=staff_${token}`;
      const text = `Приглашение кассиром в «${card?.name ?? 'заведение'}» — откройте ссылку`;
      openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`);
    } catch (e) {
      setStaffNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
    setInviteBusy(false);
  };

  const removeStaff = async (userId: number) => {
    setStaffNote(null);
    try {
      await api(`/partner/staff/${userId}`, { method: 'DELETE' });
      setStaff((s) => s.filter((x) => x.user_id !== userId));
    } catch (e) {
      setStaffNote({ ok: false, text: e instanceof ApiError ? String(e.detail) : 'Ошибка сети' });
    }
  };

  if (stats === 'loading') return <Loader />;
  if (stats === 'error')
    return <ErrorState onRetry={() => { setStats('loading'); load(); }} />;
  if (stats === 'forbidden')
    return (
      <div className="vg-center">
        <Placeholder header="Нет доступа" description="Кабинет доступен партнёрам клуба." />
      </div>
    );

  const max = Math.max(...stats.by_day.map((d) => d.visits), 1);

  return (
    <div className="vg-page vg-stagger">
      {card && (
        <>
          <div className="vg-brand">
            <span className="vg-brand-name">{card.name}</span>
            <span className="vg-brand-city">{card.is_owner ? 'кабинет' : 'кабинет кассира'}</span>
          </div>
          {card.is_owner && (
            <div className="vg-card" style={{ cursor: 'default' }}>
              <div className="vg-card-body">
                <div className="vg-card-name">Пауза («отпуск»)</div>
                <div className="vg-card-meta">Карточка скрывается из каталога и карты</div>
              </div>
              <Switch checked={card.is_paused} onChange={(e) => togglePause(e.target.checked)} />
            </div>
          )}
        </>
      )}

      {card?.is_owner && (
        <>
          <div className="vg-h">Моя скидка подписчикам</div>
          <div className="vg-chips">
            {DISCOUNTS.map((d) => (
              <button key={d}
                      className={`vg-chip ${card.discount_premium === d ? 'is-on' : ''}`}
                      onClick={() => setDiscount(d)}>
                −{d}%
              </button>
            ))}
          </div>
          {discountNote && (
            <div className={`vg-note ${discountNote.ok ? 'is-ok' : 'is-err'}`}>
              {discountNote.text}
            </div>
          )}
        </>
      )}

      <div className="vg-h">Визиты</div>
      <div className="vg-stat-grid">
        <div className="vg-stat">
          <div className="vg-stat-num" style={{ color: 'var(--vg-accent)' }}>{stats.today}</div>
          <div className="vg-stat-cap">сегодня</div>
        </div>
        <div className="vg-stat">
          <div className="vg-stat-num">{stats.week}</div>
          <div className="vg-stat-cap">за неделю</div>
        </div>
        <div className="vg-stat">
          <div className="vg-stat-num">{stats.month}</div>
          <div className="vg-stat-cap">за месяц · {stats.unique_month} уникальных</div>
        </div>
        <div className="vg-stat">
          <div className="vg-stat-num">{stats.new_clients}/{stats.repeat_clients}</div>
          <div className="vg-stat-cap">новые / повторные, 30 дней</div>
        </div>
      </div>

      {stats.by_day.length > 0 && (
        <>
          <div className="vg-h">Последние 30 дней</div>
          <div className="vg-bars">
            {stats.by_day.map((d) => (
              <div key={d.day} title={`${d.day}: ${d.visits}`}
                   style={{ height: `${(d.visits / max) * 100}%` }} />
            ))}
          </div>
        </>
      )}

      <div className="vg-h">QR клиента</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Button stretched size="l" onClick={() => void scanClient()}>
          Сканировать QR клиента
        </Button>
        {scanNote && <div className="vg-note is-err">{scanNote}</div>}
        <div className="vg-empty" style={{ padding: '0 2px' }}>
          Клиент показывает «Мой QR» из профиля — скидка и визит запишутся сразу,
          клиенту сканировать ничего не нужно.
        </div>
      </div>

      <div className="vg-h">Код клиента (фолбэк)</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Input placeholder="A7K2M9" value={code} maxLength={6}
               autoCapitalize="characters" autoCorrect="off"
               onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <Button stretched loading={redeeming} disabled={code.trim().length < 6} onClick={redeem}>
          Записать визит
        </Button>
        {result && (
          <div className={`vg-note ${result.ok ? 'is-ok' : 'is-err'}`}>{result.text}</div>
        )}
      </div>

      {card?.is_owner && editForm && (
        <>
          <div className="vg-h">Моя карточка</div>
          {pendingEdit ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="vg-card" style={{ cursor: 'default' }}>
                <div className="vg-card-body">
                  <div className="vg-card-name">Заявка на модерации у админа</div>
                  {Object.entries(pendingEdit.changes).map(([k, v]) => (
                    <div key={k} className="vg-card-meta">
                      {EDIT_LABELS[k] ?? k}: {String(v)}
                    </div>
                  ))}
                </div>
              </div>
              <Button stretched mode="bezeled" onClick={cancelEdit}>Отменить заявку</Button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Input header="Название" value={editForm.name}
                     onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
              <div className="vg-chips">
                {CATEGORIES.map((c) => (
                  <button key={c}
                          className={`vg-chip ${editForm.category === c ? 'is-on' : ''}`}
                          onClick={() => setEditForm({ ...editForm, category: c })}>
                    {c}
                  </button>
                ))}
              </div>
              <Input header="Адрес" value={editForm.address}
                     onChange={(e) => setEditForm({ ...editForm, address: e.target.value })} />
              <Input header="Часы работы" placeholder="Пн–Вс 10:00–22:00" value={editForm.work_hours}
                     onChange={(e) => setEditForm({ ...editForm, work_hours: e.target.value })} />
              <Input header="Средний чек, ₸" inputMode="numeric" value={editForm.avg_check}
                     onChange={(e) => setEditForm({ ...editForm, avg_check: e.target.value.replace(/\D/g, '') })} />
              <Button stretched loading={editBusy}
                      disabled={Object.keys(editDiff()).length === 0} onClick={submitEdit}>
                Отправить на модерацию
              </Button>
              <div className="vg-empty" style={{ padding: '0 2px' }}>
                Изменения публикуются после одобрения админом. Координаты на карте
                и логотип меняет админ — напишите ему через «Помощь» в боте.
              </div>
            </div>
          )}
          {editNote && (
            <div className={`vg-note ${editNote.ok ? 'is-ok' : 'is-err'}`}>{editNote.text}</div>
          )}

          <div className="vg-h">Сотрудники</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {staff.length > 0 && (
              <List>
                <Section>
                  {staff.map((s) => (
                    <Cell key={s.user_id}
                          subtitle={s.username ? `@${s.username}` : `id ${s.user_id}`}
                          after={
                            <Button size="s" mode="plain" onClick={() => removeStaff(s.user_id)}>
                              Удалить
                            </Button>
                          }>
                      {s.full_name ?? 'Кассир'}
                    </Cell>
                  ))}
                </Section>
              </List>
            )}
            {BOT && (
              <Button stretched loading={inviteBusy} onClick={invite}>
                Пригласить по ссылке
              </Button>
            )}
            <Input placeholder="@username кассира" value={staffQuery}
                   autoCapitalize="none" autoCorrect="off"
                   onChange={(e) => setStaffQuery(e.target.value)} />
            <Button stretched mode="bezeled" loading={staffBusy}
                    disabled={staffQuery.trim().length < 4} onClick={addStaff}>
              Добавить по @username
            </Button>
            {staffNote && (
              <div className={`vg-note ${staffNote.ok ? 'is-ok' : 'is-err'}`}>{staffNote.text}</div>
            )}
            <div className="vg-empty" style={{ padding: '4px 2px' }}>
              Проще всего — «Пригласить по ссылке»: отправьте её кассиру в Telegram,
              он откроет и сразу привязан. Ссылка одноразовая, действует 24 часа.
              Кассир получает пинги активаций и может гасить коды.
            </div>
          </div>
        </>
      )}

      <div className="vg-h">Последние активации</div>
      {feed === undefined ? (
        <div className="vg-skel vg-skel-card" />
      ) : feed === null ? (
        <div className="vg-empty">Не удалось загрузить активации</div>
      ) : feed.length === 0 ? (
        <div className="vg-empty">Пока нет активаций — они появятся здесь сразу после QR</div>
      ) : (
        <List>
          <Section>
            {feed.map((a, i) => (
              <Cell key={i}
                    subtitle={new Date(a.used_at).toLocaleString('ru-RU')}
                    after={<span className="vg-pct">−{a.discount}%</span>}>
                {a.full_name ?? 'Клиент'}
              </Cell>
            ))}
          </Section>
        </List>
      )}
    </div>
  );
}
