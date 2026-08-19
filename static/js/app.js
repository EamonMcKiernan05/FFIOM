/* FFIOM shared utilities — auth, api, theme, logos, toast, modal. No page logic here. */

const API_BASE = '/api';
let currentUser = null;
let currentTeam = null;

// ===== AUTH =====
function getToken() { return localStorage.getItem('token'); }

// Refresh the access token when it expires (15 min). The refresh token lives in
// the httpOnly "refresh_token" cookie (set at login) and is also returned in the
// auth response body — the body copy works even where the secure cookie can't
// be stored (e.g. plain http dev). Returns true on success.
let refreshing = null;
async function tryRefreshToken() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const stored = localStorage.getItem('refresh_token');
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: stored ? JSON.stringify({ refresh_token: stored }) : undefined,
      });
      if (!res.ok) return false;
      const data = await res.json();
      localStorage.setItem('token', data.access_token);
      if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
      return true;
    } catch (_) {
      return false;
    } finally {
      setTimeout(() => { refreshing = null; }, 0);
    }
  })();
  return refreshing;
}

async function apiFetch(url, options = {}, _isRetry = false) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const response = await fetch(`${API_BASE}${url}`, { ...options, headers, credentials: 'include' });
  if (response.status === 401 && !_isRetry) {
    if (await tryRefreshToken()) {
      return apiFetch(url, options, true);
    }
    logout(false);
    throw new Error('Unauthorized');
  }
  return response;
}

async function apiJson(url, options = {}) {
  const r = await apiFetch(url, options);
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try { const e = await r.json(); msg = e.detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

async function loadMe() {
  if (!getToken()) return null;
  try {
    const data = await apiJson('/users/me');
    // /users/me returns {user: {...}, team: {...}} — unwrap
    currentUser = data.user || data;
    currentTeam = data.team && data.team.id ? data.team : null;
    return currentUser;
  } catch (_) {
    return null;
  }
}

function logout(redirect = true) {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  currentUser = null;
  currentTeam = null;
  // Revoke the refresh token (best-effort; the refresh cookie travels automatically)
  fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => {});
  if (redirect) window.location.href = '/';
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errBox = document.getElementById('login-error');
  if (!username || !password) {
    return showFormError(errBox, 'Enter your username and password.');
  }
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'include',
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      const msg = response.status === 429
        ? 'Too many attempts. Please wait a minute and try again.'
        : (err.detail || 'Login failed');
      showFormError(errBox, msg);
      return showToast(msg, 'error');
    }
    const data = await response.json();
    localStorage.setItem('token', data.access_token);
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
    window.location.href = '/my-team';
  } catch (err) {
    showFormError(errBox, 'Login failed: ' + err.message);
    showToast('Login failed: ' + err.message, 'error');
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const username = document.getElementById('reg-username').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const teamName = document.getElementById('reg-team-name').value.trim();
  const errBox = document.getElementById('register-error');
  // Client-side pre-validation mirroring the API policy (fail fast, clear message)
  if (username.length < 3) return showFormError(errBox, 'Username must be at least 3 characters.');
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return showFormError(errBox, 'Enter a valid email address.');
  if (!teamName) return showFormError(errBox, 'Choose a team name.');
  if (password.length < 10 || !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password)) {
    return showFormError(errBox, 'Password must be at least 10 characters with an uppercase letter, a lowercase letter and a number.');
  }
  try {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password, team_name: teamName }),
      credentials: 'include',
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      const msg = response.status === 429
        ? 'Too many attempts. Please wait a minute and try again.'
        : (err.detail || 'Registration failed');
      showFormError(errBox, msg);
      return showToast(msg, 'error');
    }
    const data = await response.json();
    localStorage.setItem('token', data.access_token);
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
    showToast('Account created! Pick your squad on the Transfers page.', 'success');
    window.location.href = '/transfers';
  } catch (err) {
    showFormError(errBox, 'Registration failed: ' + err.message);
    showToast('Registration failed: ' + err.message, 'error');
  }
}

// Form error state helper (pre-launch checklist: visible inline error states)
function showFormError(box, msg) {
  if (box) {
    box.textContent = msg;
    box.hidden = false;
  }
}

// Confirmation modal for destructive/important actions (pre-launch checklist)
function confirmModal(title, message, confirmLabel, onConfirm) {
  openModal(`
    <h3 style="margin-bottom:1.2rem">${escapeHtml(title)}</h3>
    <p style="color:var(--theme-on-surface-variant);margin-bottom:2rem">${escapeHtml(message)}</p>
    <div style="display:flex;gap:0.8rem;justify-content:flex-end">
      <button class="button button--outlined" onclick="closeModal()">Cancel</button>
      <button class="button button--filled" id="confirm-modal-ok">${escapeHtml(confirmLabel)}</button>
    </div>`);
  document.getElementById('confirm-modal-ok').addEventListener('click', () => {
    closeModal();
    onConfirm();
  });
}

// ===== NAV =====
function renderNavAuth() {
  const el = document.getElementById('nav-auth');
  if (!el) return;
  if (currentUser) {
    el.innerHTML = `
      <span class="game-nav__user">${escapeHtml(currentUser.username)}</span>
      <button class="button button--text button--small" onclick="logout()">Sign out</button>`;
  } else {
    el.innerHTML = `<a class="button button--accent button--small" href="/login">Sign in</a>`;
  }
}

function initNav() {
  const toggle = document.getElementById('nav-toggle');
  const links = document.getElementById('nav-links');
  if (toggle && links) {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.addEventListener('click', () => {
      const open = links.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

  // Mark the current page's nav link active (pages are static shells)
  const path = window.location.pathname;
  document.querySelectorAll('.game-nav__link').forEach((a) => {
    const href = a.getAttribute('href');
    if (href === path || (href !== '/' && path.startsWith(href))) {
      a.classList.add('is-active');
    } else if (href === '/' && path !== '/') {
      a.classList.remove('is-active');
    }
  });

  // Site search (pre-launch checklist: full site search)
  const searchBtn = document.getElementById('nav-search-btn');
  if (searchBtn) searchBtn.addEventListener('click', openSiteSearch);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openSiteSearch();
    }
    if (e.key === 'Escape') closeModal();
  });
}

// ===== SITE SEARCH =====
const SEARCH_INDEX = [
  { title: 'Home', url: '/', desc: 'Season overview, top players, gameweek status' },
  { title: 'My Team', url: '/my-team', desc: 'Your squad, captain, vice-captain and chips' },
  { title: 'Transfers', url: '/transfers', desc: 'Buy and sell players, transfer market' },
  { title: 'Players', url: '/players', desc: 'All players, prices, points, goals, assists, form' },
  { title: 'Fixtures', url: '/fixtures', desc: 'Match schedule, difficulty ratings, results' },
  { title: 'Gameweeks', url: '/gameweeks', desc: 'Deadlines, fixture counts, scoring status' },
  { title: 'History', url: '/history', desc: 'Your gameweek-by-gameweek record' },
  { title: 'Leaderboard', url: '/leaderboard', desc: 'Overall manager standings' },
  { title: 'Leagues', url: '/leagues', desc: 'Create or join private mini-leagues' },
  { title: 'Dream Team', url: '/dream-team', desc: 'Best XI of each gameweek' },
  { title: 'Rankings', url: '/rankings', desc: 'Player rankings by points, goals, form' },
  { title: 'Help & rules', url: '/help', desc: 'How scoring works, FAQ, squad rules' },
  { title: 'Register', url: '/register', desc: 'Create an account and pick your team' },
  { title: 'Sign in', url: '/login', desc: 'Sign in to your account' },
  { title: 'Privacy policy', url: '/privacy', desc: 'What we store and what we never do' },
];

function openSiteSearch() {
  openModal(`
    <h3 style="margin-bottom:1.2rem">Search FFIOM</h3>
    <input class="search-input" id="site-search-input" type="search" placeholder="Search pages&hellip;" autocomplete="off">
    <div class="search-results" id="site-search-results"></div>`);
  const input = document.getElementById('site-search-input');
  const run = () => {
    const q = input.value.trim().toLowerCase();
    const hits = SEARCH_INDEX.filter(
      (p) => !q || p.title.toLowerCase().includes(q) || p.desc.toLowerCase().includes(q)
    );
    document.getElementById('site-search-results').innerHTML = hits.length
      ? hits.map((p) => `<a href="${p.url}">${escapeHtml(p.title)}<span>${escapeHtml(p.desc)}</span></a>`).join('')
      : '<p style="color:var(--theme-on-surface-variant)">No pages match.</p>';
  };
  input.addEventListener('input', run);
  run();
  input.focus();
}

// ===== COOKIE BANNER =====
function initCookieBanner() {
  const banner = document.getElementById('cookie-banner');
  if (!banner) return;
  if (!localStorage.getItem('cookie_ack')) banner.hidden = false;
  const btn = document.getElementById('cookie-accept');
  if (btn) btn.addEventListener('click', () => {
    localStorage.setItem('cookie_ack', '1');
    banner.hidden = true;
  });
}

// ===== SCROLL UX: progress bar + back-to-top =====
function initScrollUX() {
  const bar = document.getElementById('scroll-progress');
  const btt = document.getElementById('back-to-top');
  const onScroll = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (bar) bar.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
    if (btt) btt.classList.toggle('is-visible', window.scrollY > 600);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  if (btt) btt.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

// ===== FOOTER YEAR (auto-updating copyright) =====
function initFooterYear() {
  const el = document.getElementById('footer-year');
  if (el) el.textContent = String(new Date().getFullYear());
}

// ===== PASSWORD VISIBILITY TOGGLES =====
function initPasswordToggles() {
  document.querySelectorAll('[data-pw-toggle]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.pwToggle);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });
}

// ===== THEME =====
function toggleTheme() {
  const html = document.documentElement;
  const next = html.classList.contains('dark-theme') ? 'light-theme' : 'dark-theme';
  html.classList.remove('light-theme', 'dark-theme');
  html.classList.add(next);
  localStorage.setItem('theme', next);
}

// ===== CLUB LOGOS =====
// Team name (as stored in FFIOM-DB) -> logo file in /static/img/clubs/
const CLUB_LOGOS = {
  'Ayre United': 'AyreUnited.png',
  'Braddan': 'Braddan.png',
  'Colby': 'Colby.png',
  'Corinthians': 'Corinthians.png',
  'DHSOB': 'DHSOB.png',
  'Douglas & District': 'DouglasAndDistrict.png',
  'Douglas and District': 'DouglasAndDistrict.png',
  'Douglas Royal': 'DouglasRoyal.png',
  'Foxdale': 'Foxdale.png',
  'Governors Athletic': 'GovernorsAthletic.png',
  "Governor's Athletic": 'GovernorsAthletic.png',
  'Gymnasium': 'Gymnasium.png',
  'Gyms': 'Gymnasium.png',
  'Laxey': 'Laxey.png',
  'Malew': 'Malew.png',
  'Marown': 'Marown.png',
  'Michael United': 'MichaelUnited.png',
  'Onchan': 'Onchan.png',
  'Peel': 'Peel.png',
  'Pulrose United': 'Pulrose.png',
  'Pulrose': 'Pulrose.png',
  'Ramsey': 'Ramsey.png',
  'Ramsey YCOB': 'RYCOB.png',
  'RYCOB': 'RYCOB.png',
  'Rushen United': 'Rushen.jpg',
  'Rushen': 'Rushen.jpg',
  'St Georges': 'StGeorges.png',
  "St George's": 'StGeorges.png',
  'St Johns United': 'StJohns.png',
  "St John's": 'StJohns.png',
  'St Marys': 'StMarys.jpg',
  "St Mary's": 'StMarys.jpg',
  'Union Mills': 'UnionMills.png',
};

function clubLogo(teamName, cls = 'club-badge') {
  const file = CLUB_LOGOS[teamName];
  if (!file) {
    return `<span class="${cls}" style="display:inline-flex;align-items:center;justify-content:center;background:var(--theme-primary-container);border-radius:var(--radius-s);font-size:1rem;font-weight:700;color:var(--theme-on-primary-container)">${escapeHtml((teamName || '?').slice(0, 2).toUpperCase())}</span>`;
  }
  return `<img class="${cls}" src="/static/img/clubs/${file}" alt="${escapeHtml(teamName)}" loading="lazy">`;
}

// ===== TOAST =====
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ===== MODAL =====
function openModal(html) {
  let overlay = document.getElementById('modal-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = '<div class="modal" id="modal-sheet" role="dialog"></div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });
  }
  document.getElementById('modal-sheet').innerHTML =
    '<button class="modal__close" onclick="closeModal()" aria-label="Close">&times;</button>' + html;
  overlay.classList.add('is-open');
}
function closeModal() {
  const overlay = document.getElementById('modal-overlay');
  if (overlay) overlay.classList.remove('is-open');
}

// ===== HELPERS =====
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ' ' +
         d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function fmtCountdown(deadline) {
  if (!deadline) return '';
  const diff = new Date(deadline) - Date.now();
  if (diff <= 0) return 'Closed';
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  return `${hours}h ${mins}m`;
}

function requireAuth(pageName) {
  if (!getToken()) {
    const main = document.querySelector('main .container') || document.querySelector('main');
    main.innerHTML = `
      <div class="empty-state">
        <h2>Sign in required</h2>
        <p style="margin:1.2rem 0 2.4rem">You need to sign in to view ${escapeHtml(pageName)}.</p>
        <a class="button button--filled" href="/login">Sign in</a>
      </div>`;
    return false;
  }
  return true;
}

// ===== BOOT =====
document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initCookieBanner();
  initScrollUX();
  initFooterYear();
  initPasswordToggles();
  await loadMe();
  renderNavAuth();
  if (typeof initPage === 'function') initPage();
});
