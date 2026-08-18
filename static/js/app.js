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
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'include',
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      return showToast(err.detail || 'Login failed', 'error');
    }
    const data = await response.json();
    localStorage.setItem('token', data.access_token);
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
    window.location.href = '/my-team';
  } catch (err) {
    showToast('Login failed: ' + err.message, 'error');
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const username = document.getElementById('reg-username').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const teamName = document.getElementById('reg-team-name').value.trim();
  try {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password, team_name }),
      credentials: 'include',
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      return showToast(err.detail || 'Registration failed', 'error');
    }
    const data = await response.json();
    localStorage.setItem('token', data.access_token);
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
    showToast('Account created! Pick your squad on the Transfers page.', 'success');
    window.location.href = '/transfers';
  } catch (err) {
    showToast('Registration failed: ' + err.message, 'error');
  }
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
    toggle.addEventListener('click', () => links.classList.toggle('is-open'));
  }
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
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
  await loadMe();
  renderNavAuth();
  if (typeof initPage === 'function') initPage();
});
