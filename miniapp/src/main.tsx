import React from 'react';
import ReactDOM from 'react-dom/client';
import {
  init,
  backButton,
  themeParams,
  miniApp,
  viewport,
  closingBehavior,
} from '@telegram-apps/sdk-react';
import { AppRoot } from '@telegram-apps/telegram-ui';
import '@telegram-apps/telegram-ui/dist/styles.css';
import './index.css';
import App from './App';

try {
  init(); // вне Telegram бросает — dev в браузере продолжает работать
  if (backButton.mount.isAvailable()) backButton.mount();
  // Тема Telegram → CSS-переменные --tg-theme-* на :root (фон body в index.css)
  if (themeParams.mountSync.isAvailable()) themeParams.mountSync();
  if (themeParams.bindCssVars.isAvailable()) themeParams.bindCssVars();
  if (miniApp.mountSync.isAvailable()) miniApp.mountSync();
  if (miniApp.bindCssVars.isAvailable()) miniApp.bindCssVars();
  // Открытие сразу на весь экран + safe-area инсеты как CSS-переменные
  if (viewport.mount.isAvailable()) {
    void viewport.mount().then(() => {
      try {
        if (viewport.expand.isAvailable()) viewport.expand();
        if (viewport.bindCssVars.isAvailable()) viewport.bindCssVars();
      } catch { /* вне Telegram */ }
    });
  }
  // Подтверждение закрытия включает экран активации (Activate.tsx)
  if (closingBehavior.mount.isAvailable()) closingBehavior.mount();
} catch { /* браузер без Telegram */ }

/** Фирменная тема (стикерный стиль лендинга): светлая — жёлтый фон и бумажные
 *  карточки, тёмная — жёлтый только акцентами. Класс на <html> переключает
 *  токены --yn-* в index.css; сами компоненты про тему не знают. */
function syncBrandTheme() {
  let dark = false;
  try {
    dark = miniApp.isDark();
  } catch {
    // вне Telegram — по системной теме браузера
    dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  }
  document.documentElement.classList.toggle('vg-dark', dark);
  document.documentElement.classList.toggle('vg-light', !dark);
}
syncBrandTheme();
try { miniApp.isDark.sub(syncBrandTheme); } catch { /* вне Telegram */ }

/** Ошибка рендера показывается текстом, а не пустым экраном. */
class Boundary extends React.Component<{ children: React.ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  render() {
    if (this.state.err) {
      return (
        <div style={{ padding: 24, fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap' }}>
          Ошибка приложения:{'\n'}{String(this.state.err)}
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <Boundary>
    <AppRoot>
      <App />
    </AppRoot>
  </Boundary>,
);
