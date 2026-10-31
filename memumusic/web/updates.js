(() => {
  const words = {
    ru: {
      tab: 'Обновления', title: 'Обновления приложения', hint: 'Проверка новых версий, загрузка и установка.',
      current: 'Текущая версия', released: 'Выпуск', check: 'Проверить', checking: 'Проверяем обновления…',
      download: 'Скачать обновление', downloading: 'Скачиваем и проверяем установщик…',
      ready: 'Обновление готово к установке', available: 'Доступна новая версия', latest: 'Установлена последняя доступная версия',
      idle: 'Проверка ещё не выполнялась', failed: 'Не удалось обновить приложение', retry: 'Попробовать снова',
      install: 'Обновить и перезапустить', installPortable: 'Установить новую версию',
      installHint: 'Приложение закроется, установщик обновит его и снова откроет. Ваши файлы и медиатека сохранятся.',
      portableHint: 'Откроется установщик. Выберите папку установки; ваша медиатека сохранится.',
      unsupported: 'Установка доступна в приложении для Windows.', release: 'Открыть страницу версии',
      automatic: 'Автоматически проверять обновления', autoHint: 'Проверка выполняется в фоне и не прерывает музыку.',
      autoDownload: 'Скачивать найденные обновления', downloadHint: 'Установка начнётся только после вашего нажатия.',
      frequency: 'Частота проверки', h6: 'Каждые 6 часов', h12: 'Каждые 12 часов', h24: 'Раз в день', h168: 'Раз в неделю',
      channel: 'Канал обновлений', stable: 'Стабильные версии', preview: 'Стабильные и тестовые',
      channelHint: 'Тестовые версии могут содержать ещё не проверенные изменения.', last: 'Последняя проверка', never: 'ещё не проверяли',
      applying: 'Открываем установщик…', notice: 'Доступно обновление MemuMusic', saved: 'Настройки сохранены',
      network: 'Проверьте подключение к интернету и попробуйте снова.',
      disk: 'Не удалось сохранить файл. Проверьте свободное место и доступ к папке данных.',
      installer_missing: 'В новой версии пока нет установщика и контрольной суммы.',
      invalid_response: 'Сервер вернул некорректные данные об обновлении.', current_version_invalid: 'Не удалось определить текущую версию.',
      checksum_invalid: 'Некорректный файл контрольной суммы.', checksum_mismatch: 'Контрольная сумма не совпадает. Установка остановлена.',
      download_size: 'Файл загрузился не полностью или повреждён.', untrusted_url: 'Адрес файла обновления не прошёл проверку.',
      update_changed: 'Доступная версия изменилась. Проверьте обновления ещё раз.',
      not_downloaded: 'Сначала скачайте обновление.', no_update: 'Сначала проверьте наличие обновления.',
      invalid_settings: 'Не удалось сохранить настройки.', launch_failure: 'Не удалось запустить установщик.',
      unsafe_directory: 'Не удалось безопасно запустить установщик из временной папки.', busy: 'Дождитесь окончания текущей операции.'
    },
    en: {
      tab: 'Updates', title: 'Application updates', hint: 'Check, download and install new versions.',
      current: 'Current version', released: 'Released', check: 'Check for updates', checking: 'Checking for updates…',
      download: 'Download update', downloading: 'Downloading and verifying the installer…',
      ready: 'Update is ready to install', available: 'A new version is available', latest: 'You have the latest available version',
      idle: 'No check has been performed yet', failed: 'Could not update the application', retry: 'Try again',
      install: 'Update and restart', installPortable: 'Install the new version',
      installHint: 'The app will close, the installer will update it, and then reopen it. Your files and library will be kept.',
      portableHint: 'The installer will open so you can choose a folder. Your library will be kept.',
      unsupported: 'Installation is available in the Windows desktop app.', release: 'Open release page',
      automatic: 'Automatically check for updates', autoHint: 'Checks run in the background without interrupting playback.',
      autoDownload: 'Download updates when available', downloadHint: 'Installation begins only when you choose it.',
      frequency: 'Check frequency', h6: 'Every 6 hours', h12: 'Every 12 hours', h24: 'Daily', h168: 'Weekly',
      channel: 'Update channel', stable: 'Stable releases', preview: 'Stable and preview releases',
      channelHint: 'Preview releases may contain changes that are still being tested.', last: 'Last checked', never: 'Not checked yet',
      applying: 'Opening the installer…', notice: 'A MemuMusic update is available', saved: 'Settings saved',
      network: 'Check your internet connection and try again.',
      disk: 'Could not save the file. Check available space and access to the data folder.',
      installer_missing: 'The new release does not include an installer and checksum yet.',
      invalid_response: 'The server returned invalid update information.', current_version_invalid: 'Could not determine the current version.',
      checksum_invalid: 'The checksum file is invalid.', checksum_mismatch: 'The checksum does not match. Installation has been stopped.',
      download_size: 'The downloaded file is incomplete or damaged.', untrusted_url: 'The update address did not pass verification.',
      update_changed: 'The available version changed. Check for updates again.',
      not_downloaded: 'Download the update first.', no_update: 'Check for an update first.',
      invalid_settings: 'Could not save the settings.', launch_failure: 'Could not start the installer.',
      unsafe_directory: 'The installer could not be started safely from the temporary folder.', busy: 'Wait for the current operation to finish.'
    }
  };
  const L = key => (words[App.lang] || words.en)[key] || words.en[key] || key;
  let timer = 0, notified = '';

  async function request(path, body) {
    const response = await fetch('/api/updates/' + path, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'network');
    return value;
  }

  function badge(status) {
    const button = document.querySelector('#nav [data-go="settings"]');
    if (!button) return;
    let badge = button.querySelector('.mm-update-badge');
    if (!badge) { badge = document.createElement('em'); badge.className = 'mm-update-badge'; button.appendChild(badge); }
    const isUpdate = ['available', 'downloading', 'ready', 'installing'].includes(status.phase) && status.latest;
    badge.hidden = !isUpdate && status.phase !== 'error';
    badge.textContent = status.phase === 'error' ? '!' : '•';
    badge.title = L(status.phase === 'error' ? 'failed' : 'notice');
    if (isUpdate && status.latest.version !== notified) {
      notified = status.latest.version;
      if (typeof toast === 'function') toast(L('notice') + ' · ' + status.latest.version);
    }
  }

  async function pollBadge() {
    clearTimeout(timer);
    try {
      const state = await request('status'); badge(state);
      timer = setTimeout(pollBadge, state.busy || ['checking', 'downloading', 'installing'].includes(state.phase) ? 1500 : 30000);
    } catch (_) { timer = setTimeout(pollBadge, 30000); }
  }

  function render(host) {
    let state = null, drawKey = '', pollTimer = 0, about = null;
    host.innerHTML = '<div class="mm-ap mm-updates" aria-live="polite"></div>';
    const root = host.firstElementChild;
    const line = (name, hint, control) => `<div class="mm-ap-line"><div><b>${esc(name)}</b>${hint ? `<p>${esc(hint)}</p>` : ''}</div>${control}</div>`;
    const toggle = (key, checked) => `<label class="mm-switch"><input type="checkbox" data-update-config="${key}" ${checked ? 'checked' : ''} aria-label="${esc(L(key === 'enabled' ? 'automatic' : 'autoDownload'))}"><i></i></label>`;
    const group = (name, hint, content) => `<section class="mm-ap-group"><header><h3>${esc(name)}</h3>${hint ? `<p>${esc(hint)}</p>` : ''}</header>${content}</section>`;

    function draw(next) {
      state = next; badge(next);
      const cfg = next.config || {}, latest = next.latest || null, busy = next.busy || ['checking', 'downloading', 'installing'].includes(next.phase);
      const key = JSON.stringify({ ...next, release_date: about?.release_date || '', progress: 0, total: next.phase === 'downloading' ? 0 : next.total });
      if (drawKey === key) {
        const bar = root.querySelector('progress');
        if (bar) { bar.max = next.total || 1; bar.value = next.progress || 0; }
        const counter = root.querySelector('[data-update-bytes]');
        if (counter && next.total) counter.textContent = `${(next.progress / 1048576).toFixed(1)} / ${(next.total / 1048576).toFixed(1)} MB`;
        return;
      }
      drawKey = key;
      const statusKey = ({ idle: 'idle', checking: 'checking', available: 'available', downloading: 'downloading', ready: 'ready', installing: 'applying', up_to_date: 'latest', error: 'failed' })[next.phase] || 'idle';
      const last = next.last_checked ? new Date(next.last_checked * 1000).toLocaleString(App.lang === 'ru' ? 'ru-RU' : 'en-US') : L('never');
      const rawDate = about?.release_date || '';
      const parsedDate = /^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? new Date(`${rawDate}T12:00:00`) : null;
      const released = parsedDate && !isNaN(parsedDate) ? parsedDate.toLocaleDateString(App.lang === 'ru' ? 'ru-RU' : 'en-US', { day: 'numeric', month: 'long', year: 'numeric' }) : '';
      const details = next.phase === 'error' ? `<p class="mm-update-error">${esc(L(next.error || 'invalid_response'))}</p>` : '';
      const progress = next.phase === 'downloading' ? `<div class="mm-update-progress"><progress max="${next.total || 1}" value="${next.progress || 0}"></progress><small data-update-bytes>${next.total ? `${(next.progress / 1048576).toFixed(1)} / ${(next.total / 1048576).toFixed(1)} MB` : ''}</small></div>` : '';
      const controls = `<div class="mm-update-actions"><button type="button" class="mm-btn ghost sm" data-update-action="check" ${busy ? 'disabled' : ''}>${icon('refresh')}${esc(L(next.phase === 'error' ? 'retry' : 'check'))}</button>
        ${latest && ['available', 'error'].includes(next.phase) ? `<button type="button" class="mm-btn solid sm" data-update-action="download" ${busy ? 'disabled' : ''}>${icon('download')}${esc(L('download'))}</button>` : ''}
        ${next.phase === 'ready' ? `<button type="button" class="mm-btn solid sm" data-update-action="install" ${next.can_install && !busy ? '' : 'disabled'}>${icon('download')}${esc(L(next.installed ? 'install' : 'installPortable'))}</button>` : ''}
        ${latest ? `<button type="button" class="mm-btn ghost sm" data-update-action="release">${esc(L('release'))}</button>` : ''}</div>`;
      const hint = next.phase === 'ready' ? L(next.can_install ? next.installed ? 'installHint' : 'portableHint' : 'unsupported') : '';
      root.innerHTML = group(L('title'), L('hint'), `<div class="mm-update-card"><div class="mm-update-icon">${icon('refresh')}</div><div class="mm-update-copy"><b>${esc(L(statusKey))}${latest ? ' · ' + esc(latest.version) : ''}</b><p>${esc(L('current'))}: ${esc(next.current_version || '')}${released ? ` · ${esc(L('released'))} ${esc(released)}` : ''}</p>${details}${progress}${hint ? `<p>${esc(hint)}</p>` : ''}${controls}<small>${esc(L('last'))}: ${esc(last)}</small></div></div>`)
        + group(L('automatic'), '', line(L('automatic'), L('autoHint'), toggle('enabled', cfg.enabled))
          + line(L('autoDownload'), L('downloadHint'), toggle('auto_download', cfg.auto_download))
          + line(L('frequency'), '', `<select class="mm-input mm-update-select" data-update-config="interval_hours">${[6, 12, 24, 168].map(n => `<option value="${n}" ${cfg.interval_hours === n ? 'selected' : ''}>${esc(L('h' + n))}</option>`).join('')}</select>`)
          + line(L('channel'), L('channelHint'), `<select class="mm-input mm-update-select" data-update-config="channel"><option value="stable" ${cfg.channel === 'stable' ? 'selected' : ''}>${esc(L('stable'))}</option><option value="preview" ${cfg.channel === 'preview' ? 'selected' : ''}>${esc(L('preview'))}</option></select>`));
    }

    async function refresh() {
      clearTimeout(pollTimer);
      if (!host.isConnected) return;
      try {
        if (!about || about.release_date_source === 'fallback') {
          // Пока дата — офлайн-фолбэк, переспрашиваем: фоновая загрузка
          // с GitHub могла уже записать дату в кэш.
          try {
            const info = await fetch('/api/version');
            about = info.ok ? await info.json() : {};
          } catch (_) { about = {}; }
        }
        const next = await request('status');
        if (!host.isConnected) return;
        draw(next);
        pollTimer = setTimeout(refresh, next.busy || ['checking', 'downloading', 'installing'].includes(next.phase) ? 800 : 12000);
      } catch (_) { if (host.isConnected) { root.innerHTML = `<p class="mm-update-error">${esc(L('network'))}</p>`; pollTimer = setTimeout(refresh, 12000); } }
    }

    root.addEventListener('click', async event => {
      const action = event.target.closest('[data-update-action]')?.dataset.updateAction;
      if (!action || !state) return;
      try {
        if (action === 'release') { await App.open({ url: state.latest.page }); return; }
        if (action === 'install') { event.target.disabled = true; toast(L('applying')); await request('install', {}); drawKey = ''; await refresh(); return; }
        await request(action, {}); drawKey = ''; await refresh();
      } catch (error) { toast(L(error.message)); drawKey = ''; await refresh(); }
    });
    root.addEventListener('change', async event => {
      const input = event.target, key = input.dataset.updateConfig;
      if (!key) return;
      const value = input.type === 'checkbox' ? input.checked : key === 'interval_hours' ? Number(input.value) : input.value;
      try {
        await request('settings', { [key]: value });
        if (key === 'channel') await request('check', {});
        else if (value && (key === 'enabled' || key === 'auto_download')) await request('auto', {});
        drawKey = ''; await refresh();
      } catch (error) { toast(L(error.message)); drawKey = ''; await refresh(); }
    });
    refresh();
  }

  SETTINGS_TABS.push({ id: 'updates', order: 70, icon: 'refresh', title: () => L('tab'), render });
  window.MusicUpdates = { status: () => request('status'), check: () => request('check', {}), refresh: pollBadge };
  window.addEventListener('DOMContentLoaded', () => {
    request('auto', {}).catch(() => {}).finally(pollBadge);
    setInterval(() => request('auto', {}).catch(() => {}), 15 * 60 * 1000);
  });
})();
