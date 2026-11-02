'use strict';
/* Веб-панель выделенного сервера Counter-Strike 1.5. Одностраничник без сборки и внешних библиотек.
   Всё, что приходит от сервера (имена игроков, строки логов), считается чужим текстом и
   выводится только через esc() или textContent: имя игрока задаёт кто угодно из интернета.
   Встроенные onclick запрещены политикой страницы, поэтому кнопки работают через data-act
   и общий обработчик. */

// ============================================================ языки
/* Исходный язык панели — русский: каждая надпись в коде обёрнута в L('…') и сама служит
   ключом перевода. Словарь выбранного языка (static/i18n/<код>.js) подключает boot.js ещё до
   этого файла. {0}, {1}… в ключе — места для чисел и имён: L('Заходов: {0}', n).
   Нет перевода — остаётся русский текст. */

const I18N = window.PANEL_I18N || null;
const LANG = document.documentElement.lang || 'ru';
const LANGS = window.PANEL_LANGS || [['ru', 'Русский', 'ru-RU']];
const LOCALE = LANGS.reduce((a, x) => (x[0] === LANG ? x[2] : a), 'ru-RU');

function L(key, ...args) {
  let text = I18N && I18N[key];
  if (typeof text !== 'string' || !text) text = key;
  else if (key[0] === ' ' || key[key.length - 1] === ' ') {
    // пробелы по краям — часть склейки в коде, в переводе их держать не нужно
    text = key.match(/^ */)[0] + text.trim() + key.match(/ *$/)[0];
  }
  return args.length ? text.replace(/\{(\d+)\}/g, (m, n) => (args[n] == null ? '' : String(args[n]))) : text;
}

/* Одна русская надпись с разным смыслом: Lx('контекст', 'текст') ищет «контекст|текст»,
   а нет такого — обычный перевод. */
function Lx(ctx, key) { return (I18N && typeof I18N[ctx + '|' + key] === 'string' && I18N[ctx + '|' + key]) || L(key); }

/* Текст, который прислал сервер (ошибки, подписи настроек, записи журнала), переводится тем же
   словарём: сначала строка целиком, потом по образцам с {0} — «нет на сервере: {0}» узнаёт и
   «нет на сервере: stalkyard». Ответы самого движка (английские) остаются как есть. */
let srvPatterns = null;
function Lsrv(text) {
  if (!I18N || typeof text !== 'string' || !text) return text;
  if (typeof I18N[text] === 'string') return I18N[text];
  if (!srvPatterns) {
    const rx = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    srvPatterns = Object.keys(I18N).filter((k) => /\{\d+\}/.test(k) && typeof I18N[k] === 'string').map((k) => {
      const order = [];
      const re = rx(k).replace(/\\\{(\d+)\\\}/g, (m, n) => { order.push(+n); return '([\\s\\S]+?)'; });
      return [new RegExp('^' + re + '$'), k, order, k.replace(/\{\d+\}/g, '').length];
    });
    // сначала образцы, где больше постоянного текста
    srvPatterns.sort((a, b) => b[3] - a[3]);
  }
  return text.split('\n').map((line) => {
    if (!line.trim() || !/[А-Яа-яЁё]/.test(line)) return line;
    if (typeof I18N[line] === 'string') return I18N[line];
    for (const [re, k, order] of srvPatterns) {
      const m = line.match(re);
      if (!m) continue;
      const args = [];
      order.forEach((n, i) => { args[n] = Lsrv(m[i + 1]); });
      return L(k, ...args);
    }
    return line;
  }).join('\n');
}

// поля ответов сервера, где приходит его собственный русский текст
const SRV_FIELDS = new Set(['output', 'title', 'comment', 'section', 'restart_note', 'note', 'action', 'detail', 'help', 'cmd']);
function translateReply(v, depth = 0) {
  if (!I18N || depth > 8 || v == null || typeof v !== 'object') return v;
  if (Array.isArray(v)) { for (const x of v) translateReply(x, depth + 1); return v; }
  for (const k of Object.keys(v)) {
    if (typeof v[k] === 'string') { if (SRV_FIELDS.has(k)) v[k] = Lsrv(v[k]); } else translateReply(v[k], depth + 1);
  }
  return v;
}

/* Число с формой слова: Pn(5, 'заход', 'захода', 'заходов') → «5 заходов». В словаре формы
   лежат объектом под ключом «#заходов»: { one: '{0} visit', other: '{0} visits' } — нужную
   выбирают правила языка (Intl.PluralRules: zero, one, two, few, many, other). */
function plural(n, one, few, many) {
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return one;
  if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
  return many;
}
let pluralRules = null;
function Pn(n, one, few, many) {
  const forms = I18N && I18N['#' + many];
  if (forms && typeof forms === 'object') {
    pluralRules ||= new Intl.PluralRules(LOCALE);
    return (forms[pluralRules.select(n)] || forms.other || '{0}').replace('{0}', num(n));
  }
  return num(n) + ' ' + plural(n, one, few, many);
}

// ============================================================ утилиты

const S = { csrf: '', page: 'overview', timers: [], statsTab: 'humans', map: '' };
// все кнопки с data-act: имя действия → обработчик (см. onAction)
const ACTIONS = {};
// Название, адрес, ссылка «Все панели» и что есть у сервера (Docker, перезапуск, боты, консоль,
// картинки карт, музыка, звуки меню) — из /api/me, то есть из .env и папки static
const SITE = { title: '', hub: '', address: '', features: {}, music: [] };
const F = (k) => !!(SITE.features && SITE.features[k]);
// какие боты на сервере: YaPB (Counter-Strike, yapb.cfg) или jk_botti (Half-Life)
const YAPB = () => F('bots') && SITE.features.bots_kind === 'yapb';
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// значок панели — прицел (свой рисунок, не логотип игры)
const LAMBDA = '<svg class="lambda" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10.5" fill="none" '
  + 'stroke="currentColor" stroke-width="2.6"/><path d="M16 1.5v8M16 22.5v8M1.5 16h8M22.5 16h8" stroke="currentColor" stroke-width="2.6"/>'
  + '<circle cx="16" cy="16" r="2.4" fill="currentColor"/></svg>';
const GAME = 'Counter-Strike 1.5';
// команда игрока: CT или T (пусто — зритель или ещё не выбрал)
const team = (t) => (t === 'CT' ? '<span class="team ct">CT</span>' : t === 'T' ? '<span class="team t">T</span>' : '');
const ICON = {
  play: 'M8 5v14l11-7z',
  pause: 'M6 5h4v14H6zm8 0h4v14h-4z',
  prev: 'M6 6h2v12H6zm3.5 6 8.5 6V6z',
  next: 'M16 6h2v12h-2zM6 18l8.5-6L6 6z',
  volume: 'M3 9v6h4l5 5V4L7 9zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4z',
  mute: 'M3 9v6h4l5 5V4L7 9zm12.6-.4L17 7.2l2.3 2.3 2.3-2.3L23 8.6l-2.3 2.3 2.3 2.3-1.4 1.4-2.3-2.3-2.3 2.3-1.4-1.4 2.3-2.3z',
  note: 'M12 3v10.6A4 4 0 1 0 14 17V7h4V3z',
};
const ico = (k) => '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="' + ICON[k] + '" fill="currentColor"/></svg>';

/* ---------- запросы и уведомления ---------- */

async function api(path, body) {
  const opt = { credentials: 'same-origin' };
  if (body !== undefined) {
    opt.method = 'POST';
    opt.headers = { 'Content-Type': 'application/json', 'X-CSRF': S.csrf };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  let j;
  try { j = await r.json(); } catch (e) { throw new Error(L('Панель ответила не JSON ({0})', r.status)); }
  if (r.status === 401) { showLogin(); throw new Error(L('Нужно войти')); }
  if (!j.ok) throw new Error(j.error ? Lsrv(j.error) : L('Ошибка {0}', r.status));
  return translateReply(j.data);
}

function toast(msg, bad) {
  const t = document.createElement('div');
  t.className = 'toast' + (bad ? ' bad' : '');
  t.textContent = msg;
  $('#toasts').appendChild(t);
  if (bad) sfx.play('launch_deny1');
  setTimeout(() => t.remove(), bad ? 9000 : 4500);
}

async function act(fn, okMsg) {
  try {
    const d = await fn();
    if (okMsg) toast(typeof okMsg === 'function' ? okMsg(d) : okMsg);
    return d;
  } catch (e) { toast(e.message, true); return null; }
}

/* ---------- форматирование ---------- */

const nf = new Intl.NumberFormat(LOCALE);
const num = (n) => nf.format(Number(n) || 0);
const dec = (x, d = 2) => new Intl.NumberFormat(LOCALE, { maximumFractionDigits: d }).format(Number(x) || 0);
function fmtBytes(n) {
  n = Number(n) || 0;
  const u = [L('Б'), L('КБ'), L('МБ'), L('ГБ'), L('ТБ')];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? dec(n, 1) : num(n)) + ' ' + u[i];
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d) return L('{0} д {1} ч', d, h);
  if (h) return L('{0} ч {1} мин', h, m);
  if (m) return L('{0} мин {1} с', m, sec % 60);
  return L('{0} с', sec);
}
function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(LOCALE, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit', year: 'numeric' });
const fmtDateTime = (ts) => new Date(ts * 1000).toLocaleString(LOCALE,
  { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
function sinceIso(iso) {
  const t = Date.parse(iso);
  return isNaN(t) ? '—' : fmtDur((Date.now() - t) / 1000);
}
const pill = (text, kind) => '<span class="pill ' + (kind || '') + '">' + esc(text) + '</span>';
const nowSec = () => Math.floor(Date.now() / 1000);
const times = (n) => Pn(n, 'раз', 'раза', 'раз');
// дни недели с понедельника и названия месяцев — от браузера, на языке панели
const WEEKDAYS = [...Array(7)].map((_, i) => cap(new Date(2024, 0, 1 + i).toLocaleDateString(LOCALE, { weekday: 'short' })));
const monthTitle = (y, m) => (LANG === 'ru'
  ? cap(new Date(y, m, 1).toLocaleDateString(LOCALE, { month: 'long' })) + ' ' + y
  : cap(new Date(y, m, 1).toLocaleDateString(LOCALE, { month: 'long', year: 'numeric' })));

/* Страна — по коду, название даёт браузер на языке панели. Локальная сеть и «?» — словами. */
let regionNames = null;
function countryName(c) {
  if (!c) return '';
  if (/^[A-Z]{2}$/.test(c.code)) {
    try {
      regionNames ||= new Intl.DisplayNames([LOCALE], { type: 'region' });
      return regionNames.of(c.code) || c.name;
    } catch (e) { return c.name; }
  }
  return c.code === 'LAN' ? L('локальная сеть') : L('не определить');
}

function bars(container, items, label, value, opts = {}) {
  container.innerHTML = '';
  if (!items.length) { container.innerHTML = '<div class="empty">' + L('Пока нет данных') + '</div>'; return; }
  const max = opts.max || Math.max(...items.map((i) => i[value])) || 1;
  for (const it of items) {
    const row = document.createElement('div'); row.className = 'bar-row';
    const l = document.createElement('div'); l.textContent = it[label];
    if (opts.mapPreview) { l.className = 'mapname'; l.dataset.mapprev = it[label]; }
    if (opts.flags) l.innerHTML = flagHtml({ code: it.code, name: it[label] }) + ' ' + esc(it[label]);
    const track = document.createElement('div'); track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill' + (opts.muted && opts.muted(it) ? ' muted' : '');
    fill.style.width = (100 * it[value] / max).toFixed(1) + '%';
    track.appendChild(fill);
    const v = document.createElement('div'); v.className = 'num'; v.textContent = opts.fmt ? opts.fmt(it) : num(it[value]);
    if (opts.tip) row.title = opts.tip(it);
    row.append(l, track, v); container.appendChild(row);
  }
}

/* ---------- длинные списки — по страницам ----------
   pagerMount(el, строки, на странице, fill): fill(тело, строки страницы, номер первой) рисует страницу,
   под ней кнопки 1 2 3 … Номер страницы живёт в самом элементе, пока его не перерисуют. */

function pagerMount(el, rows, per, fill) {
  if (!el) return;
  el.classList.add('paged');
  el._pg = { rows, per, fill, page: 0 };
  pagerDraw(el);
}

function pagerDraw(el) {
  const { rows, per, fill } = el._pg;
  const pages = Math.max(1, Math.ceil(rows.length / per));
  const p = Math.max(0, Math.min(el._pg.page, pages - 1));
  el._pg.page = p;
  el.innerHTML = '<div class="pg-body"></div>' + (pages > 1 ? pagerNav(p, pages, rows.length, per) : '');
  fill(el.firstChild, rows.slice(p * per, (p + 1) * per), p * per);
}

function pagerNav(p, pages, total, per) {
  let html = '', prev = -1;
  for (let i = 0; i < pages; i++) {
    if (i && i !== pages - 1 && Math.abs(i - p) > 2) continue;
    if (i - prev > 1) html += '<span class="pg-gap">…</span>';
    html += `<button class="pg${i === p ? ' active' : ''}" data-act="pg" data-p="${i}">${i + 1}</button>`;
    prev = i;
  }
  return `<div class="pager"><button class="pg" data-act="pg" data-p="${p - 1}" ${p ? '' : 'disabled'}>←</button>${html}
    <button class="pg" data-act="pg" data-p="${p + 1}" ${p < pages - 1 ? '' : 'disabled'}>→</button>
    <span class="muted fs12 pg-count">${L('{0}–{1} из {2}', num(p * per + 1), num(Math.min(total, (p + 1) * per)), num(total))}</span></div>`;
}

ACTIONS.pg = (d, b) => {
  const el = b.closest('.paged');
  if (!el || !el._pg) return;
  el._pg.page = Number(d.p);
  pagerDraw(el);
};

// столбики по страницам: шкала общая для всего списка
const barsPaged = (el, items, label, value, per, opts = {}) => pagerMount(el, items, per, (body, part) => {
  body.innerHTML = '<div class="bars"></div>';
  bars(body.firstChild, part, label, value, { ...opts, max: Math.max(1, ...items.map((i) => i[value])) });
});

/* ---------- превью карт: картинка при наведении на название ----------
   Картинки — static/maps/<карта>.jpg (640×360) и static/maps/thumb/<карта>.jpg (192×108).
   Их рисует tools/build_assets.py прямо из .bsp карт сервера — см. README. */

const previewSrc = (m) => '/static/maps/' + encodeURIComponent(m) + '.jpg';
const thumbSrc = (m) => '/static/maps/thumb/' + encodeURIComponent(m) + '.jpg';
const mapLink = (m) => '<span class="mapname" data-mapprev="' + esc(m) + '">' + esc(m) + '</span>';
const noImg = () => L('нет картинки');

function initMapTip() {
  const tip = document.createElement('div');
  tip.className = 'map-tip hidden';
  tip.innerHTML = '<img alt=""><div class="cap"></div>';
  document.body.appendChild(tip);
  const img = tip.querySelector('img'), capEl = tip.querySelector('.cap');
  let cur = null;
  img.addEventListener('error', () => { img.classList.add('hidden'); capEl.textContent = L('{0} — картинки нет', cur); });
  const place = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight, gap = 16;
    let left = x + gap, top = y + gap;
    if (left + w > innerWidth - 8) left = Math.max(8, x - w - gap);
    if (top + h > innerHeight - 8) top = Math.max(8, y - h - gap);
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  };
  const show = (el, x, y) => {
    const m = el.dataset.mapprev;
    if (m !== cur) {
      cur = m;
      capEl.textContent = m;
      img.classList.remove('hidden');
      img.src = previewSrc(m);
    }
    tip.classList.remove('hidden');
    place(x, y);
  };
  const hide = () => tip.classList.add('hidden');
  const target = (e) => e.target.closest && e.target.closest('[data-mapprev]');
  document.addEventListener('mouseover', (e) => { const el = target(e); if (el) show(el, e.clientX, e.clientY); });
  document.addEventListener('mousemove', (e) => {
    if (tip.classList.contains('hidden')) return;
    if (target(e)) place(e.clientX, e.clientY); else hide();
  });
  document.addEventListener('mouseout', (e) => { const el = target(e); if (el && !el.contains(e.relatedTarget)) hide(); });
  // телефон: касание названия показывает картинку, касание мимо — прячет
  document.addEventListener('touchstart', (e) => {
    const el = target(e);
    if (el) show(el, e.touches[0].clientX, e.touches[0].clientY); else hide();
  }, { passive: true });
  document.addEventListener('dragstart', hide);
  document.addEventListener('click', (e) => { if (!target(e)) hide(); });
  window.addEventListener('scroll', hide, true);
  S.hideTip = hide;  // при переходе между разделами и открытии окна
}

// ============================================================ оформление, звуки и музыка
/* Три оформления: «Counter-Strike 1.5» (по умолчанию: цвета и шрифты старого меню WON —
   оранжевый на чёрном, фон — пустыня, ночь или текущая карта), «Steam 2003» (оливковое, как
   меню Counter-Strike 1.6) и «Обычный» — светлая или тёмная тема.
   Выбор хранится в браузере (localStorage), ставит его boot.js ещё до отрисовки. */

const pref = {
  get(k, d) { try { const v = localStorage.getItem('cspanel-' + k); return v == null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('cspanel-' + k, v); } catch (e) { /* приватный режим */ } },
  del(k) { try { localStorage.removeItem('cspanel-' + k); } catch (e) { /* приватный режим */ } },
};
const PREF_KEYS = ['lang', 'style', 'bg', 'theme', 'music', 'volume', 'muted', 'player', 'sfx'];
const STYLES = ['hl', 'steam', 'plain'];
const BGS = ['dust', 'night', 'map'];
const styleNow = () => (STYLES.includes(document.documentElement.getAttribute('data-style'))
  ? document.documentElement.getAttribute('data-style') : 'hl');
const LEGAL = () => L('Counter-Strike® и Half-Life® — товарные знаки Valve Corporation. Панель никак не связана с Valve. Картинки карт, '
  + 'звуки меню и заставка собираются из вашей собственной копии игры (tools/build_assets.py) и в репозиторий не входят. '
  + 'Музыка — CC0, шрифты — SIL Open Font License, флаги — flag-icons (MIT).');

function setStyle(k) {
  pref.set('style', k);
  document.documentElement.setAttribute('data-style', k);
  syncLoginVideo();
}
function setBg(k) {
  pref.set('bg', k);
  document.documentElement.setAttribute('data-bg', k);
  applyMapBg();
}
// фон «Текущая карта» — картинка той карты, что играет (её узнаёт sideStatus)
function applyMapBg() {
  const d = document.documentElement;
  if (S.map && F('art')) d.style.setProperty('--bg-map', 'url("' + previewSrc(S.map) + '")');
  else d.style.removeProperty('--bg-map');
}
// заставка на экране входа — вращающийся логотип из меню игры (static/hl/logo.webm)
function syncLoginVideo() {
  const v = $('#login-video');
  if (!v) return;
  const on = F('logo') && styleNow() === 'hl';
  v.classList.toggle('hidden', !on);
  if (on) { if (!v.getAttribute('src')) v.src = '/static/hl/logo.webm'; v.play().catch(() => {}); } else v.pause();
}

/* Звуки меню — те самые launch_*.wav из меню игры (static/hl/sfx, собирает tools/build_assets.py):
   наведение на раздел, нажатие, ошибка, открытие и закрытие окна. Только в оформлениях игры. */
const sfx = {
  cache: {},
  on() { return F('sfx') && styleNow() !== 'plain' && pref.get('sfx', 'on') === 'on'; },
  play(name) {
    if (!this.on()) return;
    let a = this.cache[name];
    if (!a) { a = this.cache[name] = new Audio('/static/hl/sfx/' + name + '.wav'); a.preload = 'auto'; }
    a.volume = 0.5;
    try { a.currentTime = 0; } catch (e) { /* ещё не загружен */ }
    a.play().catch(() => {});
  },
};

/* Музыка играет по кругу: первой — первая мелодия списка, дальше вперемешку. Браузер не даёт
   включить звук, пока человек ничего не нажал, поэтому музыка начинается с первого клика
   или клавиши (если её не выключили). Мелодии — static/music (tracks.json — названия и авторы). */
const music = {
  audio: null, order: [], idx: 0, started: false, listeners: new Set(),
  tracks() { return SITE.music || []; },
  wanted() { return playerOn() && pref.get('music', 'on') === 'on'; },
  volume() { const v = Number(pref.get('volume', '0.35')); return isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.35; },
  init() {
    if (this.audio || !this.tracks().length) return;
    const a = new Audio();
    a.preload = 'none';
    a.volume = this.volume();
    a.muted = this.muted();
    a.addEventListener('ended', () => this.next());
    a.addEventListener('play', () => this.emit());
    a.addEventListener('pause', () => this.emit());
    a.addEventListener('error', () => { if (this.started) setTimeout(() => this.next(), 1500); });
    this.audio = a;
    const rest = this.tracks().slice(1).map((_, i) => i + 1);
    for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]]; }
    this.order = [0, ...rest];
    const kick = (e) => {
      if (e.target && e.target.closest && e.target.closest('[data-music]')) return;
      if (this.wanted() && !this.started) this.play();
    };
    document.addEventListener('pointerdown', kick, true);
    document.addEventListener('keydown', kick, true);
  },
  track() { const t = this.tracks(); return t[this.order[this.idx % this.order.length]] || t[0] || { file: '', title: '' }; },
  load() { this.audio.src = '/static/music/' + encodeURIComponent(this.track().file); },
  play() {
    this.init();
    if (!this.audio) return;
    if (!this.audio.getAttribute('src')) this.load();
    this.started = true;
    this.audio.play().catch(() => { this.started = false; this.emit(); });
    this.emit();
  },
  playing() { return !!(this.audio && !this.audio.paused); },
  toggle() {
    const on = !this.playing();
    pref.set('music', on ? 'on' : 'off');
    if (on) this.play(); else if (this.audio) this.audio.pause();
    this.emit();
  },
  next() { this.step(1); },
  prev() { this.step(-1); },
  step(dir) {
    this.init();
    if (!this.audio) return;
    this.idx = (this.idx + dir + this.order.length) % this.order.length;
    this.load();
    pref.set('music', 'on');      // «назад/вперёд» включают музыку, даже если стояла пауза
    this.started = true;
    this.audio.play().catch(() => { this.started = false; this.emit(); });
    this.emit();
  },
  muted() { return pref.get('muted', '0') === '1'; },
  toggleMute() {
    const m = !this.muted();
    pref.set('muted', m ? '1' : '0');
    if (this.audio) this.audio.muted = m;
    this.emit();
  },
  pick(n) {
    this.init();
    if (!this.audio) return;
    const at = this.order.indexOf(n);
    this.idx = at >= 0 ? at : 0;
    this.load();
    pref.set('music', 'on');
    this.play();
  },
  setVolume(v) {
    pref.set('volume', String(v));
    if (this.audio) this.audio.volume = v;
    if (v > 0 && this.muted()) this.toggleMute();      // подвинули громкость — значит, звук нужен
    this.emit();
  },
  emit() {
    for (const fn of [...this.listeners]) {
      if (fn.el && !fn.el.isConnected) this.listeners.delete(fn); else fn();
    }
  },
  watch(el, fn) { fn.el = el; this.listeners.add(fn); fn(); },
};

/* Плеер внизу меню и на экране входа: название мелодии (крестик справа убирает плеер) и кнопки
   «назад», «играть/пауза», «вперёд», «звук» с ползунком громкости. Убранный плеер не играет
   музыку; вернуть — в «Настройках панели». */
const playerOn = () => music.tracks().length > 0 && pref.get('player', 'on') !== 'off';

function setPlayer(on) {
  pref.set('player', on ? 'on' : 'off');
  if (!on) {
    if (music.audio) music.audio.pause();
    music.started = false;      // вернут плеер — музыка снова начнётся с первого клика
  }
  fillPlayers();
  music.emit();
}

function fillPlayers() {
  for (const slot of document.querySelectorAll('.mus-slot')) {
    slot.innerHTML = playerOn() ? musicWidget() : '';
    const box = slot.firstElementChild;
    if (box) music.watch(box, () => updateWidget(box));
  }
}

function musicWidget() {
  const b = (act, label, icon, cls = '') => '<button class="mus-b' + cls + '" type="button" data-music="1" data-act="' + act
    + '" title="' + esc(label) + '" aria-label="' + esc(label) + '">' + ico(icon) + '</button>';
  return '<div class="mus" data-music="1"><div class="mus-head">' + ico('note') + '<span class="mus-name"></span>'
    + '<button class="mus-b mus-x" type="button" data-music="1" data-act="mus-hide" title="'
    + esc(L('Убрать плеер — вернуть можно в «Настройках панели»')) + '">×</button></div>'
    + '<div class="mus-ctrl">' + b('mus-prev', L('Предыдущая мелодия'), 'prev') + b('mus-play', L('Играть'), 'play', ' mus-play')
    + b('mus-next', L('Следующая мелодия'), 'next') + b('mus-mute', L('Выключить звук'), 'volume')
    + '<input type="range" class="mus-vol" min="0" max="1" step="0.05" data-music="1" aria-label="' + esc(L('Громкость'))
    + '" title="' + esc(L('Громкость')) + '"></div></div>';
}

function updateWidget(box) {
  const on = music.playing(), muted = music.muted();
  const play = box.querySelector('[data-act="mus-play"]'), mute = box.querySelector('[data-act="mus-mute"]');
  const vol = box.querySelector('.mus-vol'), title = box.querySelector('.mus-name');
  play.innerHTML = ico(on ? 'pause' : 'play');
  play.title = on ? L('Пауза') : L('Играть');
  play.setAttribute('aria-label', play.title);
  play.classList.toggle('on', on);
  mute.innerHTML = ico(muted ? 'mute' : 'volume');
  mute.title = muted ? L('Включить звук') : L('Выключить звук');
  mute.setAttribute('aria-label', mute.title);
  mute.classList.toggle('off', muted);
  if (document.activeElement !== vol) vol.value = String(music.volume());
  title.textContent = on ? (muted ? L('{0} — звук выключен', music.track().title) : music.track().title)
    : music.wanted() ? L('Музыка начнётся с первого клика') : L('Музыка на паузе');
  title.title = title.textContent;
}

ACTIONS['mus-play'] = () => music.toggle();
ACTIONS['mus-prev'] = () => music.prev();
ACTIONS['mus-next'] = () => music.next();
ACTIONS['mus-mute'] = () => music.toggleMute();
ACTIONS['mus-hide'] = () => { setPlayer(false); toast(L('Плеер убран, музыка не играет. Вернуть — в «Настройках панели».')); };
ACTIONS['mus-pick'] = (d) => music.pick(Number(d.n));
document.addEventListener('input', (e) => {
  if (e.target.classList && (e.target.classList.contains('mus-vol') || e.target.id === 'set-vol')) music.setVolume(Number(e.target.value));
});

// ============================================================ Настройки панели
/* Язык, оформление и музыка — всё хранится в этом браузере (localStorage). Та же страница
   открывается окном и с экрана входа. Язык меняется перезагрузкой: словарь подключает boot.js. */

function setLang(code) {
  if (code) pref.set('lang', code); else pref.del('lang');
  location.reload();
}

const seg = (name, options, current) => '<div class="seg" role="group">' + options.map(([k, label]) =>
  '<button type="button" class="' + (k === current ? 'on' : '') + '" data-act="seg" data-seg="' + name + '" data-v="' + k + '">'
  + esc(label) + '</button>').join('') + '</div>';

function settingsHtml(inModal) {
  const style = styleNow();
  const chosen = pref.get('lang', '');
  const langName = (LANGS.find(([c]) => c === LANG) || [LANG, LANG])[1];
  const lang = `<div class="card"><h2>${L('Язык')}${LANG === 'en' ? '' : ' <span class="h-sub">Language</span>'}</h2>
    <div class="chips">
      <button type="button" class="chip${chosen ? '' : ' on'}" data-act="set-lang" data-lang="">${L('Как в браузере')}</button>
      ${LANGS.map(([c, name]) => `<button type="button" lang="${c}" class="chip${chosen === c ? ' on' : ''}${LANG === c ? ' cur' : ''}"
        data-act="set-lang" data-lang="${c}">${esc(name)}</button>`).join('')}
    </div>
    <p class="muted">${L('Сейчас: {0}. Переводы лежат в static/i18n — их можно поправить.', esc(langName))}</p></div>`;

  const about = { hl: L('Меню Counter-Strike 1.5 (WON, 2002): оранжевый на чёрном, шрифты в духе игры, фон на выбор.'),
    steam: L('Оливковое оформление Steam 2003 года — как меню Counter-Strike 1.6.'),
    plain: L('Прежний вид панели: светлая или тёмная тема.') }[style];
  const bgName = { dust: L('Пустыня'), night: L('Ночь'), map: L('Текущая карта') };
  const bgNow = document.documentElement.getAttribute('data-bg') || 'dust';
  const look = `<div class="card"><h2>${L('Оформление')}</h2><div class="stack">
    <div class="field"><span>${L('Стиль')}</span>${seg('style', [['hl', GAME], ['steam', 'Steam 2003'], ['plain', L('Обычный')]], style)}
      <p class="muted">${about}</p></div>
    ${style === 'hl' ? `<div class="field"><span>${L('Фон')}</span><div class="bg-pick">${BGS.filter((k) => k !== 'map' || F('art')).map((k) =>
      `<button type="button" class="bg-opt bg-${k}${bgNow === k ? ' on' : ''}" data-act="seg" data-seg="bg" data-v="${k}"><span>${esc(bgName[k])}</span></button>`).join('')}
      </div></div>` : ''}
    ${style === 'plain' ? `<div class="field"><span>${L('Тема')}</span>${seg('theme', [['light', L('Светлая')], ['dark', L('Тёмная')]],
      document.documentElement.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))}</div>` : ''}
    ${F('sfx') && style !== 'plain' ? `<div class="field"><span>${L('Звуки меню из игры')}</span>${seg('sfx',
      [['on', L('Включены')], ['off', L('Выключены')]], pref.get('sfx', 'on'))}</div>` : ''}
    </div></div>`;

  let mus;
  if (!music.tracks().length) {
    mus = `<div class="card"><h2>${L('Музыка')}</h2><p class="muted">${L('Музыки на сервере нет: положите mp3 в static/music (см. README).')}</p></div>`;
  } else {
    const on = playerOn();
    const cur = music.playing() ? music.track().file : '';
    mus = `<div class="card"><h2>${L('Музыка')}</h2><div class="stack">
      <div class="field"><span>${L('Плеер в меню')}</span>${seg('player', [['on', L('Показывать')], ['off', L('Убрать, музыку не играть')]], on ? 'on' : 'off')}</div>
      ${on ? `<div class="row">
          <button type="button" class="btn${music.playing() ? '' : ' primary'}" data-music="1" data-act="mus-play">${ico(music.playing() ? 'pause' : 'play')}
            ${music.playing() ? L('Пауза') : L('Играть')}</button>
          <button type="button" class="btn" data-music="1" data-act="mus-mute">${ico(music.muted() ? 'mute' : 'volume')}
            ${music.muted() ? L('Включить звук') : L('Выключить звук')}</button>
          <label class="vol">${L('Громкость')} <input id="set-vol" type="range" min="0" max="1" step="0.05" value="${music.volume()}" data-music="1"></label></div>
        <div class="field"><span>${L('Мелодии')}</span><div class="chips">${music.tracks().map((t, n) =>
          `<button type="button" class="chip${t.file === cur ? ' on' : ''}" data-music="1" data-act="mus-pick" data-n="${n}"
            title="${esc(t.author ? t.title + ' — ' + t.author : t.title)}">${t.file === cur ? '♪ ' : ''}${esc(t.title)}</button>`).join('')}</div></div>
        <div class="credits muted">${music.tracks().filter((t) => t.author).map((t) =>
          esc(t.title) + ' — ' + esc(t.author) + (t.license ? ' (' + esc(t.license) + ')' : '')).join(' · ')}</div>`
        : `<p class="muted">${L('Плеер убран, музыка не играет. Выберите «Показывать», чтобы вернуть.')}</p>`}
      </div></div>`;
  }

  const reset = `<div class="card"><h2>${L('Сброс')}</h2>
    <p class="muted">${L('Настройки хранятся только в этом браузере. Сброс вернёт язык браузера, оформление «{0}», фон «Пустыня» и плеер с музыкой.', GAME)}</p>
    <div class="row"><button type="button" class="btn" data-act="prefs-reset">${L('Сбросить настройки')}</button></div></div>`;

  return `<div class="${inModal ? 'stack' : 'grid two settings-grid'}">${lang}${look}${mus}${reset}</div>
    <p class="legal">${LEGAL()}</p>`;
}

function settingsInto(el, inModal) {
  const box = document.createElement('div');
  box.className = 'settings';
  box.dataset.music = '1';
  el.appendChild(box);
  let last = '';
  music.watch(box, () => {
    // ползунок громкости не перерисовываем, пока его тянут
    if (document.activeElement && document.activeElement.id === 'set-vol' && box.contains(document.activeElement)) return;
    const html = settingsHtml(inModal);
    if (html !== last) { box.innerHTML = html; last = html; }
  });
  S.redrawSettings = () => { last = ''; music.emit(); };
}

ACTIONS['set-lang'] = (d) => setLang(d.lang);
ACTIONS['prefs-reset'] = () => { PREF_KEYS.forEach((k) => pref.del(k)); location.reload(); };
ACTIONS.seg = (d) => {
  const v = d.v;
  if (d.seg === 'style') setStyle(v);
  else if (d.seg === 'bg') setBg(v);
  else if (d.seg === 'theme') { document.documentElement.setAttribute('data-theme', v); pref.set('theme', v); }
  else if (d.seg === 'sfx') { pref.set('sfx', v); sfx.play('launch_select2'); }
  else if (d.seg === 'player') setPlayer(v === 'on');
  if (S.redrawSettings) S.redrawSettings();
};
ACTIONS['panel-settings'] = () => {
  const m = openModal('<h2>' + esc(L('Настройки панели')) + '</h2>', 'wide');
  settingsInto(m, true);
};

// ============================================================ каркас и вход

const NAV = () => [
  ['overview', L('Обзор')], ['players', F('bots') ? L('Игроки и боты') : L('Игроки')], ['maps', L('Карты')],
  ['settings', L('Настройки сервера')], ['stats', L('Статистика')], ['logs', L('Логи')], ['console', L('Консоль')],
  ['audit', L('Журнал действий')], ...(F('backups') ? [['backups', L('Бэкап')]] : []), ['panel', L('Настройки панели')],
];

function hubHref() {
  const h = SITE.hub || '';
  if (!h) return '';
  if (/^:\d+/.test(h)) return location.protocol + '//' + location.hostname + h + (h.includes('/') ? '' : '/');
  return /^https?:\/\//.test(h) ? h : '';
}

function renderShell() {
  const title = SITE.title || GAME;
  document.title = title;
  // эмблема игры у заголовка каждой страницы и на вкладке браузера: круглый значок с заставки меню
  // (static/hl/emblem.png, его вырезает tools/build_assets.py), а без него — свой прицел (emblem.svg)
  if (F('emblem')) {
    document.documentElement.style.setProperty('--emblem', 'url("/static/hl/emblem.png")');
    const icon = document.querySelector('link[rel="icon"]');
    if (icon) { icon.type = 'image/png'; icon.href = '/static/hl/emblem.png'; }
  }
  $('#login').innerHTML = `<video id="login-video" class="login-video hidden" muted loop playsinline aria-hidden="true"></video>
    <form id="login-form" class="login-card">
      <div class="brand">${LAMBDA}<span>${esc(title)}</span></div>
      <p class="muted">${L('Панель управления сервером {0}.', GAME)}</p>
      <input id="login-password" type="password" autocomplete="current-password" placeholder="${esc(L('Пароль'))}" required>
      <button type="submit" class="btn primary">${L('Войти')}</button>
      <div id="login-error" class="error"></div>
      <p class="muted fs12">${L('Забыли пароль — на сервере: {0} или {1}.', '<code class="nowrap">python3 app.py --init</code>', '<code class="nowrap">tools/passwd.py</code>')}</p>
    </form>
    <div class="login-foot"><div class="mus-slot"></div>
      <button class="btn small ghost" type="button" data-music="1" data-act="panel-settings">${L('Настройки панели')}</button></div>`;
  const hub = hubHref();
  $('#app').innerHTML = `<aside class="side">
      <div class="brand">${LAMBDA}<span id="side-host">${esc(title)}</span></div>
      <nav id="nav">${NAV().map(([k, label]) => `<a data-page="${k}" href="#${k}">${esc(label)}</a>`).join('')}</nav>
      <div class="side-foot">
        <div id="side-status" class="pill">…</div>
        <div class="mus-slot"></div>
        <div class="row"><button id="logout" class="btn ghost small" type="button">${L('Выйти')}</button>
          ${hub ? `<a class="hub-link" href="${esc(hub)}" title="${esc(L('Список всех панелей сервера'))}">${L('← Все панели')}</a>` : ''}</div>
      </div>
    </aside>
    <main id="main"></main>`;
  fillPlayers();
}

function showLogin() {
  stopTimers();
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
  syncLoginVideo();
  setTimeout(() => { const p = $('#login-password'); if (p) p.focus(); }, 50);
}

async function start() {
  let me = null;
  try { me = await api('/api/me'); } catch (e) { /* панель недоступна — покажем вход */ }
  if (me && me.site) Object.assign(SITE, me.site);
  renderShell();
  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('#login-error').textContent = '';
    try {
      const d = await api('/api/login', { password: $('#login-password').value });
      S.csrf = d.csrf; $('#login-password').value = '';
      if (d.site) Object.assign(SITE, d.site);
      sfx.play('launch_select2');
      enterApp();
    } catch (err) { $('#login-error').textContent = err.message; sfx.play('launch_deny2'); }
  });
  $('#logout').addEventListener('click', async () => { await act(() => api('/api/logout', {})); showLogin(); });
  $('#nav').addEventListener('click', (e) => {
    const a = e.target.closest('a[data-page]');
    if (!a) return;
    e.preventDefault();
    sfx.play('launch_select2');
    go(a.dataset.page);
  });
  $('#nav').addEventListener('mouseover', (e) => {
    const a = e.target.closest('a[data-page]');
    if (a && !a.contains(e.relatedTarget)) sfx.play('launch_glow1');
  });
  document.addEventListener('click', onAction);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  window.addEventListener('resize', evenAll);
  document.addEventListener('error', (e) => {
    const t = e.target;
    if (t.classList && t.classList.contains('flag')) t.replaceWith(document.createTextNode(t.alt));
  }, true);
  initMapTip();
  music.init();
  window.addEventListener('hashchange', () => { if (!$('#app').classList.contains('hidden')) go(location.hash.slice(1) || 'overview', true); });
  if (me && me.auth) { S.csrf = me.csrf; enterApp(); } else showLogin();
}

function enterApp() {
  $('#login').classList.add('hidden');
  $('#app').classList.remove('hidden');
  const v = $('#login-video');
  if (v) v.pause();
  go(location.hash.slice(1) || 'overview', true);
  sideStatus();
  clearInterval(S.sideTimer);
  S.sideTimer = setInterval(sideStatus, 15000);
}

async function sideStatus() {
  try {
    const d = await api('/api/overview');
    const s = d.server;
    $('#side-host').textContent = SITE.title || (s ? s.hostname : GAME);
    $('#side-status').className = 'pill ' + (s ? 'ok' : 'bad');
    $('#side-status').textContent = s ? L('работает · {0}', s.map) : L('не отвечает');
    if (s && s.map !== S.map) { S.map = s.map; applyMapBg(); }
  } catch (e) { /* тихо: основное сообщение покажет страница */ }
}

/* ---------- навигация ---------- */

const PAGES = {};
function stopTimers() { S.timers.forEach(clearInterval); S.timers = []; }
function every(ms, fn) { S.timers.push(setInterval(fn, ms)); }

function go(page, fromHash) {
  if (!PAGES[page]) page = 'overview';
  S.page = page;
  if (!fromHash) location.hash = page;
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === page));
  stopTimers();
  closeModal();
  if (S.hideTip) S.hideTip();
  S.redrawSettings = null;
  const main = $('#main');
  main.innerHTML = '<div class="empty">' + L('Загрузка…') + '</div>';
  PAGES[page](main);
}

/* Все кнопки с data-act попадают сюда. */
async function onAction(e) {
  const b = e.target.closest('[data-act]');
  if (!b || b.disabled) return;
  const fn = ACTIONS[b.dataset.act];
  if (!fn) return;
  e.preventDefault();
  if (!b.dataset.music) sfx.play('launch_select1');
  b.disabled = true;
  try { await fn(b.dataset, b); } finally { b.disabled = false; }
}

/* Плитки — ровными рядами: берём наибольшее число колонок, которое помещается и делит
   количество плиток без остатка (12 → 6, 4, 3 или 2). Если такого нет (простое число
   плиток) — сколько помещается. */
function evenGrid(el, minW, gap) {
  if (!el || !el.children.length) return;
  gap = gap ?? (parseFloat(getComputedStyle(el).columnGap) || 0);
  const n = el.children.length;
  const max = Math.max(1, Math.floor((el.clientWidth + gap) / (minW + gap)));
  let cols = max;
  for (let k = max; k >= Math.ceil(max / 2); k--) if (n % k === 0) { cols = k; break; }
  el.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
}
// плитка порядка карт: на телефоне уже, чтобы шло по две в ряд, а не по одной
const ordTileW = () => (innerWidth < 600 ? 140 : 176);
const evenAll = () => { evenGrid($('#ord'), ordTileW()); evenGrid($('#pick'), 96); };

/* ---------- окна поверх страницы ---------- */

function openModal(html, cls) {
  closeModal();
  if (S.hideTip) S.hideTip();
  const back = document.createElement('div');
  back.className = 'modal-back';
  back.innerHTML = '<div class="modal ' + (cls || '') + '" role="dialog" aria-modal="true">'
    + '<button class="modal-x" data-act="modal-close" data-music="1" title="' + esc(L('Закрыть')) + '">×</button>' + html + '</div>';
  back.addEventListener('click', (e) => { if (e.target === back) closeModal(); });
  document.body.appendChild(back);
  S.modal = back;
  sfx.play('launch_upmenu1');
  return back.querySelector('.modal');
}
function closeModal() {
  if (!S.modal) return;
  S.modal.remove();
  S.modal = null;
  sfx.play('launch_dnmenu1');
  const done = S.modalDone; S.modalDone = null;
  if (done) done('later');
}
ACTIONS['modal-close'] = () => closeModal();

/* Вопрос с вариантами. buttons: [[ключ, надпись, класс]]. Закрыли окно — «later». */
function choose(title, html, buttons) {
  return new Promise((resolve) => {
    const m = openModal('<h2>' + esc(title) + '</h2><p>' + html + '</p><div class="row mt16">'
      + buttons.map(([k, l, c]) => '<button class="btn ' + (c || '') + '" data-choice="' + k + '">' + esc(l) + '</button>').join('')
      + '</div>', 'small');
    S.modalDone = resolve;
    m.addEventListener('click', (e) => {
      const b = e.target.closest('[data-choice]');
      if (!b) return;
      S.modalDone = null;
      closeModal();
      resolve(b.dataset.choice);
    });
  });
}

/* ---------- настройки, которые ждут смены карты или перезапуска ---------- */

function pendingBanner(list) {
  if (!list || !list.length) return '';
  const restart = list.some((p) => p.kind === 'restart');
  return `<div class="note pend"><b>${restart ? L('Ждут перезапуска сервера:') : L('Ждут смены карты:')}</b>
    ${list.map((p) => '<span class="mono">' + esc(p.name) + ' ' + esc(p.value) + '</span>').join(', ')}
    <div class="row mt8">${restart ? '' : '<button class="btn small" data-act="apply-map">' + L('Перезапустить карту сейчас') + '</button>'}
      ${F('restart') ? '<button class="btn small danger" data-act="apply-restart">' + L('Перезапустить сервер сейчас') + '</button>'
        : restart ? '<span class="muted">' + L('Перезапустите сервер вручную — из панели перезапуск не настроен.') + '</span>' : ''}
      <button class="btn small ghost" data-act="pending-dismiss">${L('Скрыть')}</button></div></div>`;
}
const reloadSoon = (ms) => setTimeout(() => go(S.page, true), ms);
ACTIONS['apply-map'] = async () => {
  if (await act(() => api('/api/maps', { action: 'restart' }), L('Карта перезапускается — настройки применятся'))) reloadSoon(4000);
};
ACTIONS['apply-restart'] = async () => {
  if (!confirm(L('Перезапустить игровой сервер? Игроков выкинет на ~10 секунд.'))) return;
  if (await act(() => api('/api/container', { action: 'restart' }), L('Перезапускаю сервер'))) reloadSoon(3000);
};
ACTIONS['pending-dismiss'] = async () => { await act(() => api('/api/pending', { action: 'dismiss' })); go(S.page, true); };

/* После сохранения настройки: если сервер применит её не сразу — спросить, когда. */
async function afterSettingSaved(name, r) {
  if (r.apply !== 'map' && r.apply !== 'restart') return;
  const map = r.apply === 'map';
  const nm = '<b class="mono">' + esc(name) + '</b>';
  if (!map && !F('restart')) {
    toast(L('{0} заработает после перезапуска сервера — перезапустите его вручную.', name));
    return;
  }
  const buttons = map
    ? [['map', L('Перезапустить карту сейчас'), 'primary'], ...(F('restart') ? [['restart', L('Перезапустить сервер')]] : []), ['later', L('Потом')]]
    : [['restart', L('Перезапустить сервер сейчас'), 'primary'], ['later', L('Потом')]];
  const choice = await choose(map ? L('Нужна смена карты') : L('Нужен перезапуск сервера'), map
    ? L('{0} сохранена, но сервер применит её только со следующей карты. Сделать сейчас?', nm)
    : L('{0} сохранена, но сервер не принял её на ходу — она заработает после перезапуска сервера. Сделать сейчас?', nm), buttons);
  if (choice === 'map') await act(() => api('/api/maps', { action: 'restart' }), L('Карта перезапускается — настройка применится'));
  else if (choice === 'restart') await act(() => api('/api/container', { action: 'restart' }), L('Перезапускаю сервер — настройка применится'));
  else toast(L('Хорошо. Напоминание будет вверху «Обзора», «Карт» и «Настроек сервера», пока не перезапустите'));
}
const savedMsg = (name, x) => ({
  now: L('{0} сохранена (копия {1}), применена на сервере', name, x.backup),
  offline: L('{0} сохранена (копия {1}). Сервер не отвечает — применит при запуске', name, x.backup),
}[x.apply] || L('{0} сохранена (копия {1})', name, x.backup));

/* ---------- живые игроки ---------- */

/* Флаги — static/flags/<код>.svg (набор flag-icons, MIT). Локальная сеть и «?» — буквами. */
const flagHtml = (c) => (!c ? '' : /^[A-Z]{2}$/.test(c.code)
  ? '<img class="flag" src="/static/flags/' + c.code.toLowerCase() + '.svg" alt="' + esc(c.code) + '" title="' + esc(countryName(c)) + '">'
  : '<span class="cc" title="' + esc(countryName(c)) + '">' + esc(c.code) + '</span>');
const countryTag = (c) => (c ? flagHtml(c) + ' ' + esc(countryName(c)) : '<span class="muted">—</span>');
const playerBtn = (ip, name) => (ip
  ? '<button class="plink" data-act="player" data-ip="' + esc(ip) + '">' + esc(name) + '</button>' : esc(name));
const killsShort = (n) => L('{0} уб.', num(n));
const kdTip = (k, d) => L('{0} убийств / {1} смертей', num(k), num(d));

/* Карточка игрока — вкладками. «Обзор»: адрес, 10 плиток (ровно два ряда по 5, на телефоне по 2).
   «Лучшее»: оружие | карты, лучшие заходы | где играет лучше | дни недели. «Календарь»: дни, когда заходил, и часы.
   «Заходы»: все заходы по страницам. */
ACTIONS.player = async (d) => {
  let c;
  try { c = await api('/api/player?ip=' + encodeURIComponent(d.ip)); } catch (e) { toast(e.message, true); return; }
  const hours = Array(24).fill(0), week = Array(7).fill(0), days = new Set();
  for (const [t, dur] of c.spans) {
    const dt = new Date(t * 1000);
    hours[dt.getHours()]++;
    week[(dt.getDay() + 6) % 7] += dur;          // понедельник — первый
    days.add(dayKey(dt));
  }
  const kpi = (label, value, tip, sub) => '<div class="kpi"' + (tip ? ' title="' + esc(tip) + '"' : '') + '><div class="muted">'
    + label + '</div><div class="kv-big">' + value + '</div>' + (sub ? '<div class="muted fs12">' + sub + '</div>' : '') + '</div>';
  const byNick = '<div class="muted fs12 mt8">' + L('по нику — статистика оружия ведётся по нику') + '</div>';
  const tab = (key, label, on) => `<button${on ? ' class="active"' : ''} data-act="pc-tab" data-tab="${key}">${label}</button>`;
  const m = openModal(`
    <h2>${esc(c.name)} ${c.online ? pill(L('на сервере'), 'ok') : ''}</h2>
    ${c.names.length > 1 ? '<div class="muted">' + L('Ники с этого адреса: {0}', c.names.map(esc).join(', ')) + '</div>' : ''}
    <div class="tabs mt12" id="pc-tabs">${tab('main', L('Обзор'), true)}${tab('best', L('Лучшее'))}${tab('cal', L('Календарь'))}${
      tab('visits', L('Заходы') + ' · ' + num(c.visits))}</div>
    <div class="pc-pane" data-pane="main">
      <dl class="kv"><dt>IP</dt><dd class="mono">${esc(c.ip)}</dd><dt>${L('Страна')}</dt><dd>${countryTag(c.country)}</dd>
        <dt>${L('Первый заход')}</dt><dd>${fmtDateTime(c.first)}</dd>
        <dt>${L('Последний')}</dt><dd>${c.online ? L('сейчас на сервере') : fmtDateTime(c.last)}</dd></dl>
      <div class="kpis five mt12">${kpi(L('Заходов'), num(c.visits))}${kpi(L('Всего в игре'), fmtDur(c.seconds))}${kpi(L('Средний заход'), fmtDur(c.avg))}
        ${kpi(L('Убийств / смертей'), num(c.kills) + ' / ' + num(c.deaths))}${kpi(L('У/С'), dec(c.kd))}
        ${kpi(L('Лучший заход'), c.best.kills ? killsShort(c.best.kills) : '—', '', c.best.kills ? fmtDate(c.best.at) : '')}
        ${kpi(L('Самый долгий заход'), fmtDur(c.longest.duration), '', fmtDate(c.longest.at))}
        ${kpi(L('Убийств в час'), c.kph == null ? '—' : dec(c.kph), L('по заходам, где были убийства или смерти'))}
        ${kpi(L('Дней на сервере'), num(days.size))}
        ${kpi(L('Место по времени'), c.rank ? L('{0} из {1}', c.rank.pos, c.rank.of) : '—', L('среди всех живых игроков — по времени в игре'))}</div>
    </div>
    <div class="pc-pane hidden" data-pane="best">
      <div class="duo">
        <div><h3>${L('Любимое оружие')}</h3><div class="bars" id="pc-w"></div>${c.weapons.length ? byNick : ''}</div>
        <div><h3>${L('Любимые карты')}</h3><div class="bars" id="pc-m"></div></div>
      </div>
      <div class="trio mt16">
        <div><h3>${L('Лучшие заходы')}</h3><div class="bars lbl-m" id="pc-t"></div></div>
        <div><h3>${L('Где играет лучше')}</h3><div class="bars lbl-m" id="pc-k"></div></div>
        <div><h3>${L('Дни недели')}</h3><div class="bars lbl-s" id="pc-d"></div></div>
      </div>
      <div class="muted fs12 mt8">${L('Лучшие заходы — пять заходов с наибольшим числом убийств (убийства / смерти). «Где играет лучше» — У/С на картах, где набралось от 10 убийств и смертей; по нику, из игрового лога. Дни недели — время в игре по дню захода, по часам вашего компьютера.')}</div>
    </div>
    <div class="pc-pane hidden" data-pane="cal">
      <div class="pc-cal"></div>
      <h3 class="mt16">${L('Когда заходит')}</h3><div class="hours small" id="pc-h"></div>
      <div class="hours-labels">${Array.from({ length: 24 }, (_, i) => '<span>' + i + '</span>').join('')}</div>
    </div>
    <div class="pc-pane hidden" data-pane="visits">
      <div id="pc-v"></div>
      ${c.same_names_from.length ? '<div class="note mt12">' + L('Этим же ником заходили и с других адресов: {0} — возможно, это другой человек.',
        '<span class="mono">' + c.same_names_from.map(esc).join(', ') + '</span>') + '</div>' : ''}
    </div>`, 'wide');
  hoursChart(m.querySelector('#pc-h'), hours);
  bars(m.querySelector('#pc-w'), c.weapons, 'title', 'kills', { fmt: (w) => killsShort(w.kills) });
  bars(m.querySelector('#pc-m'), c.maps, 'map', 'visits', { mapPreview: true, fmt: (x) => times(x.visits) });
  bars(m.querySelector('#pc-t'), c.top.map((t) => ({ ...t, title: fmtDate(t.at) })), 'title', 'kills', {
    fmt: (t) => t.kills + ' / ' + t.deaths,
    tip: (t) => fmtDateTime(t.at) + ' · ' + t.name + ' · ' + fmtDur(t.duration) + ' · ' + kdTip(t.kills, t.deaths) });
  bars(m.querySelector('#pc-k'), c.map_kd, 'map', 'kd', { mapPreview: true, fmt: (x) => dec(x.kd),
    tip: (x) => L('У/С {0}: {1} за {2}', dec(x.kd), kdTip(x.kills, x.deaths), Pn(x.matches, 'матч', 'матча', 'матчей')) });
  bars(m.querySelector('#pc-d'), WEEKDAYS.map((w, i) => ({ title: w, seconds: week[i] })), 'title', 'seconds',
    { fmt: (x) => (x.seconds ? fmtDur(x.seconds) : '—') });
  const last = new Date((c.online ? Date.now() / 1000 : c.last) * 1000);
  const cal = m.querySelector('.pc-cal');
  cal._pc = { visits: c.recent, y: last.getFullYear(), m: last.getMonth(), day: null };
  playerCal(cal);
  pagerMount(m.querySelector('#pc-v'), c.recent, 10, (el, rows) => { el.innerHTML = visitsTable(rows); });
};

ACTIONS['pc-tab'] = (d, b) => {
  const m = b.closest('.modal');
  m.querySelectorAll('#pc-tabs button').forEach((x) => x.classList.toggle('active', x.dataset.tab === d.tab));
  m.querySelectorAll('.pc-pane').forEach((x) => x.classList.toggle('hidden', x.dataset.pane !== d.tab));
};

const visitsTable = (rows) => `<div class="tbl-wrap"><table><thead><tr><th>${L('Зашёл')}</th><th class="num">${L('Пробыл')}</th>
  <th>${L('Ник')}</th><th>${L('Карты')}</th><th class="num nowrap">${L('У / С')}</th></tr></thead><tbody>${rows.map((r) => `<tr>
  <td class="nowrap">${fmtDateTime(r.joined_at)}</td><td class="num nowrap">${r.online ? pill(L('сейчас'), 'ok') : fmtDur(r.duration)}</td>
  <td>${esc(r.name)}</td><td class="mono">${r.maps.map(mapLink).join(', ')}</td><td class="num nowrap">${r.kills} / ${r.deaths}</td></tr>`).join('')
  }</tbody></table></div>`;

/* Календарь игрока: дни, когда он заходил (чем темнее, тем дольше был на сервере); по клику — заходы дня. */
function playerCal(el) {
  const st = el._pc, { y, m } = st;
  const byDay = {};
  for (const v of st.visits) (byDay[dayKey(new Date(v.joined_at * 1000))] ||= []).push(v);
  const secs = (list) => list.reduce((a, v) => a + Math.max(0, v.duration || 0), 0);
  const month = Object.keys(byDay).filter((k) => k.startsWith(y + '-' + pad2(m + 1)));
  const max = Math.max(1, ...month.map((k) => secs(byDay[k])));
  const lead = (new Date(y, m, 1).getDay() + 6) % 7, total = new Date(y, m + 1, 0).getDate(), today = dayKey(new Date());
  let cells = WEEKDAYS.map((w) => `<div class="cal-h">${esc(w)}</div>`).join('');
  for (let i = 0; i < lead; i++) cells += '<div class="cal-d empty-cell"></div>';
  for (let n = 1; n <= total; n++) {
    const key = y + '-' + pad2(m + 1) + '-' + pad2(n), list = byDay[key] || [];
    const lvl = list.length ? 1 + Math.min(3, Math.floor(3 * secs(list) / max)) : 0;
    cells += `<button class="cal-d l${lvl}${key === today ? ' today' : ''}${key === st.day ? ' sel' : ''}" data-act="pc-cal-day" data-day="${key}" ${list.length ? '' : 'disabled'}>
      <span class="cal-n">${n}</span>${list.length ? `<span class="cal-b">${list.length}</span><span class="cal-c">${Pn(list.length, 'заход', 'захода', 'заходов')}</span><span class="cal-p">${fmtDur(secs(list))}</span>` : ''}</button>`;
  }
  const sel = st.day && byDay[st.day];
  el.innerHTML = `<h3><button class="btn small ghost" data-act="pc-cal-move" data-dir="-1">←</button>${esc(monthTitle(y, m))}
      <button class="btn small ghost" data-act="pc-cal-move" data-dir="1">→</button>
      <span class="muted fs12">${L('дней с заходами: {0}', num(month.length))}</span></h3>
    <div class="cal">${cells}</div>
    <p class="muted fs12">${L('Чем темнее день, тем дольше игрок был на сервере. Нажмите на день — внизу появятся его заходы.')}</p>
    ${sel ? `<h3 class="mt12">${esc(fmtDate(new Date(st.day + 'T12:00:00').getTime() / 1000))}</h3>${visitsTable(sel)}` : ''}`;
}

ACTIONS['pc-cal-move'] = (d, b) => {
  const el = b.closest('.pc-cal'), s = el._pc, t = new Date(s.y, s.m + Number(d.dir), 1);
  s.y = t.getFullYear(); s.m = t.getMonth(); s.day = null;
  playerCal(el);
};
ACTIONS['pc-cal-day'] = (d, b) => {
  const el = b.closest('.pc-cal');
  el._pc.day = el._pc.day === d.day ? null : d.day;
  playerCal(el);
};

const who = (p) => (p.bot ? '<span class="tag-bot">🤖</span> ' : p.bot === false ? '🧑 ' : '❔ ');
const restartBtn = (label) => (F('restart') ? `<button class="btn danger" data-act="container" data-action="restart">${label}</button>` : '');

/* ---------- Обзор ---------- */

PAGES.overview = async (main) => {
  main.innerHTML = `
    <h1>${L('Обзор')}</h1>
    <div id="ov-pend"></div>
    <div class="grid" id="ov-cards"></div>
    <div class="grid two">
      <div class="card"><h2>${L('На карте')} <span id="ov-count" class="muted"></span></h2><div id="ov-players"></div></div>
      <div class="card">
        <h2>${L('Быстрые действия')}</h2>
        <div class="ov-maps" id="ov-maps"></div>
        <div class="row">
          <button class="btn" data-act="map-next" id="ov-next">${L('Следующая карта')}</button>
          <button class="btn" data-act="map-restart">${L('Перезапустить карту')}</button>
          <button class="btn" data-act="round-restart">${L('Рестарт раунда')}</button>
          ${restartBtn(L('Перезапустить сервер'))}
        </div>
        ${F('console') ? `<h2 class="mt18">${L('Падения и перезапуски')}</h2><div id="ov-events"></div>` : ''}
      </div>
    </div>`;
  S.ovMaps = null;
  const load = async () => {
    let d;
    try { d = await api('/api/overview'); } catch (e) { $('#ov-cards').innerHTML = '<div class="card error">' + esc(e.message) + '</div>'; return; }
    renderOverview(d);
  };
  await load();
  every(5000, load);
};

function renderOverview(d) {
  const s = d.server, c = d.container, h = d.host || {}, st = d.stats || {};
  $('#ov-pend').innerHTML = pendingBanner(d.pending);
  const cards = [];
  if (s) {
    const left = s.map_since && Number(s.timelimit) ? Math.max(0, s.map_since + s.timelimit * 60 - d.now) : null;
    cards.push(`<div class="card"><h2>${L('Сервер')} ${pill(L('работает'), 'ok')}</h2>
      <div class="big mono">${mapLink(s.map)}</div>
      <dl class="kv"><dt>${L('Игроки')}</dt><dd>${L('{0} из {1} · людей {2}, ботов {3}', s.players.length, esc(s.maxplayers), s.humans, s.bots)}</dd>
      <dt>${L('Карта')}</dt><dd>${s.map_since ? L('идёт {0}', fmtDur(d.now - s.map_since)) + (left !== null ? L(', до смены ≈ {0}', fmtDur(left)) : '') : '—'}</dd>
      ${s.score ? `<dt>${L('Счёт')}</dt><dd class="score"><span class="team ct">CT</span>${num(s.score.ct)} : ${num(s.score.t)} <span class="team t">T</span>`
        + ` <span class="muted">${L('раунд {0}', num(s.score.ct + s.score.t + 1))}</span></dd>` : ''}
      <dt>${L('Лимиты')}</dt><dd>${L('{0} мин', esc(s.timelimit))} · ${L('раунд {0} мин', esc(s.roundtime || '—'))}${Number(s.maxrounds) ? ' · ' + L('до {0} раундов', esc(s.maxrounds)) : ''}${Number(s.winlimit) ? ' · ' + L('до {0} побед', esc(s.winlimit)) : ''}</dd>
      ${!c && d.started ? `<dt>${L('Работает')}</dt><dd>${fmtDur(d.now - d.started)}</dd>` : ''}
      <dt>${L('Адрес')}</dt><dd class="mono">${esc(s.address)}</dd></dl></div>`);
  } else {
    cards.push(`<div class="card"><h2>${L('Сервер')} ${pill(L('не отвечает'), 'bad')}</h2>
      <p>${L('Сервер не ответил на запрос статуса. Если он запущен через hlds_run, после падения тот поднимет его сам за ~10 секунд.')}</p>
      ${restartBtn(L('Перезапустить сейчас'))}</div>`);
  }
  if (c) {
    cards.push(`<div class="card"><h2>${L('Контейнер')} ${c.running ? pill(L('запущен'), 'ok') : pill(c.status || L('нет'), 'bad')}</h2>
      <dl class="kv"><dt>${L('Процессор')}</dt><dd>${esc(c.cpu || '—')}</dd><dt>${L('Память')}</dt><dd>${esc(c.mem || '—')}</dd>
      <dt>${L('Работает')}</dt><dd>${c.started_at ? sinceIso(c.started_at) : '—'}</dd>
      <dt>${L('Перезапусков')}</dt><dd>${esc(c.restarts ?? '—')}</dd><dt>${L('Образ')}</dt><dd class="mono">${esc(c.image || '—')}</dd></dl></div>`);
  }
  const memUsed = (h.mem_total || 0) - (h.mem_available || 0);
  cards.push(`<div class="card"><h2>${L('Машина')}</h2>
    <dl class="kv"><dt>${L('Нагрузка')}</dt><dd>${esc((h.load || []).join(' · '))} (${Pn(h.cpus || 0, 'ядро', 'ядра', 'ядер')})</dd>
    <dt>${L('Память')}</dt><dd>${L('{0} из {1}', fmtBytes(memUsed), fmtBytes(h.mem_total))}</dd>
    <dt>${L('Своп')}</dt><dd>${L('{0} из {1}', fmtBytes((h.swap_total || 0) - (h.swap_free || 0)), fmtBytes(h.swap_total))}</dd>
    <dt>${L('Диск')}</dt><dd>${L('свободно {0}', fmtBytes(h.disk_free))}</dd>
    <dt>${L('Аптайм')}</dt><dd>${fmtDur(h.uptime)}</dd></dl></div>`);
  cards.push(`<div class="card"><h2>${L('История')}</h2>
    <div class="big">${num(st.matches)} <span class="muted fs15">${L('матчей')}</span></div>
    <dl class="kv"><dt>${L('Убийств')}</dt><dd>${num(st.kills)}</dd><dt>${L('Сыграно')}</dt><dd>${fmtDur(st.seconds)}</dd>
    <dt>${L('Живых игроков')}</dt><dd>${L('{0} (в {1} матчах)', num(st.humans), num(st.matches_with_humans))}</dd></dl></div>`);
  $('#ov-cards').innerHTML = cards.join('');

  const tOrd = { CT: 0, T: 1 };
  const list = s ? s.players.slice().sort((a, b) => (tOrd[a.team] ?? 2) - (tOrd[b.team] ?? 2) || (b.frags ?? -99) - (a.frags ?? -99)) : [];
  $('#ov-count').textContent = s ? '(' + list.length + ')' : '';
  $('#ov-players').innerHTML = list.length ? `<div class="tbl-wrap"><table><thead><tr><th>${L('Игрок')}</th><th class="num">${L('Фраги')}</th><th class="num">${L('На сервере')}</th></tr></thead><tbody>${
    list.map((p) => `<tr><td>${who(p)}${team(p.team)}${esc(p.name)}</td><td class="num">${p.frags ?? '—'}</td><td class="num">${p.time != null ? fmtDur(p.time) : '—'}</td></tr>`).join('')
  }</tbody></table></div>` : '<div class="empty">' + L('Никого') + '</div>';

  // картинки текущей и следующей карты — перерисовываются только при смене карты
  const mk = s ? s.map + '|' + (s.next || '') : '';
  if (mk !== S.ovMaps && $('#ov-maps')) {
    S.ovMaps = mk;
    const fig = (cap, m, has) => `<figure class="ov-map">${has ? `<img src="${previewSrc(m)}" alt="">`
      : '<div class="none">' + noImg() + '</div>'}<figcaption><span class="muted">${esc(cap)}</span> <b class="mono">${esc(m)}</b></figcaption></figure>`;
    $('#ov-maps').innerHTML = s ? fig(L('Сейчас играет'), s.map, s.preview) + (s.next ? fig(L('Следующая'), s.next, s.next_preview) : '') : '';
  }

  const evEl = $('#ov-events');
  if (evEl) {
    const ev = d.events || [];
    evEl.innerHTML = ev.length
      ? '<pre class="out">' + esc(ev.slice(-6).join('\n')) + '</pre>'
      : '<div class="empty">' + L('Событий нет — сервер не падал.') + '</div>';
  }
}

/* ---------- Игроки и боты ---------- */

PAGES.players = async (main) => {
  main.innerHTML = `
    <h1>${F('bots') ? L('Игроки и боты') : L('Игроки')}</h1>
    <div class="grid split">
      <div class="colstack">
        <div class="card"><h2>${L('На сервере')} <button class="btn small" data-act="players-reload">${L('Обновить')}</button></h2><div id="pl-table"></div>
          <p class="muted">${L('Список — из живого лога сервера: кто зашёл, с какого адреса, бот или человек. Фраги и время — из запроса к серверу.')}</p></div>
        <div class="card"><h2>${L('Сообщение всем')}</h2>
          <div class="row"><input id="say-text" class="wide" maxlength="120" placeholder="${esc(L('Текст в игровой чат'))}">
          <button class="btn primary" data-act="say">${L('Отправить')}</button></div>
          <p class="muted">${L('В {0} нет личных сообщений от сервера — только общий чат.', GAME)}</p></div>
      </div>
      <div class="colstack">
        ${F('bots') ? `<div class="card"><h2>${YAPB() ? L('Боты YaPB') : L('Боты jk_botti')}</h2><div class="stack" id="pl-bots"></div></div>` : ''}
        <div class="card"><h2>${L('Баны по IP')}</h2>
          <div class="row mb10"><input id="ban-addr" placeholder="1.2.3.4">
            <button class="btn danger" data-act="ban-address">${L('Забанить адрес')}</button></div>
          <div id="pl-bans"></div>
          <p class="muted">${L('Баны хранятся в listip.cfg (команда writeip) и переживают перезапуск сервера.')}</p></div>
      </div>
    </div>`;
  await loadPlayers(true);
  every(10000, () => loadPlayers(false));
};

const banTerm = (b) => (b.minutes ? L('{0} мин', dec(b.minutes)) : L('навсегда'));

async function loadPlayers(full) {
  let d;
  try { d = await api('/api/players'); } catch (e) { $('#pl-table').innerHTML = '<div class="error">' + esc(e.message) + '</div>'; return; }
  if (!$('#pl-table')) return;
  const rows = d.players.sort((a, b) => (a.bot ? 1 : 0) - (b.bot ? 1 : 0) || (b.frags ?? -99) - (a.frags ?? -99));
  $('#pl-table').innerHTML = (!d.responding ? '<div class="error">' + L('Сервер не ответил на запрос — показываю, что известно по логу.') + '</div>' : '')
    + (rows.length ? `<div class="tbl-wrap"><table><thead><tr>
    <th class="num">userid</th><th>${L('Игрок')}</th><th class="num">${L('Фраги')}</th><th class="num">${L('На сервере')}</th><th>${L('Адрес')}</th><th></th></tr></thead><tbody>${
    rows.map((p) => `<tr><td class="num">${p.uid ?? '—'}</td><td>${who(p)}${team(p.team)}${p.bot ? '<span class="tag-bot">' + L('бот') + '</span> ' : ''}${esc(p.name)}</td>
      <td class="num">${p.frags ?? '—'}</td><td class="num">${p.time != null ? fmtDur(p.time) : '—'}</td>
      <td class="mono">${p.bot ? '—' : esc(p.address || '—')}</td>
      <td><div class="row">${p.uid ? `<button class="btn small" data-act="kick" data-uid="${p.uid}" data-name="${esc(p.name)}">${L('Выкинуть')}</button>` : ''}
        ${!p.bot && p.uid && p.address ? `<button class="btn small danger" data-act="ban" data-uid="${p.uid}" data-address="${esc(p.address)}" data-name="${esc(p.name)}">${L('Бан')}</button>` : ''}</div></td></tr>`).join('')
  }</tbody></table></div>` : '<div class="empty">' + L('На сервере никого') + '</div>');
  $('#pl-bans').innerHTML = d.bans.length ? `<table><thead><tr><th>${L('Адрес')}</th><th>${L('Срок')}</th><th></th></tr></thead><tbody>${
    d.bans.map((b) => `<tr><td class="mono">${esc(b.ip)}</td><td>${esc(banTerm(b))}</td>
      <td><button class="btn small" data-act="unban" data-address="${esc(b.ip)}">${L('Снять')}</button></td></tr>`).join('')
  }</tbody></table>` : '<div class="empty">' + L('Банов нет') + '</div>';
  if (full && d.bots && $('#pl-bots') && d.bots_kind === 'yapb') {
    const v = Object.fromEntries(d.bots.map((b) => [b.name, b.value]));
    const modes = [['fill', L('людей и ботов вместе')], ['normal', L('ровно столько ботов')]];
    if (v.yb_quota_mode === 'match') modes.push(['match', 'match']);
    const opt = (val, text, cur) => `<option value="${esc(val)}"${String(val) === String(cur) ? ' selected' : ''}>${esc(text)}</option>`;
    $('#pl-bots').innerHTML = `
      <div class="row"><span class="muted w140">${L('Ботов')}</span><input id="yb-quota" class="narrow" type="number" min="0" max="31" value="${esc(v.yb_quota)}">
        <select id="yb-mode">${modes.map(([k, t]) => opt(k, t, v.yb_quota_mode || 'fill')).join('')}</select></div>
      <div class="row"><span class="muted w140">${L('Сложность')}</span><select id="yb-diff">${
        [L('новичок'), L('лёгкий'), L('средний'), L('сложный'), L('эксперт')].map((t, i) => opt(i, i + ' — ' + t, v.yb_difficulty)).join('')}</select></div>
      <div class="row"><button class="btn primary" data-act="bots">${L('Применить и сохранить')}</button>
        <button class="btn danger" data-act="kickbots">${L('Убрать всех ботов')}</button></div>
      <div class="muted">${L('«Людей и ботов вместе»: на пустом сервере столько ботов, зашёл человек — один бот уходит. Новая сложность — у ботов, которые зайдут после неё. «Убрать всех» действует до перезапуска сервера. Остальные настройки ботов — в «Настройках сервера».')}</div>`;
  } else if (full && d.bots && $('#pl-bots')) {
    const v = Object.fromEntries(d.bots.map((b) => [b.name, b.value]));
    $('#pl-bots').innerHTML = `
      <div class="row"><span class="muted w140">${L('Минимум ботов')}</span><input id="bot-min" class="narrow" type="number" min="0" max="15" value="${esc(v.min_bots)}"></div>
      <div class="row"><span class="muted w140">${L('Игроков с ботами')}</span><input id="bot-max" class="narrow" type="number" min="0" max="15" value="${esc(v.max_bots)}"></div>
      <div class="row"><span class="muted w140">${L('Сложность 1–5')}</span><input id="bot-skill" class="narrow" type="number" min="1" max="5" value="${esc(v.botskill)}">
        <span class="muted">${L('1 — сильнее всех')}</span></div>
      <div class="row"><button class="btn primary" data-act="bots">${L('Применить и сохранить')}</button>
        <button class="btn danger" data-act="kickbots">${L('Убрать всех ботов')}</button></div>
      <div class="muted">${L('Боты добавляются, пока игроков вместе с ботами меньше «игроков с ботами». Зашёл живой — один бот уходит, но не меньше минимума. «Убрать всех» действует до перезапуска сервера.')}</div>`;
  }
}

const player = (body) => api('/api/players', body);
ACTIONS['players-reload'] = () => loadPlayers(true);
ACTIONS.say = async () => {
  const text = $('#say-text').value.trim(); if (!text) return;
  if (await act(() => player({ action: 'say', text }), L('Отправлено'))) $('#say-text').value = '';
};
ACTIONS.kick = async (d) => {
  if (!confirm(L('Выкинуть {0}?', d.name))) return;
  await act(() => player({ action: 'kick', uid: +d.uid, name: d.name }), L('Выкинут'));
  setTimeout(() => loadPlayers(false), 1500);
};
ACTIONS.ban = async (d) => {
  if (!confirm(L('Забанить адрес {0} игрока {1} навсегда и выкинуть его?', d.address, d.name))) return;
  await act(() => player({ action: 'ban', uid: +d.uid, address: d.address, name: d.name }), L('Забанен'));
  setTimeout(() => loadPlayers(false), 1500);
};
ACTIONS['ban-address'] = async () => {
  const address = $('#ban-addr').value.trim(); if (!address) return;
  if (!confirm(L('Забанить {0} навсегда?', address))) return;
  if (await act(() => player({ action: 'ban_address', address }), L('Адрес забанен'))) { $('#ban-addr').value = ''; loadPlayers(false); }
};
ACTIONS.unban = async (d) => { await act(() => player({ action: 'unban', address: d.address }), L('Снято')); loadPlayers(false); };
ACTIONS.bots = async () => {
  const body = YAPB()
    ? { action: 'bots', quota: +$('#yb-quota').value, mode: $('#yb-mode').value, difficulty: +$('#yb-diff').value }
    : { action: 'bots', min_bots: +$('#bot-min').value, max_bots: +$('#bot-max').value, botskill: +$('#bot-skill').value };
  await act(() => player(body), L('Сохранено. Боты подстроятся за несколько секунд'));
  setTimeout(() => loadPlayers(false), 4000);
};
ACTIONS.kickbots = async () => {
  if (!confirm(L('Убрать всех ботов? Вернутся после перезапуска сервера или кнопкой «Применить и сохранить».'))) return;
  await act(() => player({ action: 'kickbots' }), L('Боты убраны')); setTimeout(() => loadPlayers(false), 1500);
};

/* ---------- Карты ---------- */

PAGES.maps = async (main) => {
  let d;
  try { d = await api('/api/maps'); } catch (e) { main.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; return; }
  S.maps = d;
  S.ord = d.order.map((m) => ({ ...m }));
  S.pick = null;
  const has = (m) => d.previews.includes(m);
  const spent = d.map_since ? d.now - d.map_since : null;
  const total = d.timelimit ? d.timelimit * 60 : null;
  const left = d.ends_at ? Math.max(0, d.ends_at - d.now) : null;
  const next = d.upcoming[0];
  main.innerHTML = `
    <h1>${L('Карты')}</h1>
    ${pendingBanner(d.pending)}
    <div class="grid three">
      <div class="card span2"><h2>${L('Сейчас играет')}</h2>
        <div class="now-wide">
          ${d.current && has(d.current) ? `<img class="now-shot" src="${previewSrc(d.current)}" alt="">` : '<div class="now-shot none">' + noImg() + '</div>'}
          <div>
            <div class="big mono">${esc(d.current || '—')}</div>
            <div class="muted">${spent !== null ? L('идёт {0}', fmtDur(spent)) : ''}${left !== null ? ' · ' + L('до смены ≈ {0}', fmtDur(left)) : ''}</div>
            ${spent !== null && total ? '<div class="bar-track mt8"><div class="bar-fill" id="now-bar"></div></div>' : ''}
            ${next ? `<div class="mt16"><div class="muted fs12">${L('Следующая')}</div>
              <div class="row mt8">${has(next) ? `<img class="thumb-s" src="${thumbSrc(next)}" alt="">` : ''}
                <span class="mono">${esc(next)}</span></div></div>` : ''}
            <div class="row mt16"><button class="btn" data-act="map-next">${L('Следующая карта')}</button>
              <button class="btn" data-act="map-restart">${L('Перезапустить')}</button></div>
          </div>
        </div></div>
      <div class="card pick-card"><h2>${L('Загрузить карту')}</h2>
        <div class="pick" id="pick"></div>
        <p class="muted mt8">${L('Нажмите на карту — откроется окно с картинкой и тем, что будет дальше.')}</p></div>
    </div>
    <div class="card"><h2>${L('Порядок карт')}</h2>
      <p class="muted mb12">${L('Сервер играет карты по порядку — слева направо, сверху вниз; после последней снова первая.')}</p>
      <ol class="ord-tiles" id="ord"></ol>
      <div class="row mt12"><button class="btn small ghost" data-act="ord-all">${L('Включить все')}</button>
        <button class="btn small ghost" data-act="ord-reset">${L('Отменить')}</button>
        <span id="ord-dirty" class="dirty hidden">${L('Есть несохранённые изменения')}</span>
        <span class="grow"></span><button id="ord-save" class="btn small" data-act="ord-save">${L('Сохранить')}</button></div>
      <p class="muted">${L('Меняйте местами, перетаскивая карту мышью, или стрелками ◀ ▶. Выключенная карта остаётся в списке, но сервер её не ставит — играются только включённые. Сохранённое работает со следующей смены карты, без перезапуска.')}</p></div>`;
  if ($('#now-bar')) $('#now-bar').style.width = Math.min(100, 100 * spent / total).toFixed(1) + '%';
  renderPick();
  renderOrder();
  bindOrderDrag();
};

function renderPick() {
  const d = S.maps;
  $('#pick').innerHTML = d.available.map((m) => `<button class="pick-m${m === d.current ? ' cur' : ''}"
      data-act="pick" data-map="${esc(m)}" title="${esc(m)}">${d.previews.includes(m)
      ? `<img src="${thumbSrc(m)}" alt="" loading="lazy">` : '<span class="noimg">' + noImg() + '</span>'}
      <span class="pm">${esc(m)}</span></button>`).join('');
  evenGrid($('#pick'), 96);
}

/* Окно «Загрузить карту»: большая картинка и что будет дальше. Кнопка загрузки — в окне. */
ACTIONS.pick = (d) => {
  const D = S.maps, map = d.map;
  const on = D.order.filter((m) => m.on).map((m) => m.name);
  // дальше сервер пойдёт с карты, что стоит следом за загруженной (или с первой, если её нет в порядке)
  const after = on.length ? on[(on.indexOf(map) + 1) % on.length] : null;
  const mono = (x) => '<b class="mono">' + esc(x) + '</b>';
  S.pick = map;
  openModal(`<h2>${L('Загрузить карту')}</h2>
    <div class="load-head">
      ${D.previews.includes(map) ? `<img class="load-shot" src="${previewSrc(map)}" alt="">` : '<div class="load-shot none">' + noImg() + '</div>'}
      <div>
        <div class="big mono">${esc(map)}</div>
        ${map === D.current ? '<div class="muted mt8">' + L('Она играет сейчас — карта начнётся заново.') + '</div>' : ''}
        ${!on.includes(map) ? '<div class="muted mt8">' + L('Её нет среди включённых в «Порядке карт» — сервер сыграет её один раз.') + '</div>' : ''}
      </div>
    </div>
    <div class="note mt12">${L('Будет: {0}. Текущий матч прервётся, игроки останутся на сервере.', mono(map))}
      ${after ? L('Дальше — по порядку: {0}.', mono(after)) : ''}</div>
    <div class="row"><span class="grow"></span>
      <button class="btn ghost" data-act="modal-close">${L('Отмена')}</button>
      <button class="btn primary" data-act="map-load" id="lm-go">${L('Загрузить {0}', esc(map))}</button></div>`);
};

function renderOrder() {
  const d = S.maps;
  let n = 0;
  $('#ord').innerHTML = S.ord.map((m, i) => {
    const cur = m.name === d.current;
    const nr = m.on ? ++n : '';
    return `<li class="ord-tile${m.on ? '' : ' off'}${cur ? ' current' : ''}" draggable="true" data-i="${i}" title="${esc(L('Перетащите, чтобы поменять местами'))}">
      <div class="ot-img">${d.previews.includes(m.name)
        ? `<img src="${thumbSrc(m.name)}" alt="" loading="lazy" draggable="false">`
        : '<span class="none">' + noImg() + '</span>'}
        ${nr !== '' ? `<span class="ot-n">${nr}</span>` : ''}${cur ? '<span class="ot-cur">' + L('▶ сейчас') + '</span>' : ''}</div>
      <div class="ot-name">${esc(m.name)}</div>
      <div class="ot-ctl"><button class="btn small ghost" data-act="ord-move" data-i="${i}" data-step="-1" title="${esc(L('Раньше'))}"${i === 0 ? ' disabled' : ''}>◀</button>
        <button class="btn small ghost" data-act="ord-move" data-i="${i}" data-step="1" title="${esc(L('Позже'))}"${i === S.ord.length - 1 ? ' disabled' : ''}>▶</button>
        <button class="toggle${m.on ? ' on' : ''}" data-act="ord-toggle" data-i="${i}">${m.on ? L('играет') : L('выключена')}</button></div></li>`;
  }).join('');
  evenGrid($('#ord'), ordTileW());
  const dirty = JSON.stringify(S.ord) !== JSON.stringify(d.order);
  $('#ord-dirty').classList.toggle('hidden', !dirty);
  $('#ord-save').classList.toggle('primary', dirty);
}

/* Перетаскивание плиток мышью. Обработчики висят на самом списке: renderOrder
   меняет только его содержимое. */
function bindOrderDrag() {
  const list = $('#ord');
  let from = null;
  const clearMarks = () => list.querySelectorAll('.drop-before, .drop-after')
    .forEach((x) => x.classList.remove('drop-before', 'drop-after'));
  const below = (e, li) => { const r = li.getBoundingClientRect(); return e.clientX > r.left + r.width / 2; };
  list.addEventListener('dragstart', (e) => {
    const li = e.target.closest('li[data-i]');
    if (!li) return;
    from = Number(li.dataset.i);
    li.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', li.dataset.i); } catch (_) { /* старые браузеры */ }
  });
  list.addEventListener('dragover', (e) => {
    if (from === null) return;
    e.preventDefault();
    const li = e.target.closest('li[data-i]');
    clearMarks();
    if (li) li.classList.add(below(e, li) ? 'drop-after' : 'drop-before');
  });
  list.addEventListener('drop', (e) => {
    if (from === null) return;
    e.preventDefault();
    const li = e.target.closest('li[data-i]');
    if (li) {
      let to = Number(li.dataset.i) + (below(e, li) ? 1 : 0);
      const [m] = S.ord.splice(from, 1);
      if (to > from) to--;
      S.ord.splice(to, 0, m);
    }
    from = null;
    renderOrder();
  });
  list.addEventListener('dragend', () => { if (from !== null) { from = null; renderOrder(); } });
}

ACTIONS['ord-toggle'] = (d) => { const m = S.ord[Number(d.i)]; m.on = !m.on; renderOrder(); };
ACTIONS['ord-move'] = (d) => {
  const i = Number(d.i), j = i + Number(d.step);
  if (j < 0 || j >= S.ord.length) return;
  [S.ord[i], S.ord[j]] = [S.ord[j], S.ord[i]];
  renderOrder();
};
ACTIONS['ord-all'] = () => { S.ord.forEach((m) => { m.on = true; }); renderOrder(); };
ACTIONS['ord-reset'] = () => { S.ord = S.maps.order.map((m) => ({ ...m })); renderOrder(); };
ACTIONS['ord-save'] = async () => {
  const on = S.ord.filter((m) => m.on).length;
  if (!on) { toast(L('Включите хотя бы одну карту'), true); return; }
  const r = await act(() => api('/api/pool', { maps: S.ord }),
    (x) => (x.applied ? L('Сохранено (копия {0}). Со следующей смены карты пойдёт {1}.', x.backup, x.next)
      : L('Сохранено (копия {0}). Сервер не ответил — новый список он прочитает при запуске.', x.backup)));
  if (r) go('maps', true);
};
ACTIONS['map-next'] = async () => {
  await act(() => api('/api/maps', { action: 'next' }), L('Загружаю следующую карту'));
};
ACTIONS['map-restart'] = async () => { await act(() => api('/api/maps', { action: 'restart' }), L('Карта перезапущена')); };
ACTIONS['round-restart'] = async () => {
  if (!confirm(L('Начать игру на этой карте заново? Счёт, деньги и оружие обнулятся через секунду.'))) return;
  await act(() => api('/api/maps', { action: 'restartround' }), L('Рестарт раунда'));
};
ACTIONS['map-load'] = async () => {
  const map = S.pick;
  if (!map) return;
  if (await act(() => api('/api/maps', { action: 'map', map }), L('Загружаю {0}', map))) {
    closeModal();
    setTimeout(() => go('maps', true), 2500);
  }
};

/* ---------- Настройки сервера ---------- */

PAGES.settings = async (main) => {
  let d;
  try { d = await api('/api/settings'); } catch (e) { main.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; return; }
  // разделы server.cfg и боты — вкладками, в порядке файла; последняя вкладка — копии файла
  const groups = {};
  for (const s of d.settings) (groups[s.section || L('Прочее')] ||= []).push(s);
  const tabs = Object.keys(groups);
  if (!tabs.includes(S.setTab) && S.setTab !== 'backups') S.setTab = tabs[0] || 'backups';
  main.innerHTML = `<h1>${L('Настройки сервера')}</h1>
    ${pendingBanner(d.pending)}
    <div class="note">${F('bots') ? (YAPB() ? L('Настройки — из server.cfg, боты — из yapb.cfg.') : L('Настройки — из server.cfg, боты — из jk_botti.cfg.')) : L('Настройки — из server.cfg.')}
      ${L('Перед каждой записью панель сохраняет копию файла. Настройки применяются сразу. Если сервер применит настройку только после смены карты или перезапуска — панель спросит, сделать это сейчас или потом.')}</div>
    <div class="tabs" id="set-tabs">${tabs.map((g) => `<button data-act="set-tab" data-tab="${esc(g)}">${esc(secTitle(g, true))}<span class="tab-n">${groups[g].length}</span></button>`).join('')}
      <button data-act="set-tab" data-tab="backups">${L('Резервные копии')}</button></div>
    ${Object.entries(groups).map(([g, items]) => `<div class="card set-pane" data-pane="${esc(g)}"><h2>${esc(secTitle(g))}</h2><div class="tbl-wrap"><table>
      <thead><tr><th>${L('Настройка')}</th><th>${L('В файле')}</th><th>${L('На сервере')}</th><th></th></tr></thead><tbody>${
      items.map((s) => `<tr><td><span class="mono">${esc(s.name)}</span>${s.comment ? '<div class="muted">' + esc(s.comment) + '</div>' : ''}
        ${s.restart_note ? '<div>' + pill(s.restart_note, 'warn') + '</div>' : ''}</td>
        <td><input data-setting="${esc(s.name)}" ${s.secret ? 'type="password" placeholder="' + esc(L('скрыто — введите новое')) + '"' : ''} value="${esc(s.value)}"></td>
        <td class="mono">${s.secret ? '•••' : s.bot ? '<span class="muted">—</span>' : esc(s.live ?? '—')}</td>
        <td><button class="btn small" data-act="setting-save" data-name="${esc(s.name)}" data-bot="${s.bot ? 1 : ''}">${L('Сохранить')}</button></td></tr>`).join('')
    }</tbody></table></div></div>`).join('')}
    <div class="card set-pane" data-pane="backups"><h2>${L('Резервные копии')}</h2>${d.backups.length
      ? '<div class="mono">' + d.backups.map(esc).join('<br>') + '</div><p class="muted">' + L('Лежат на сервере в папке данных панели (PANEL_DATA), в cfg-backups.') + '</p>'
      : '<div class="empty">' + L('Пока ни одной правки') + '</div>'}</div>`;
  showSetTab();
};

/* Раздел server.cfg («2. Карта и раунды») — без номера, а на вкладке ещё и без имени файла
   («Боты (yapb.cfg)» → «Боты»). Русские слова, набранные ЗАГЛАВНЫМИ, — строчными, как в панели Quake. */
function secTitle(s, short) {
  let t = s.replace(/^\d+\.\s*/, '').trim();
  if (/[А-ЯЁ]{2}/.test(t)) t = t.replace(/[А-ЯЁ]+/g, (w) => w.toLowerCase());
  if (short) t = t.replace(/\s*\([^)]*\)$/, '');
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : s;
}

function showSetTab() {
  document.querySelectorAll('#set-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === S.setTab));
  document.querySelectorAll('.set-pane').forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== S.setTab));
}

ACTIONS['set-tab'] = (d) => { S.setTab = d.tab; showSetTab(); };

ACTIONS['setting-save'] = async (d) => {
  const input = document.querySelector('input[data-setting="' + CSS.escape(d.name) + '"]');
  const value = input.value;
  if (input.type === 'password' && !value && !confirm(L('Сохранить пустое значение (снять пароль)?'))) return;
  const r = await act(() => api('/api/settings', { name: d.name, value, bot: !!d.bot }), (x) => savedMsg(d.name, x));
  if (!r) return;
  await afterSettingSaved(d.name, r);
  go('settings', true);
};

/* ---------- Статистика ---------- */

PAGES.stats = async (main) => {
  let d, p;
  try {
    [d, p] = await Promise.all([api('/api/stats?tz=' + new Date().getTimezoneOffset()), api('/api/sessions')]);
  } catch (e) { main.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; return; }
  S.stats = d;
  S.sessions = p;
  if (!S.calMonth) { const n = new Date(); S.calMonth = { y: n.getFullYear(), m: n.getMonth() }; }
  const t = d.totals;
  main.innerHTML = `<h1>${L('Статистика')}</h1>
    <div class="grid kpi4">
      <div class="card"><div class="muted">${L('Матчей')}</div><div class="big">${num(t.matches)}</div></div>
      <div class="card"><div class="muted">${L('Убийств')}</div><div class="big">${num(t.kills)}</div></div>
      <div class="card"><div class="muted">${L('Сыграно')}</div><div class="big">${fmtDur(t.seconds)}</div></div>
      <div class="card"><div class="muted">${L('Живых игроков')}</div><div class="big">${num(t.humans)}</div><div class="muted">${L('были в {0} матчах', num(t.matches_with_humans))}</div></div>
    </div>
    <div class="tabs" id="st-tabs">
      <button data-act="stats-tab" data-tab="humans">${L('Живые игроки')}</button>
      <button data-act="stats-tab" data-tab="summary">${L('Сводка')}</button>
      <button data-act="stats-tab" data-tab="rounds">${L('Раунды')}</button>
      <button data-act="stats-tab" data-tab="calendar">${L('Календарь')}</button>
      <button data-act="stats-tab" data-tab="bots">${L('Боты')}</button>
      <button data-act="stats-tab" data-tab="maps">${L('Карты')}</button>
      <button data-act="stats-tab" data-tab="activity">${L('Активность')}</button>
    </div>
    <div id="st-body"></div>
    <p class="muted">${L('Лог разобран {0} · матч попадает сюда, когда карта сменилась ·', fmtTime(d.state.parsed_at))}
      <button class="btn small ghost" data-act="stats-refresh">${L('обновить сейчас')}</button></p>`;
  renderStatsTab();
};

ACTIONS['stats-tab'] = (d) => { S.statsTab = d.tab; renderStatsTab(); };
ACTIONS['stats-refresh'] = async () => {
  if (await act(() => api('/api/stats/refresh', {}), (x) => L('Добавлено матчей: {0}', x.added))) go('stats', true);
};

function playerTable(rows) {
  if (!rows.length) return '<div class="empty">' + L('Пока никого') + '</div>';
  return `<div class="tbl-wrap"><table><thead><tr><th>${L('Игрок')}</th><th class="num">${L('Матчей')}</th><th class="num">${L('Убийств')}</th>
    <th class="num">${L('Смертей')}</th><th class="num">${L('У/С')}</th><th class="num">${L('Самоубийств')}</th><th class="num">${L('Своих')}</th><th class="num">${L('В игре')}</th><th>${L('Последний раз')}</th></tr></thead><tbody>${
    rows.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${num(p.matches)}</td><td class="num">${num(p.kills)}</td>
      <td class="num">${num(p.deaths)}</td><td class="num">${dec(p.kd)}</td><td class="num">${num(p.suicides)}</td><td class="num">${num(p.teamkills || 0)}</td>
      <td class="num">${fmtDur(p.playtime)}</td><td>${fmtTime(p.last_seen_at)}</td></tr>`).join('')
  }</tbody></table></div>`;
}

function renderStatsTab() {
  const d = S.stats, tab = S.statsTab, body = $('#st-body');
  document.querySelectorAll('#st-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'humans') {
    const P = S.sessions;
    body.innerHTML = `<div class="grid split">
        <div class="card"><h2>${L('Заходы живых игроков')}</h2><div id="pg-sess"></div><p class="muted">${esc(trackingNote())}</p></div>
        <div class="card"><h2>${L('Итоги по живым игрокам')}</h2><div id="pg-hum"></div>
          <p class="muted">${L('Игрок — это IP-адрес: ники бывают одинаковые. Нажмите на ник — откроется его статистика.')}</p></div>
      </div>`;
    pagerMount($('#pg-sess'), P.sessions, 15, (el, rows) => { el.innerHTML = sessionsTable(rows); });
    pagerMount($('#pg-hum'), P.players || [], 15, (el, rows) => { el.innerHTML = humansTable(rows); });
  } else if (tab === 'summary') {
    const P = S.sessions, X = P.summary;
    body.innerHTML = `<div class="grid two">
        <div class="card"><h2>${L('Откуда игроки')}</h2><div id="pg-c"></div>
          <p class="muted">${F('geo') ? L('Страна — по IP-адресу, из базы GeoLite2 прямо на сервере (адреса никуда не отправляются).')
            : L('Базы стран GeoLite2 на сервере нет — см. GEOIP_DB в README.')}</p></div>
        <div class="card"><h2>${L('Лучшие игроки')}</h2><div id="pg-best"></div>
          <p class="muted">${L('По нику, из игрового лога — так же, как таблица ботов.')}</p></div>
      </div>
      <div class="grid three">
        <div class="card"><h2>${L('Оружие живых игроков')}</h2><div class="bars" id="w-h"></div></div>
        <div class="card"><h2>${L('Рекорды')}</h2>${recordsList(P.records)}</div>
        <div class="card"><h2>${L('Лучшие по убийствам')}</h2>${killersList(X.top_killers)}</div>
      </div>
      <div class="grid three">
        <div class="card"><h2>${L('Карты живых игроков')}</h2><div id="pg-mh"></div>
          <p class="muted">${L('Сколько заходов застали карту — где люди бывают чаще всего.')}</p></div>
        <div class="card"><h2>${L('Сколько длятся заходы')}</h2><div class="bars" id="d-h"></div>
          <p class="muted">${L('Много коротких — люди заходят и сразу уходят: стоит посмотреть, почему.')}</p></div>
        <div class="card"><h2>${L('Новые игроки')}</h2>${newcomersList(X.newcomers)}</div>
      </div>`;
    bars($('#w-h'), d.weapons_humans, 'title', 'kills', { muted: (w) => w.environment });
    barsPaged($('#pg-c'), P.countries.map((c) => ({ ...c, title: countryName(c) })), 'title', 'players', 10, { flags: true });
    pagerMount($('#pg-best'), d.humans || [], 10, (el, rows, start) => { el.innerHTML = bestTable(rows, start); });
    barsPaged($('#pg-mh'), X.maps, 'map', 'visits', 10, { mapPreview: true, fmt: (x) => times(x.visits) });
    bars($('#d-h'), X.durations, 'title', 'visits', { fmt: (x) => Pn(x.visits, 'заход', 'захода', 'заходов') });
  } else if (tab === 'rounds') {
    renderRounds(body, d);
  } else if (tab === 'calendar') {
    renderCalendar(body);
  } else if (tab === 'bots') {
    body.innerHTML = `<div class="grid two">
      <div class="card"><h2>${L('Боты')}</h2><div id="pg-bots"></div></div>
      <div class="card"><h2>${L('Оружие ботов')}</h2><div class="bars" id="w-b"></div>
        <p class="muted">${L('Серым — смерти не от оружия: падения, ловушки, двери.')}</p></div></div>`;
    bars($('#w-b'), d.weapons_bots, 'title', 'kills', { muted: (w) => w.environment });
    pagerMount($('#pg-bots'), d.bots, 15, (el, rows) => { el.innerHTML = playerTable(rows); });
  } else if (tab === 'maps') {
    body.innerHTML = `<div class="grid two"><div class="card"><h2>${L('Сколько раз играли')}</h2><div id="pg-mb"></div></div>
      <div class="card"><h2>${L('Подробно')}</h2><div id="pg-md"></div></div></div>
      <div class="card mt16"><h2>${L('Последние матчи')}</h2><div id="pg-rec"></div>
      <p class="muted">${L('Карта «?» — матч шёл, пока панель не работала: в логе WON-сервера названия карты нет.')}</p></div>`;
    barsPaged($('#pg-mb'), d.maps, 'map', 'matches', 15, { mapPreview: true });
    pagerMount($('#pg-md'), d.maps, 15, (el, rows) => { el.innerHTML = `<div class="tbl-wrap"><table><thead><tr><th>${L('Карта')}</th><th class="num">${L('Матчей')}</th>
        <th class="num">${L('С людьми')}</th><th class="num">${L('Убийств')}</th><th class="num nowrap">CT : T</th><th class="num">${L('Средний матч')}</th></tr></thead><tbody>${rows.map((m) => `<tr><td class="mono">${mapLink(m.map)}</td><td class="num">${m.matches}</td><td class="num">${m.with_humans}</td>
          <td class="num">${num(m.kills)}</td><td class="num nowrap">${m.rounds ? num(m.ct_wins) + ' : ' + num(m.t_wins) : '—'}</td><td class="num nowrap">${fmtDur(m.avg_duration)}</td></tr>`).join('')}</tbody></table></div>`; });
    pagerMount($('#pg-rec'), d.recent, 10, (el, rows) => { el.innerHTML = rows.length ? `<div class="tbl-wrap"><table class="compact"><thead><tr>
        <th>${L('Начало')}</th><th>${L('Карта')}</th><th class="num">${L('Длился')}</th><th class="num">${L('Людей')}</th><th class="num">${L('Ботов')}</th><th class="num">${L('Убийств')}</th></tr></thead><tbody>${rows.map((m) => `<tr><td>${fmtTime(m.started_at)}</td><td class="mono">${mapLink(m.map)}</td><td class="num">${fmtDur(m.duration)}</td>
          <td class="num">${m.humans}</td><td class="num">${m.bots}</td><td class="num">${num(m.kills)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">' + L('Пока ни одного законченного матча') + '</div>'; });
  } else {
    const a = d.activity;
    const labels = '<div class="hours-labels">' + Array.from({ length: 24 }, (_, i) => '<span>' + i + '</span>').join('') + '</div>';
    body.innerHTML = `<div class="note">${L('Время матчей — точное, из живого лога сервера. Часы — по часам этого компьютера.')}</div>
      <div class="card"><h2>${L('Матчи по часам суток')}</h2><div class="hours" id="hrs"></div>${labels}</div>
      <div class="grid two mt16">
        <div class="card"><h2>${L('Матчи с живыми игроками')}</h2><div class="hours" id="hrs-h"></div>${labels}</div>
        <div class="card"><h2>${L('По дням')}</h2><div class="bars" id="days"></div></div></div>`;
    hoursChart($('#hrs'), a.hours);
    hoursChart($('#hrs-h'), a.human_hours);
    bars($('#days'), a.days, 'day', 'matches');
  }
}

/* ---------- раунды Counter-Strike ---------- */

function renderRounds(body, d) {
  const t = d.totals, o = d.objectives || [];
  const share = (a) => (t.rounds ? Math.round(a * 100 / t.rounds) + '%' : '—');
  body.innerHTML = `<div class="grid three">
      <div class="card"><h2>${L('Раунды')}</h2><div class="big">${num(t.rounds)}</div>
        <dl class="kv"><dt>${team('CT')}${L('Победы спецназа')}</dt><dd>${num(t.ct_wins)} (${share(t.ct_wins)})</dd>
        <dt>${team('T')}${L('Победы террористов')}</dt><dd>${num(t.t_wins)} (${share(t.t_wins)})</dd></dl></div>
      <div class="card"><h2>${L('Бомба')}</h2><dl class="kv"><dt>${L('Поставлена')}</dt><dd>${num(t.planted)}</dd>
        <dt>${L('Взорвалась')}</dt><dd>${num(t.exploded)}</dd><dt>${L('Разминирована')}</dt><dd>${num(t.defused)}</dd></dl></div>
      <div class="card"><h2>${L('Заложники и свои')}</h2><dl class="kv"><dt>${L('Заложников спасено')}</dt><dd>${num(t.rescued)}</dd>
        <dt>${L('Убито своих')}</dt><dd>${num(t.teamkills)}</dd></dl></div>
    </div>
    <div class="card mt16"><h2>${L('Задания и убийства своих')}</h2>${o.length ? `<div class="tbl-wrap"><table><thead><tr>
      <th>${L('Игрок')}</th><th class="num">${L('Матчей')}</th><th class="num">${L('Поставил бомбу')}</th><th class="num">${L('Разминировал')}</th>
      <th class="num">${L('Спас заложников')}</th><th class="num">${L('Убил своих')}</th></tr></thead><tbody>${
      o.map((p) => `<tr><td>${p.is_bot ? '<span class="tag-bot">🤖</span> ' : ''}${esc(p.name)}</td><td class="num">${num(p.matches)}</td>
        <td class="num">${num(p.plants)}</td><td class="num">${num(p.defuses)}</td><td class="num">${num(p.rescues)}</td>
        <td class="num">${num(p.teamkills)}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty">' + L('Пока ничего — счёт идёт с первого законченного матча') + '</div>'}
      <p class="muted">${L('Счёт ведётся по нику — как и оружие. Убийство своего не засчитывается как фраг.')}</p></div>`;
}

/* ---------- заходы, календарь ---------- */

const pad2 = (n) => String(n).padStart(2, '0');
const dayKey = (d) => d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
const sessEnd = (s) => (s.online ? nowSec() : (s.left_at || s.last_seen));

function trackingNote() {
  const t = S.sessions.tracking_since;
  return t ? L('Заходы панель отмечает по живому логу сервера с {0}, время точное.', fmtDateTime(t)) : '';
}

function sessionsTable(rows) {
  if (!rows.length) return '<div class="empty">' + L('Пока никто из живых игроков не заходил.') + '</div>';
  return `<div class="tbl-wrap"><table><thead><tr><th>${L('Зашёл')}</th><th class="num">${L('Пробыл')}</th><th>${L('Игрок')}</th>
    <th>${L('IP · страна')}</th><th>${L('Карты')}</th><th class="num nowrap">${L('У / С')}</th></tr></thead><tbody>${
    rows.map((s) => `<tr><td class="nowrap">${fmtDateTime(s.joined_at)}</td>
      <td class="num nowrap">${s.online ? pill(L('на сервере'), 'ok') : fmtDur(sessEnd(s) - s.joined_at)}</td>
      <td>${playerBtn(s.ip, s.name)}</td>
      <td class="nowrap">${flagHtml(s.country)} <span class="mono">${esc(s.ip || s.address || '—')}</span></td>
      <td class="mono">${s.maps.map(mapLink).join(', ')}</td><td class="num nowrap">${s.kills} / ${s.deaths}</td></tr>`).join('')
  }</tbody></table></div>`;
}

function humansTable(rows) {
  if (!rows || !rows.length) return '<div class="empty">' + L('Пока никого') + '</div>';
  return `<div class="tbl-wrap"><table><thead><tr><th>${L('Игрок')}</th><th>IP</th><th>${L('Страна')}</th>
    <th class="num">${L('Заходов')}</th><th class="num">${L('В игре')}</th><th class="num">${L('У/С')}</th></tr></thead><tbody>${
    rows.map((p) => `<tr><td>${playerBtn(p.ip, p.name)}${p.online ? ' ' + pill(L('сейчас'), 'ok') : ''}
        ${p.names.length > 1 ? '<div class="muted fs12">' + L('ещё: {0}', p.names.slice(1).map(esc).join(', ')) + '</div>' : ''}</td>
      <td class="mono">${esc(p.ip)}</td><td class="nowrap">${countryTag(p.country)}</td>
      <td class="num">${num(p.visits)}</td><td class="num nowrap">${fmtDur(p.seconds)}</td>
      <td class="num" title="${esc(kdTip(p.kills, p.deaths))}">${dec(p.kd)}</td></tr>`).join('')
  }</tbody></table></div>`;
}

/* Ник из игрового лога → карточка игрока: адрес, с которого этим ником заходили больше всего.
   Ника нет среди заходов (только в старом логе) — просто текст. */
function bestWho(nick) {
  let best = null;
  for (const p of (S.sessions && S.sessions.players) || []) {
    if ((p.names || []).includes(nick) && (!best || p.visits > best.visits)) best = p;
  }
  return best ? playerBtn(best.ip, nick) : esc(nick);
}

/* Лучшие живые игроки — по нику, из игрового лога (как таблица ботов, только короче). */
function bestTable(rows, start = 0) {
  if (!rows.length) return '<div class="empty">' + L('Пока никого') + '</div>';
  return `<div class="tbl-wrap"><table><thead><tr><th class="num">#</th><th>${L('Игрок')}</th><th class="num">${L('Матчей')}</th>
    <th class="num">${L('Убийств')}</th><th class="num">${L('Смертей')}</th><th class="num">${L('У/С')}</th><th class="num">${L('В игре')}</th></tr></thead><tbody>${
    rows.map((p, i) => `<tr><td class="num muted">${start + i + 1}</td><td>${bestWho(p.name)}</td><td class="num">${num(p.matches)}</td>
      <td class="num">${num(p.kills)}</td><td class="num">${num(p.deaths)}</td><td class="num">${dec(p.kd)}</td>
      <td class="num nowrap">${fmtDur(p.playtime)}</td></tr>`).join('')
  }</tbody></table></div>`;
}

function killersList(rows) {
  if (!rows || !rows.length) return '<div class="empty">' + L('Пока нет данных') + '</div>';
  return '<ol class="rank-list">' + rows.map((p, i) => `<li><span class="rk">${i + 1}</span>
    <span class="who">${flagHtml(p.country)} ${playerBtn(p.ip, p.name)}</span>
    <span class="val"><b>${num(p.kills)}</b> ${L('уб.')} <span class="muted">· ${L('У/С')} ${dec(p.kd)}</span></span></li>`).join('') + '</ol>';
}

function newcomersList(rows) {
  if (!rows || !rows.length) return '<div class="empty">' + L('Пока никого') + '</div>';
  return '<ol class="rank-list">' + rows.map((p) => `<li>
    <span class="who">${flagHtml(p.country)} ${playerBtn(p.ip, p.name)}</span>
    <span class="val muted">${L('впервые {0} · {1}', fmtDateTime(p.first), times(p.visits))}</span></li>`).join('') + '</ol>';
}

function recordsList(rows) {
  if (!rows || !rows.length) return '<div class="empty">' + L('Пока нет данных') + '</div>';
  const val = (v) => (v && typeof v === 'object'
    ? (v.duration != null ? fmtDur(v.duration) : v.times != null ? times(v.times) : '') : esc(v));
  return '<ul class="recs">' + rows.map((r) => `<li><div class="muted fs12">${esc(r.title)}</div>
    <div><b>${val(r.value)}</b>${r.name ? ' — ' + playerBtn(r.ip, r.name) : ''}${r.at ? ' <span class="muted">· ' + fmtDateTime(r.at) + '</span>' : ''}</div></li>`).join('') + '</ul>';
}

function renderCalendar(body) {
  const rows = S.sessions.sessions;
  const byDay = {};
  for (const s of rows) (byDay[dayKey(new Date(s.joined_at * 1000))] ||= []).push(s);
  const { y, m } = S.calMonth;
  const first = new Date(y, m, 1);
  const lead = (first.getDay() + 6) % 7;
  const days = new Date(y, m + 1, 0).getDate();
  const counts = Object.entries(byDay).filter(([k]) => k.startsWith(y + '-' + pad2(m + 1))).map(([, v]) => v.length);
  const max = Math.max(1, ...counts);
  const today = dayKey(new Date());
  let cells = WEEKDAYS.map((w) => `<div class="cal-h">${esc(w)}</div>`).join('');
  for (let i = 0; i < lead; i++) cells += '<div class="cal-d empty-cell"></div>';
  for (let d = 1; d <= days; d++) {
    const key = y + '-' + pad2(m + 1) + '-' + pad2(d);
    const list = byDay[key] || [];
    const people = new Set(list.map((s) => s.name)).size;
    const lvl = list.length ? 1 + Math.min(3, Math.floor(3 * list.length / max)) : 0;
    cells += `<button class="cal-d l${lvl}${key === today ? ' today' : ''}${key === S.calDay ? ' sel' : ''}" data-act="cal-day" data-day="${key}" ${list.length ? '' : 'disabled'}>
      <span class="cal-n">${d}</span>${list.length ? `<span class="cal-b">${list.length}</span><span class="cal-c">${Pn(list.length, 'заход', 'захода', 'заходов')}</span><span class="cal-p">${Pn(people, 'игрок', 'игрока', 'игроков')}</span>` : ''}</button>`;
  }
  const sel = S.calDay && byDay[S.calDay] ? byDay[S.calDay].slice().sort((a, b) => b.joined_at - a.joined_at) : null;
  body.innerHTML = `<div class="note">${esc(trackingNote())}</div>
    <div class="grid two">
      <div class="card"><h2><button class="btn small ghost" data-act="cal-prev">←</button>
        ${esc(monthTitle(y, m))}<button class="btn small ghost" data-act="cal-next">→</button></h2>
        <div class="cal">${cells}</div>
        <p class="muted">${L('Чем темнее день, тем больше заходов. Нажмите на день — внизу появится список.')}</p></div>
      <div class="card"><h2>${L('Когда заходят: дни недели × часы')}</h2><div class="heat" id="heat"></div>
        <p class="muted">${L('Сколько минут живые игроки провели на сервере в каждый час — за всё время. Время — по часам этого компьютера.')}</p></div>
    </div>
    ${sel ? `<div class="card mt16"><h2>${esc(fmtDate(new Date(S.calDay + 'T12:00:00').getTime() / 1000))}</h2><div id="pg-day"></div></div>` : ''}`;
  renderHeat($('#heat'), rows);
  if (sel) pagerMount($('#pg-day'), sel, 15, (el, part) => { el.innerHTML = sessionsTable(part); });
}

function renderHeat(el, rows) {
  const grid = Array.from({ length: 7 }, () => new Array(24).fill(0));
  for (const s of rows) {
    let t = s.joined_at * 1000;
    const end = sessEnd(s) * 1000;
    while (t < end) {
      const d = new Date(t);
      const next = new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours() + 1).getTime();
      grid[(d.getDay() + 6) % 7][d.getHours()] += (Math.min(next, end) - t) / 60000;
      t = next;
    }
  }
  const max = Math.max(1, ...grid.flat());
  let html = '<div class="heat-h"></div>' + Array.from({ length: 24 }, (_, h) => `<div class="heat-h">${h % 3 ? '' : h}</div>`).join('');
  grid.forEach((row, w) => {
    html += `<div class="heat-w">${esc(WEEKDAYS[w])}</div>`;
    row.forEach((v, h) => {
      const lvl = v ? 1 + Math.min(3, Math.floor(3 * v / max)) : 0;
      html += `<div class="heat-c l${lvl}" title="${esc(WEEKDAYS[w] + ' ' + pad2(h) + ':00–' + pad2(h + 1) + ':00 — ' + L('{0} мин', Math.round(v)))}"></div>`;
    });
  });
  el.innerHTML = html;
}

ACTIONS['cal-prev'] = () => { const c = S.calMonth; S.calMonth = c.m ? { y: c.y, m: c.m - 1 } : { y: c.y - 1, m: 11 }; renderStatsTab(); };
ACTIONS['cal-next'] = () => { const c = S.calMonth; S.calMonth = c.m < 11 ? { y: c.y, m: c.m + 1 } : { y: c.y + 1, m: 0 }; renderStatsTab(); };
ACTIONS['cal-day'] = (d) => { S.calDay = S.calDay === d.day ? null : d.day; renderStatsTab(); };

function hoursChart(el, values) {
  const max = Math.max(...values, 1);
  el.innerHTML = '';
  values.forEach((v, i) => {
    const c = document.createElement('div'); c.className = 'col';
    c.style.height = (100 * v / max).toFixed(1) + '%';
    c.title = i + ':00 — ' + v;
    el.appendChild(c);
  });
}

/* ---------- Логи ---------- */

PAGES.logs = async (main) => {
  main.innerHTML = `<h1>${L('Логи')}</h1>
    <div class="card"><div class="row mb12">
      <select id="lg-key"><option value="live">${L('Игра (живой лог)')}</option>
        ${F('console') ? `<option value="console">${F('container') ? L('Консоль сервера (docker logs)') : L('Консоль сервера')}</option>` : ''}
        <option value="hlds">${L('Лог сервера (L*.log)')}</option></select>
      <select id="lg-lines"><option>100</option><option selected>300</option><option>1000</option><option>3000</option></select>
      <input id="lg-grep" class="wide" placeholder="${esc(L('Фильтр, например killed или connected'))}">
      <button class="btn primary" data-act="logs-load">${L('Показать')}</button>
      <label class="row"><input type="checkbox" id="lg-follow"> ${L('обновлять')}</label></div>
      <div id="lg-files" class="muted mb8"></div>
      <pre class="log" id="lg-out"></pre>
      <p class="muted">${L('Пароль rcon, который движок пишет в лог, здесь заменён на ***. Время в строках лога — по часам сервера.')}</p></div>`;
  $('#lg-grep').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadLogs(); });
  $('#lg-key').addEventListener('change', loadLogs);
  await loadLogs();
  every(5000, () => { if ($('#lg-follow') && $('#lg-follow').checked) loadLogs(); });
};

async function loadLogs() {
  const key = $('#lg-key').value;
  const q = new URLSearchParams({ log: key, lines: $('#lg-lines').value, grep: $('#lg-grep').value });
  let d;
  try { d = await api('/api/logs?' + q); } catch (e) { $('#lg-out').textContent = e.message; return; }
  const f = d.files[key];
  $('#lg-files').textContent = f ? f.path + (f.size ? ' · ' + fmtBytes(f.size) + ' · ' + L('изменён {0}', fmtTime(f.mtime)) : '') : '';
  const out = $('#lg-out');
  out.textContent = d.lines.length ? d.lines.join('\n') : L('(пусто)');
  out.scrollTop = out.scrollHeight;
}
ACTIONS['logs-load'] = () => loadLogs();

/* ---------- Консоль ---------- */

PAGES.console = async (main) => {
  main.innerHTML = `<h1>${L('Консоль rcon')}</h1>
    <div class="card"><div class="row"><input id="cn-cmd" class="wide mono" placeholder="status" autocomplete="off">
      <button class="btn primary" data-act="console-run">${L('Выполнить')}</button></div>
      <pre class="out" id="cn-out">${L('Ответ сервера появится здесь. Каждая команда пишется в журнал действий.')}</pre></div>
    <div class="card"><h2>${L('Справочник команд')}</h2><p class="muted">${L('Команды выделенного сервера {0}. Нажмите на команду, чтобы подставить её.', GAME)}</p>
      <div class="tbl-wrap"><table class="cmd-ref"><tbody id="cn-ref"></tbody></table></div></div>`;
  $('#cn-cmd').addEventListener('keydown', (e) => { if (e.key === 'Enter') ACTIONS['console-run'](); });
  $('#cn-ref').addEventListener('click', (e) => {
    const td = e.target.closest('td[data-cmd]'); if (!td) return;
    const c = td.dataset.cmd;
    $('#cn-cmd').value = c.startsWith('<') ? '' : c.split(' <')[0].split(' [')[0] + ' '; $('#cn-cmd').focus();
  });
  const ref = await act(() => api('/api/commands'));
  if (ref) $('#cn-ref').innerHTML = ref.map((c) => `<tr><td data-cmd="${esc(c.cmd)}">${esc(c.cmd)}</td><td>${esc(c.help)}</td></tr>`).join('');
};

ACTIONS['console-run'] = async () => {
  const command = $('#cn-cmd').value.trim(); if (!command) return;
  $('#cn-out').textContent = '…';
  try {
    const d = await api('/api/console', { command });
    $('#cn-out').textContent = d.output || L('(сервер ничего не ответил — для многих команд это нормально)');
  } catch (e) { $('#cn-out').textContent = L('Ошибка: {0}', e.message); }
};

/* ---------- Журнал ---------- */

PAGES.audit = async (main) => {
  let rows;
  try { rows = await api('/api/audit'); } catch (e) { main.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; return; }
  main.innerHTML = `<h1>${L('Журнал действий')}</h1><div class="card"><div id="pg-audit"></div></div>`;
  pagerMount($('#pg-audit'), rows, 25, (el, part) => { el.innerHTML = part.length ? `<div class="tbl-wrap"><table>
    <thead><tr><th>${L('Когда')}</th><th>${L('Действие')}</th><th>${L('Подробности')}</th><th>${L('Итог')}</th></tr></thead><tbody>${
    part.map((r) => `<tr><td>${fmtTime(r.at)}</td><td>${esc(r.action)}</td><td class="mono">${esc(r.detail)}</td>
      <td>${r.ok ? pill(L('ок'), 'ok') : pill(L('ошибка'), 'bad')}${r.output ? '<div class="muted mono">' + esc(r.output.slice(0, 200)) + '</div>' : ''}</td></tr>`).join('')
  }</tbody></table></div>` : '<div class="empty">' + L('Пока пусто') + '</div>'; });
};

/* ---------- Настройки панели ---------- */

PAGES.panel = async (main) => {
  main.innerHTML = '<h1>' + L('Настройки панели') + '</h1>';
  settingsInto(main, false);
};

/* ---------- Бэкап: копии статистики ---------- */

PAGES.backups = async (main) => {
  main.innerHTML = '<h1>' + L('Бэкап') + '</h1><div class="card" id="bk-card"></div>';
  try { $('#bk-card').innerHTML = backupsHtml(await api('/api/backups')); } catch (e) { $('#bk-card').innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

function backupsHtml(d) {
  const kinds = { auto: L('каждый день'), manual: L('вручную'), 'before-restore': L('перед восстановлением'), upload: L('с компьютера') };
  const n = (x) => (x == null ? '—' : num(x));
  return `<h2>${L('Копии статистики')}</h2>
    <p class="muted">${L('Раз в сутки панель сама сохраняет копию всей статистики: матчи, игроков, заходы, журнал действий. Хранятся копии за последние {0}, самая свежая — всегда.', Pn(d.days, 'день', 'дня', 'дней'))}</p>
    <div class="bk-actions"><button class="btn primary" data-act="bk-make">${L('Сделать копию сейчас')}</button>
      <button class="btn" data-act="bk-upload">${L('Загрузить с компьютера')}</button></div>
    ${d.items.length ? `<div class="tbl-wrap mt12"><table><thead><tr><th>${L('Когда')}</th><th>${L('Какая')}</th>
      <th class="num">${L('Матчей')}</th><th class="num">${L('Игроков')}</th><th>${L('Последний матч')}</th><th class="num">${L('Размер')}</th><th></th></tr></thead><tbody>${
      d.items.map((x) => `<tr><td class="nowrap">${fmtDateTime(x.at)}</td><td>${esc(kinds[x.kind] || x.kind)}</td>
        <td class="num">${n(x.matches)}</td><td class="num">${n(x.players)}</td><td class="nowrap">${x.last_match ? fmtDateTime(x.last_match) : '—'}</td>
        <td class="num nowrap">${fmtBytes(x.size)}</td>
        <td class="nowrap"><button class="btn" data-act="bk-save" data-name="${esc(x.name)}">${L('Скачать')}</button>
          <button class="btn" data-act="bk-restore" data-name="${esc(x.name)}" data-at="${x.at}">${L('Восстановить')}</button></td></tr>`).join('')
    }</tbody></table></div>` : '<div class="empty mt12">' + L('Копий пока нет — первая появится через пару минут после запуска панели.') + '</div>'}
    <div class="muted fs12 mt8">${L('«Восстановить» возвращает статистику к выбранной копии. Перед этим панель сохраняет текущую — её тоже можно вернуть. Всё, что сыграно после копии, панель дочитает из живого лога сервера, если он с тех пор не обрезался.')}</div>
    <div class="muted fs12 mt8">${L('«Скачать» и «Сделать копию сейчас» спрашивают, куда сохранить файл на компьютере. «Загрузить с компьютера» — выбрать такой файл; после проверки панель спросит, восстановить ли статистику из него.')}</div>`;
}

const bkShow = (d) => { if (d && $('#bk-card')) $('#bk-card').innerHTML = backupsHtml(d); };
const bkFileName = (name) => (SITE.title || GAME).replace(/[^\w.-]+/g, '_') + '-' + name;

/* Сохранить копию на компьютер. Где браузер умеет (Chrome, Edge) — окно «куда сохранить»; иначе — обычное
   скачивание в папку загрузок. handle — уже выбранное место (окно надо открыть сразу по нажатию). */
async function bkPick(suggested) {
  if (!window.showSaveFilePicker) return null;
  try {
    return await window.showSaveFilePicker({ suggestedName: suggested,
      types: [{ description: L('Копия статистики'), accept: { 'application/gzip': ['.gz'] } }] });
  } catch (e) { return false; }   // окно закрыли — не сохранять
}

async function bkSave(name, handle) {
  const url = '/api/backups/file?name=' + encodeURIComponent(name);
  if (handle) {
    const r = await fetch(url, { credentials: 'same-origin' });
    if (!r.ok) throw new Error(L('Ошибка {0}', r.status));
    const w = await handle.createWritable();
    await w.write(await r.blob());
    await w.close();
    return;
  }
  const a = document.createElement('a');
  a.href = url;
  a.download = bkFileName(name);
  document.body.appendChild(a);
  a.click();
  a.remove();
}

ACTIONS['bk-make'] = async () => {
  const t = new Date();
  const stamp = t.getFullYear() + pad2(t.getMonth() + 1) + pad2(t.getDate()) + '-' + pad2(t.getHours()) + pad2(t.getMinutes()) + pad2(t.getSeconds());
  const handle = await bkPick(bkFileName('panel-' + stamp + '-manual.db.gz'));
  const d = await act(() => api('/api/backups', { action: 'create' }));
  if (!d) return;
  bkShow(d);
  if (handle === false) { toast(L('Копия сохранена на сервере')); return; }
  await act(() => bkSave(d.items[0].name, handle), L('Копия сохранена на сервере и на компьютере'));
};

ACTIONS['bk-save'] = async (b) => {
  const handle = await bkPick(bkFileName(b.name));
  if (handle === false) return;
  await act(() => bkSave(b.name, handle), handle ? L('Копия сохранена на компьютере') : '');
};

async function bkRestore(name, at, asked) {
  if (!asked && !confirm(L('Вернуть статистику к копии от {0}? Текущая статистика сначала сохранится отдельной копией.', fmtDateTime(at)))) return;
  toast(L('Выполняю…'));
  bkShow(await act(() => api('/api/backups', { action: 'restore', name }), L('Статистика восстановлена')));
}

ACTIONS['bk-restore'] = (b) => bkRestore(b.name, Number(b.at));

// выбор файла: окно выбора не сообщает об отмене, поэтому кнопку не держим — дальше всё в onchange
ACTIONS['bk-upload'] = () => {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = '.gz,.db';
  inp.onchange = async () => {
    const file = inp.files[0];
    if (!file) return;
    toast(L('Загружаю {0}…', file.name));
    const d = await act(async () => {
      const r = await fetch('/api/backups/upload', { method: 'POST', credentials: 'same-origin', body: file,
        headers: { 'X-CSRF': S.csrf, 'Content-Type': 'application/octet-stream' } });
      let j;
      try { j = await r.json(); } catch (e) { throw new Error(L('Панель ответила не JSON ({0})', r.status)); }
      if (!j.ok) throw new Error(j.error ? Lsrv(j.error) : L('Ошибка {0}', r.status));
      return translateReply(j.data);
    });
    if (!d) return;
    bkShow(d);
    const x = d.item;
    const what = L('В копии: {0}, {1}, последний матч — {2}.', Pn(x.matches || 0, 'матч', 'матча', 'матчей'),
      Pn(x.players || 0, 'игрок', 'игрока', 'игроков'), x.last_match ? fmtDateTime(x.last_match) : '—');
    if (confirm(L('Копия загружена. {0} Восстановить статистику из неё сейчас? Текущая статистика сначала сохранится отдельной копией.', what))) {
      await bkRestore(x.name, x.at, true);
    }
    else toast(L('Копия лежит в списке — восстановить её можно позже.'));
  };
  inp.click();
};

/* ---------- перезапуск сервера ---------- */

ACTIONS.container = async (d) => {
  const q = { restart: L('Перезапустить игровой сервер? Игроков выкинет.'), stop: L('Остановить игровой сервер? Игроков выкинет.'),
    start: L('Запустить игровой сервер?') }[d.action];
  if (!confirm(q)) return;
  toast(L('Выполняю…'));
  await act(() => api('/api/container', { action: d.action }), L('Готово. Сервер поднимется за несколько секунд'));
};

document.addEventListener('DOMContentLoaded', start);
