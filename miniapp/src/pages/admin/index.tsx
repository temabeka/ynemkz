import { useState } from 'react';
import Overview from './Overview';
import Partners from './Partners';
import Users from './Users';
import Broadcast from './Broadcast';
import { Chips } from './chips';

type SectionId = 'overview' | 'partners' | 'users' | 'broadcast';

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: 'overview', label: 'Сводка' },
  { id: 'partners', label: 'Партнёры' },
  { id: 'users', label: 'Люди' },
  { id: 'broadcast', label: 'Рассылка' },
];

export default function Admin() {
  const [section, setSection] = useState<SectionId>('overview');
  return (
    <div className="vg-admin">
      <Chips items={SECTIONS} value={section} onChange={setSection} />
      {section === 'overview' && <Overview />}
      {section === 'partners' && <Partners />}
      {section === 'users' && <Users />}
      {section === 'broadcast' && <Broadcast />}
    </div>
  );
}
