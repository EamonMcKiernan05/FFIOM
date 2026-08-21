/* FFIOM per-page renderers. Dispatches on document.body.dataset.page. */

function initPage() {
  const page = document.body.dataset.page;
  const renderers = {
    'home': renderHome,
    'my-team': renderMyTeam,
    'transfers': renderTransfers,
    'players': renderPlayers,
    'fixtures': renderFixtures,
    'gameweeks': renderGameweeks,
    'history': renderHistory,
    'leaderboard': renderLeaderboard,
    'leagues': renderLeagues,
    'dream-team': renderDreamTeam,
    'rankings': renderRankings,
    'help': () => {},
    'login': () => {},
    'register': () => {},
  };
  const fn = renderers[page];
  if (fn) {
    // Renderers are async (return a Promise), but some (help/login/register)
    // are synchronous — guard the .catch so a non-Promise return doesn't throw.
    const result = fn();
    if (result && typeof result.catch === 'function') {
      result.catch((err) => {
        console.error(page, err);
        showToast('Failed to load: ' + err.message, 'error');
      });
    }
  }
}

/* ---------- HOME ---------- */
async function renderHome() {
  const banner = document.getElementById('gw-banner');
  try {
    const info = await apiJson('/gameweek-history/current-gw-info');
    if (info.status === 'season_not_started') {
      banner.innerHTML = `<div class="gw-banner"><div><strong>Season not started</strong><div style="color:var(--theme-on-surface-variant);font-size:1.4rem">Gameweek ${info.next_gameweek} deadline: ${fmtDate(info.next_deadline)}</div></div></div>`;
    } else if (info.gameweek_number) {
      banner.innerHTML = `
        <div class="gw-banner">
          <div>
            <span class="badge ${info.is_closed ? 'badge--closed' : 'badge--live'}">${info.is_closed ? 'Closed' : 'Live'}</span>
            <strong style="margin-left:0.8rem">Gameweek ${info.gameweek_number}</strong>
          </div>
          <div style="text-align:right">
            <div style="font-size:1.2rem;color:var(--theme-on-surface-variant)">Deadline</div>
            <div class="gw-banner__countdown" id="gw-countdown">${fmtDate(info.deadline)}</div>
          </div>
        </div>`;
      if (info.deadline && !info.is_closed) {
        setInterval(() => {
          const el = document.getElementById('gw-countdown');
          if (el) el.textContent = fmtCountdown(info.deadline) + ' — ' + fmtDate(info.deadline);
        }, 30000);
      }
    }
  } catch (_) { banner.innerHTML = ''; }

  // Top players rail
  try {
    const players = await apiJson('/players/?order_by=points');
    const top = players.slice(0, 5);
    document.getElementById('home-top-players').innerHTML = `
      <h2 style="margin-bottom:1.6rem">Top players this season</h2>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>#</th><th>Player</th><th>Club</th><th class="num">Pts</th><th class="num">Price</th></tr></thead>
        <tbody>${top.map((p, i) => `
          <tr>
            <td>${i + 1}</td>
            <td>${escapeHtml(p.name)}</td>
            <td><span class="team-cell">${clubLogo(p.team && p.team.name, 'club-badge club-badge--small')}${escapeHtml(p.team ? p.team.name : '')}</span></td>
            <td class="num">${p.total_points}</td>
            <td class="num">£${p.price.toFixed(1)}m</td>
          </tr>`).join('')}
        </tbody>
      </table></div>
      <p style="margin-top:1.6rem"><a href="/players">View all players &rarr;</a></p>`;
  } catch (_) {}

  // Stats cards
  try {
    const gws = await apiJson('/gameweeks/');
    const played = gws.gameweeks.filter((g) => g.scored).length;
    document.getElementById('home-stats').innerHTML = `
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-card__label">Season</div><div class="stat-card__value">${escapeHtml(gws.season)}</div></div>
        <div class="stat-card"><div class="stat-card__label">Gameweeks scored</div><div class="stat-card__value">${played}</div></div>
        <div class="stat-card"><div class="stat-card__label">Total gameweeks</div><div class="stat-card__value">${gws.gameweeks.length}</div></div>
      </div>`;
  } catch (_) {}
}

/* ---------- MY TEAM ---------- */
async function renderMyTeam() {
  const root = document.getElementById('my-team-root');
  if (!requireAuth('My Team')) return;
  if (!currentTeam) {
    root.innerHTML = `<div class="empty-state"><h2>No team yet</h2><p style="margin:1.2rem 0 2.4rem">Create your squad to get started.</p><a class="button button--filled" href="/transfers">Pick your squad</a></div>`;
    return;
  }
  const [squad, chips] = await Promise.all([
    apiJson('/users/squad').catch(() => []),
    apiJson('/users/chips').catch(() => ({})),
  ]);

  if (!squad.length) {
    root.innerHTML = `<div class="empty-state"><h2>Squad empty</h2><p style="margin:1.2rem 0 2.4rem">Head to Transfers to build your 13-man squad.</p><a class="button button--filled" href="/transfers">Go to Transfers</a></div>`;
    return;
  }

  // Normalize: API returns {player: {name, team, price...}, is_starting, ...}
  const norm = squad.map((s) => ({
    id: s.id,
    player_id: s.player_id,
    name: (s.player && s.player.name) || s.name || 'Unknown',
    team_name: (s.player && s.player.team && s.player.team.name) || s.team_name || '',
    price: s.purchase_price ?? s.selling_price ?? (s.player && s.player.price) ?? 0,
    is_captain: !!s.is_captain,
    is_vice_captain: !!s.is_vice_captain,
    is_starting: s.is_starting !== false && !s.is_bench,
    bench_priority: s.bench_priority ?? s.bench_order ?? 99,
    gw_points: s.gw_points ?? 0,
    total_points: s.total_points ?? 0,
  }));

  const starters = norm.filter((s) => s.is_starting);
  const bench = norm.filter((s) => !s.is_starting).sort((a, b) => a.bench_priority - b.bench_priority);
  // Lay starters out in balanced rows of up to 4 across the pitch
  const rows = [];
  for (let i = 0; i < starters.length; i += 4) rows.push(starters.slice(i, i + 4));

  root.innerHTML = `
    <div class="gw-banner">
      <div><strong>${escapeHtml(currentTeam.name)}</strong>
        <div style="font-size:1.4rem;color:var(--theme-on-surface-variant)">Total points: ${currentTeam.total_points ?? '—'} &middot; Bank: £${(currentTeam.budget_remaining ?? currentTeam.bank ?? 0).toFixed(1)}m</div>
      </div>
      <div class="chip-row" id="chip-row"></div>
    </div>
    <h2 style="margin:2.4rem 0 1.6rem">Starting XI</h2>
    <div class="pitch">
      ${rows.map((row) => `<div class="pitch__row">${row.map(pitchPlayerHtml).join('')}</div>`).join('')}
    </div>
    <h2 style="margin:2.4rem 0 1.6rem">Bench</h2>
    <div class="card">
      <div class="pitch__row" style="justify-content:flex-start">
        ${bench.map(pitchPlayerHtml).join('') || '<span style="color:var(--theme-on-surface-variant)">No bench players</span>'}
      </div>
    </div>`;

  renderChips(chips);
}

function pitchPlayerHtml(s) {
  const badge = s.is_captain ? '<span class="pitch-player__c">C</span>'
    : s.is_vice_captain ? '<span class="pitch-player__vc">V</span>' : '';
  return `
    <div class="pitch-player" onclick="showSquadPlayerModal(${s.id}, '${escapeHtml(s.name).replace(/'/g, "\\'")}', ${s.is_starting ? 'true' : 'false'})">
      ${badge}
      <div class="pitch-player__shirt">${clubLogo(s.team_name || '', '')}</div>
      <div class="pitch-player__name">${escapeHtml(s.name)}</div>
      <div class="pitch-player__pts">${s.gw_points ?? 0} pts</div>
    </div>`;
}

async function showSquadPlayerModal(squadId, name, isStarting) {
  openModal(`
    <h3 style="margin-bottom:1.6rem">${escapeHtml(name)}</h3>
    <div style="display:flex;flex-direction:column;gap:0.8rem">
      <button class="button button--filled" onclick="setCaptain(${squadId})">Make captain</button>
      <button class="button button--outlined" onclick="setViceCaptain(${squadId})">Make vice-captain</button>
      <button class="button button--outlined" onclick="toggleBench(${squadId}, ${isStarting ? 'true' : 'false'})">Bench / Start</button>
    </div>`);
}

async function setCaptain(squadId) {
  try {
    await apiJson(`/users/captain/${squadId}`, { method: 'POST' });
    closeModal(); showToast('Captain updated', 'success'); renderMyTeam();
  } catch (e) { showToast(e.message, 'error'); }
}
async function setViceCaptain(squadId) {
  try {
    await apiJson(`/users/vice-captain/${squadId}`, { method: 'POST' });
    closeModal(); showToast('Vice-captain updated', 'success'); renderMyTeam();
  } catch (e) { showToast(e.message, 'error'); }
}
async function toggleBench(squadId, isStarting) {
  try {
    // isStarting player -> bench (auto-promotes top bench player); bench player -> start
    await apiJson(`/users/squad/${squadId}/${isStarting ? 'bench' : 'start'}`, { method: 'POST' });
    closeModal(); showToast('Squad updated', 'success'); renderMyTeam();
  } catch (e) { showToast(e.message, 'error'); }
}

function renderChips(chips) {
  const row = document.getElementById('chip-row');
  if (!row) return;
  const list = Array.isArray(chips) ? chips : (chips.chips || []);
  if (!list.length) { row.innerHTML = ''; return; }
  const label = (t) => String(t).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  row.innerHTML = list.map((c) => {
    const type = c.type || c.chip_type || c.name;
    const isActive = !!(c.active ?? c.is_active);
    const used = !!c.used;
    return `
    <button class="chip-button ${isActive ? 'is-active' : ''}" ${used && !isActive ? 'disabled' : ''}
      onclick="toggleChip('${type}', ${isActive})">
      ${escapeHtml(label(type))}${used ? ' (used)' : ''}
    </button>`;
  }).join('');
}

async function toggleChip(chipType, isActive) {
  try {
    const action = isActive ? 'cancel' : 'activate';
    await apiJson(`/users/chips/${action}/${chipType}`, { method: 'POST' });
    showToast(`Chip ${isActive ? 'cancelled' : 'activated'}`, 'success');
    renderMyTeam();
  } catch (e) { showToast(e.message, 'error'); }
}

/* ---------- TRANSFERS ---------- */
/*
 * Transfers page: 13-player pitch in a 5-5-3 formation.
 * Clicking a player (or an empty slot) opens a small player modal with
 * Replace / Remove player (or Add player for empty slots). Replace and Add
 * open a larger market modal with club / max-price / budget filters and
 * price / points / club / name sorting. A pick must be confirmed in the
 * market modal before returning to the page. Nothing is final until
 * "Confirm all transfers" is pressed on the main page.
 */
const T = {
  players: [],   // full market from /players/
  layout: [],    // 13 slots, each a squad entry or null
  pending: [],   // {slot, out: entry|null, in: {player_id,name,team_name,price,total_points}|null}
  market: null,  // {slot, out: entry|null, selectedId}
};
const TF_ROWS = [5, 5, 3];

async function renderTransfers() {
  const root = document.getElementById('transfers-root');
  if (!requireAuth('Transfers')) return;
  root.innerHTML = '<div class="loading">Loading transfer market&hellip;</div>';
  const [players, squad] = await Promise.all([
    apiJson('/players/?order_by=points'),
    apiJson('/users/squad').catch(() => []),
  ]);
  T.players = players;
  T.layout = buildTransferLayout(squad);
  renderTransfersPage();
}

function squadEntry(s) {
  return {
    id: s.id,
    player_id: s.player_id,
    name: (s.player && s.player.name) || s.name || 'Unknown',
    team_name: (s.player && s.player.team && s.player.team.name) || '',
    team_id: s.player ? s.player.team_id : null,
    price: (s.player && s.player.price) ?? 0,
    sell: s.selling_price ?? s.purchase_price ?? (s.player && s.player.price) ?? 0,
    gw_points: s.gw_points ?? 0,
    total_points: s.total_points ?? 0,
    is_captain: !!s.is_captain,
    is_vice_captain: !!s.is_vice_captain,
    is_starting: s.is_starting !== false,
    position_slot: s.position_slot ?? 99,
  };
}

function buildTransferLayout(squad) {
  const entries = squad.map(squadEntry).sort((a, b) => a.position_slot - b.position_slot);
  const layout = new Array(13).fill(null);
  entries.slice(0, 13).forEach((e, i) => { layout[i] = e; });
  return layout;
}

function pendingForSlot(slot) { return T.pending.find((p) => p.slot === slot); }
function pendingInIds() { return new Set(T.pending.filter((p) => p.in).map((p) => p.in.player_id)); }
function pendingNet() {
  let n = 0;
  for (const p of T.pending) { if (p.out) n += p.out.sell; if (p.in) n -= p.in.price; }
  return Math.round(n * 10) / 10;
}
function bankAfterPending() {
  if (!currentTeam) return 0;
  return Math.round(((currentTeam.budget_remaining ?? currentTeam.bank ?? 0) + pendingNet()) * 10) / 10;
}
/* Budget available for a new pick at a slot: bank + pending sells - pending buys
   (bankAfterPending), plus what the pick itself frees up.
   - pending op with a replacement: the new pick supersedes that buy -> add its price back
   - pending op without a replacement: the sell is already in bankAfterPending -> add nothing
   - no pending op, player on the pitch: the sell is not in bankAfterPending yet -> add it
   - empty slot: nothing freed */
function budgetForPick(slot) {
  const p = pendingForSlot(slot);
  let freed = 0;
  if (p) {
    if (p.in) freed = p.in.price;
  } else if (T.layout[slot]) {
    freed = T.layout[slot].sell;
  }
  return Math.round((bankAfterPending() + freed) * 10) / 10;
}

function renderTransfersPage() {
  const root = document.getElementById('transfers-root');
  const bank = bankAfterPending();
  const squadCount = T.layout.filter(Boolean).length;
  const netGain = pendingNet();

  let html = `
    <div class="gw-banner">
      <div><strong>${escapeHtml(currentTeam ? currentTeam.name : 'No team')}</strong>
        <div style="font-size:1.4rem;color:var(--theme-on-surface-variant)">
          Bank: &pound;${(currentTeam ? (currentTeam.budget_remaining ?? currentTeam.bank ?? 0) : 0).toFixed(1)}m
          ${T.pending.length ? ` &rarr; &pound;${bank.toFixed(1)}m with transfers` : ''}
          &middot; Squad: ${squadCount}/13
        </div>
      </div>
      ${T.pending.length ? `<div style="font-size:1.4rem;color:var(--theme-on-surface-variant)">${T.pending.length} pending &middot; net ${netGain <= 0 ? '+' : '-'}&pound;${Math.abs(netGain).toFixed(1)}m</div>` : ''}
    </div>`;

  if (T.pending.length) {
    html += `
    <div class="card tf-pending" style="margin-top:2.4rem">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;margin-bottom:1.2rem">
        <h3 class="card__title" style="margin-bottom:0">Pending transfers</h3>
        <div style="display:flex;gap:0.8rem;flex-wrap:wrap">
          <button class="button button--text button--small" onclick="tfClearAll()">Clear all</button>
          <button class="button button--accent button--small" onclick="tfConfirmAll()">Confirm all transfers</button>
        </div>
      </div>
      ${T.pending.map((p) => tfPendingRowHtml(p)).join('')}
    </div>`;
  }

  html += `
    <h2 style="margin:2.4rem 0 1.6rem">Your squad</h2>
    <div class="pitch pitch--13">
      ${TF_ROWS.map((n, r) => `<div class="pitch__row">${Array.from({ length: n }, (_, i) => tfSlotHtml(r * 5 + i)).join('')}</div>`).join('')}
    </div>
    <p style="margin-top:1.6rem;font-size:1.4rem;color:var(--theme-on-surface-variant)">
      Tap a player to replace or remove them, or tap an empty slot to add a player.
      Transfers are only final once you press <strong>Confirm all transfers</strong>.
    </p>`;

  root.innerHTML = html;
}

function tfPendingRowHtml(p) {
  const out = p.out
    ? `<span class="team-cell">${clubLogo(p.out.team_name, 'club-badge club-badge--small')}<span>${escapeHtml(p.out.name)} &mdash; out for &pound;${p.out.sell.toFixed(1)}m</span></span>`
    : '<span style="color:var(--theme-on-surface-variant)">Empty slot</span>';
  const inn = p.in
    ? `<span class="team-cell">${clubLogo(p.in.team_name, 'club-badge club-badge--small')}<span>${escapeHtml(p.in.name)} &mdash; in for &pound;${p.in.price.toFixed(1)}m</span></span>`
    : '<span style="color:var(--theme-on-surface-variant)">No replacement yet</span>';
  const net = (p.in ? p.in.price : 0) - (p.out ? p.out.sell : 0);
  return `
    <div class="tf-pending__row">
      <div style="display:flex;align-items:center;gap:1.2rem;flex-wrap:wrap">
        ${out} <span aria-hidden="true">&rarr;</span> ${inn}
        <strong class="tf-pending__net" style="color:${net > 0 ? 'var(--c-system-error)' : 'var(--c-system-success)'}">${net > 0 ? '+' : net < 0 ? '-' : ''}&pound;${Math.abs(net).toFixed(1)}m</strong>
      </div>
      <button class="button button--text button--small" onclick="tfRemovePending(${p.slot})">&times; Remove from list</button>
    </div>`;
}

function tfSlotHtml(i) {
  const e = T.layout[i];
  const p = pendingForSlot(i);
  if (p) {
    const outHtml = p.out
      ? `<div class="pitch-player is-pending-out">
          <div class="pitch-player__shirt">${clubLogo(p.out.team_name, '')}</div>
          <div class="pitch-player__name">${escapeHtml(p.out.name)}</div>
          <div class="pitch-player__pts">out</div>
        </div>`
      : `<div class="pitch-player is-pending-out"><div class="pitch-player__shirt pitch-player__shirt--empty">&mdash;</div><div class="pitch-player__name pitch-player__name--empty">empty</div></div>`;
    const inHtml = p.in
      ? `<div class="pitch-player is-pending-in">
          <div class="pitch-player__shirt">${clubLogo(p.in.team_name, '')}</div>
          <div class="pitch-player__name">${escapeHtml(p.in.name)}</div>
          <div class="pitch-player__pts">&pound;${p.in.price.toFixed(1)}m</div>
        </div>`
      : '';
    return `<div class="pitch-slot" onclick="tfOpenSlot(${i})">${outHtml}<div class="pitch-slot__arrow" aria-hidden="true">&rarr;</div>${inHtml}</div>`;
  }
  if (e) {
    const badge = e.is_captain ? '<span class="pitch-player__c">C</span>'
      : e.is_vice_captain ? '<span class="pitch-player__vc">V</span>' : '';
    return `
    <div class="pitch-player" onclick="tfOpenSlot(${i})">
      ${badge}
      <div class="pitch-player__shirt">${clubLogo(e.team_name, '')}</div>
      <div class="pitch-player__name">${escapeHtml(e.name)}</div>
      <div class="pitch-player__pts">${e.gw_points} pts</div>
    </div>`;
  }
  return `
  <div class="pitch-player" onclick="tfOpenSlot(${i})">
    <div class="pitch-player__shirt pitch-player__shirt--empty">+</div>
    <div class="pitch-player__name pitch-player__name--empty">Add player</div>
  </div>`;
}

/* --- Small player modal --- */
function tfOpenSlot(i) {
  const e = T.layout[i];
  const p = pendingForSlot(i);
  if (p) {
    const inn = p.in ? `${escapeHtml(p.in.name)} (&pound;${p.in.price.toFixed(1)}m)` : 'no replacement yet';
    const outt = p.out ? `${escapeHtml(p.out.name)} out for &pound;${p.out.sell.toFixed(1)}m` : 'empty slot';
    openModal(`
      <h3 style="margin-bottom:0.8rem">Pending transfer</h3>
      <p style="margin-bottom:1.6rem">${outt} &rarr; ${inn}</p>
      <div style="display:flex;flex-direction:column;gap:0.8rem">
        <button class="button button--filled" onclick="tfOpenMarket(${i})">Change replacement</button>
        <button class="button button--outlined" onclick="tfRemovePending(${i})">Remove from list</button>
      </div>`);
    return;
  }
  if (!e) {
    openModal(`
      <h3 style="margin-bottom:0.8rem">Empty slot</h3>
      <p style="margin-bottom:1.6rem;color:var(--theme-on-surface-variant)">Pick a player to fill this slot.</p>
      <div style="display:flex;flex-direction:column;gap:0.8rem">
        <button class="button button--filled" onclick="tfOpenMarket(${i})">Add player</button>
      </div>`);
    return;
  }
  const badge = e.is_captain ? ' &middot; Captain' : e.is_vice_captain ? ' &middot; Vice-captain' : '';
  openModal(`
    <h3 style="margin-bottom:0.4rem">${escapeHtml(e.name)}${badge}</h3>
    <p style="color:var(--theme-on-surface-variant);margin-bottom:1.6rem">
      <span class="team-cell">${clubLogo(e.team_name, 'club-badge club-badge--small')}${escapeHtml(e.team_name)}</span>
      &nbsp; &pound;${e.price.toFixed(1)}m &middot; ${e.total_points} pts this season &middot; sells for &pound;${e.sell.toFixed(1)}m
    </p>
    <div style="display:flex;flex-direction:column;gap:0.8rem">
      <button class="button button--filled" onclick="tfOpenMarket(${i})">Replace</button>
      <button class="button button--outlined" onclick="tfRemoveSlot(${i})">Remove player</button>
    </div>`);
}

function tfRemoveSlot(i) {
  const e = T.layout[i];
  if (!e) return;
  T.pending.push({ slot: i, out: e, in: null });
  closeModal();
  renderTransfersPage();
  showToast(`${e.name} removed — pick a replacement or confirm all transfers`, 'info');
}

function tfRemovePending(slot) {
  T.pending = T.pending.filter((p) => p.slot !== slot);
  closeModal();
  renderTransfersPage();
}

function tfClearAll() {
  T.pending = [];
  renderTransfersPage();
  showToast('Transfer list cleared', 'info');
}

async function tfConfirmAll() {
  if (!T.pending.length) return;
  const ops = T.pending.map((p) => ({
    player_out_id: p.out ? p.out.player_id : null,
    player_in_id: p.in ? p.in.player_id : null,
  }));
  try {
    const res = await apiJson('/transfers/confirm', {
      method: 'POST',
      body: JSON.stringify({ pending_transfers: ops }),
    });
    showToast(`Transfers confirmed (${res.transfers_applied})${res.points_hit ? ' — -' + res.points_hit + ' pts hit' : ''}`, 'success');
    T.pending = [];
    await loadMe();
    await renderTransfers();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

/* --- Large market modal --- */
function tfOpenMarket(i) {
  T.market = { slot: i, out: T.layout[i] || null, selectedId: null, club: '', maxPrice: '', onlyAffordable: false, sort: 'points' };
  renderMarketModal();
}

function tfMarketFiltered() {
  const m = T.market;
  const squadIds = new Set(T.layout.filter(Boolean).map((e) => e.player_id));
  const outIds = pendingInIds();
  const budget = budgetForPick(m.slot);
  let rows = T.players.filter((p) => {
    if (m.club && !(p.team && p.team.name === m.club)) return false;
    if (m.maxPrice && p.price > parseFloat(m.maxPrice)) return false;
    if (m.onlyAffordable && p.price > budget) return false;
    return true;
  });
  const cmp = {
    price_desc: (a, b) => b.price - a.price,
    price_asc: (a, b) => a.price - b.price,
    points: (a, b) => (b.total_points || 0) - (a.total_points || 0),
    club: (a, b) => ((a.team && a.team.name) || '').localeCompare((b.team && b.team.name) || ''),
    name: (a, b) => a.name.localeCompare(b.name),
  }[m.sort] || ((a, b) => 0);
  rows = rows.slice().sort(cmp);
  return rows.map((p) => {
    const inSquad = squadIds.has(p.id) && !(m.out && m.out.player_id === p.id);
    const isSelf = !!(m.out && m.out.player_id === p.id);
    const isPending = outIds.has(p.id);
    return { p, inSquad, isSelf, isPending, disabled: inSquad || isSelf || isPending };
  });
}

function renderMarketModal() {
  const m = T.market;
  const rows = tfMarketFiltered();
  const budget = budgetForPick(m.slot);
  const clubs = [...new Set(T.players.map((p) => p.team && p.team.name).filter(Boolean))].sort();
  const prices = [];
  for (let v = 5.0; v <= 15.5; v += 0.5) prices.push(Math.round(v * 10) / 10);
  const sel = T.players.find((p) => p.id === m.selectedId);

  const title = m.out ? `Replace ${escapeHtml(m.out.name)}` : 'Add player';
  const sub = m.out
    ? `Selling ${escapeHtml(m.out.name)} for &pound;${m.out.sell.toFixed(1)}m`
    : 'Filling an empty slot';

  openModal(`
    <h3 style="margin-bottom:0.4rem">${title}</h3>
    <p style="color:var(--theme-on-surface-variant);margin-bottom:1.6rem">
      ${sub} &middot; Budget available: <strong style="color:var(--theme-on-surface)">&pound;${budget.toFixed(1)}m</strong>
    </p>
    <div class="filters">
      <select id="tfm-club" onchange="tfMarketSet('club', this.value)">
        <option value="">All clubs</option>
        ${clubs.map((c) => `<option value="${escapeHtml(c)}" ${m.club === c ? 'selected' : ''}>${escapeHtml(c)}</option>`).join('')}
      </select>
      <select id="tfm-maxprice" onchange="tfMarketSet('maxPrice', this.value)">
        <option value="">Any price</option>
        ${prices.map((v) => `<option value="${v}" ${m.maxPrice === String(v) ? 'selected' : ''}>&le; &pound;${v.toFixed(1)}m</option>`).join('')}
      </select>
      <label style="display:flex;align-items:center;gap:0.6rem;font-size:1.4rem;cursor:pointer">
        <input type="checkbox" ${m.onlyAffordable ? 'checked' : ''} onchange="tfMarketSet('onlyAffordable', this.checked)">
        Only players I can afford
      </label>
      <select id="tfm-sort" onchange="tfMarketSet('sort', this.value)">
        <option value="points" ${m.sort === 'points' ? 'selected' : ''}>Sort: Points</option>
        <option value="price_desc" ${m.sort === 'price_desc' ? 'selected' : ''}>Sort: Price (high to low)</option>
        <option value="price_asc" ${m.sort === 'price_asc' ? 'selected' : ''}>Sort: Price (low to high)</option>
        <option value="club" ${m.sort === 'club' ? 'selected' : ''}>Sort: Club (A&ndash;Z)</option>
        <option value="name" ${m.sort === 'name' ? 'selected' : ''}>Sort: Name (A&ndash;Z)</option>
      </select>
    </div>
    <div class="table-wrap" style="max-height:48rem;overflow-y:auto">
      <table class="data-table">
        <thead><tr><th>Player</th><th>Club</th><th class="num">Pts</th><th class="num">Price</th><th class="num"></th></tr></thead>
        <tbody>
          ${rows.map(({ p, inSquad, isSelf, isPending, disabled }) => `
            <tr class="tf-market__row ${disabled ? 'is-disabled' : ''} ${m.selectedId === p.id ? 'is-selected' : ''}"
                ${disabled ? '' : `onclick="tfMarketPick(${p.id})"`}>
              <td><span class="team-cell">${clubLogo(p.team && p.team.name, 'club-badge club-badge--small')}${escapeHtml(p.name)}</span></td>
              <td>${escapeHtml(p.team ? p.team.name : '')}</td>
              <td class="num">${p.total_points}</td>
              <td class="num">&pound;${p.price.toFixed(1)}m</td>
              <td class="num">
                ${m.selectedId === p.id ? '<span class="badge badge--live">Selected</span>'
                  : disabled ? (isSelf ? '<span style="font-size:1.2rem;color:var(--theme-on-surface-variant)">Being replaced</span>'
                    : inSquad ? '<span style="font-size:1.2rem;color:var(--theme-on-surface-variant)">In your squad</span>'
                    : '<span style="font-size:1.2rem;color:var(--theme-on-surface-variant)">Pending</span>')
                  : '<span style="font-size:1.2rem;color:var(--theme-on-surface-variant)">&rarr;</span>'}
              </td>
            </tr>`).join('') || '<tr><td colspan="5">No players match these filters.</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="tf-market__footer">
      ${sel
        ? `<div style="font-size:1.4rem">Selected: <strong>${escapeHtml(sel.name)}</strong> &mdash; &pound;${sel.price.toFixed(1)}m
             ${m.out ? `&middot; net ${sel.price - m.out.sell >= 0 ? '+' : '-'}&pound;${Math.abs(sel.price - m.out.sell).toFixed(1)}m` : ''}</div>
           <div style="display:flex;gap:0.8rem">
             <button class="button button--outlined button--small" onclick="tfMarketSet('selectedId', null)">Back</button>
             <button class="button button--accent button--small" onclick="tfMarketConfirm()">Confirm ${escapeHtml(sel.name)}</button>
           </div>`
        : '<div style="font-size:1.4rem;color:var(--theme-on-surface-variant)">Select a player, then confirm your choice.</div>'}
    </div>`);
  const sheet = document.getElementById('modal-sheet');
  if (sheet) sheet.classList.add('modal--market');
}

function tfMarketSet(key, value) {
  if (!T.market) return;
  T.market[key] = value;
  if (key === 'selectedId') T.market.selectedId = value;
  renderMarketModal();
}

function tfMarketPick(playerId) {
  if (!T.market) return;
  T.market.selectedId = playerId;
  renderMarketModal();
}

function tfMarketConfirm() {
  const m = T.market;
  const p = T.players.find((x) => x.id === m.selectedId);
  if (!p) return;
  const entry = {
    player_id: p.id,
    name: p.name,
    team_name: p.team ? p.team.name : '',
    price: p.price,
    total_points: p.total_points,
  };
  const existing = pendingForSlot(m.slot);
  if (existing) {
    existing.in = entry;
  } else {
    T.pending.push({ slot: m.slot, out: m.out, in: entry });
  }
  T.market = null;
  closeModal();
  renderTransfersPage();
  showToast(`${entry.name} added to your transfer list — press "Confirm all transfers" to finalise`, 'success');
}

/* ---------- PLAYERS ---------- */
let allPlayers = [];

async function renderPlayers() {
  const root = document.getElementById('players-root');
  root.innerHTML = `
    <div class="filters">
      <input id="pl-search" type="search" placeholder="Search players&hellip;" oninput="filterPlayers()">
      <select id="pl-team" onchange="filterPlayers()"><option value="">All clubs</option></select>
      <select id="pl-sort" onchange="filterPlayers()">
        <option value="points">Sort: Points</option><option value="goals">Goals</option>
        <option value="assists">Assists</option><option value="price">Price</option><option value="form">Form</option>
      </select>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>Player</th><th>Club</th><th class="num">Price</th><th class="num">Pts</th><th class="num">G</th><th class="num">A</th><th class="num">CS</th><th class="num">Form</th><th class="num">Sel%</th></tr></thead>
      <tbody id="pl-tbody"><tr><td colspan="9" class="loading">Loading players&hellip;</td></tr></tbody>
    </table></div>`;

  allPlayers = await apiJson('/players/?order_by=points');
  const teams = [...new Set(allPlayers.map((p) => p.team && p.team.name).filter(Boolean))].sort();
  document.getElementById('pl-team').innerHTML = '<option value="">All clubs</option>' +
    teams.map((t) => `<option>${escapeHtml(t)}</option>`).join('');
  filterPlayers();
}

function filterPlayers() {
  const q = (document.getElementById('pl-search').value || '').toLowerCase();
  const team = document.getElementById('pl-team').value;
  const sort = document.getElementById('pl-sort').value;
  const key = { points: 'total_points', goals: 'goals', assists: 'assists', price: 'price', form: 'form' }[sort] || 'total_points';
  const rows = allPlayers
    .filter((p) =>
      (!team || (p.team && p.team.name === team)) &&
      (!q || p.name.toLowerCase().includes(q)))
    .sort((a, b) => (b[key] || 0) - (a[key] || 0))
    .slice(0, 150);
  document.getElementById('pl-tbody').innerHTML = rows.map((p) => `
    <tr style="cursor:pointer" onclick="showPlayerDetail(${p.id})">
      <td>${escapeHtml(p.name)}</td>
      <td><span class="team-cell">${clubLogo(p.team && p.team.name, 'club-badge club-badge--small')}${escapeHtml(p.team ? p.team.name : '')}</span></td>
      <td class="num">&pound;${p.price.toFixed(1)}m</td>
      <td class="num"><strong>${p.total_points}</strong></td>
      <td class="num">${p.goals}</td>
      <td class="num">${p.assists}</td>
      <td class="num">${p.clean_sheets}</td>
      <td class="num">${(p.form || 0).toFixed(1)}</td>
      <td class="num">${(p.selected_by_percent || 0).toFixed(1)}</td>
    </tr>`).join('') || '<tr><td colspan="9">No players match.</td></tr>';
}

async function showPlayerDetail(id) {
  try {
    const data = await apiJson(`/players/${id}/detail`);
    const p = data.player || data;
    openModal(`
      <h3 style="margin-bottom:0.4rem">${escapeHtml(p.name)}</h3>
      <p style="color:var(--theme-on-surface-variant);margin-bottom:1.6rem">
        <span class="team-cell">${clubLogo(p.team_name || (p.team && p.team.name), 'club-badge club-badge--small')}${escapeHtml(p.team_name || (p.team && p.team.name) || '')}</span>
        &nbsp; &pound;${(p.price || 0).toFixed(1)}m
      </p>
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-card__label">Total points</div><div class="stat-card__value">${p.total_points ?? p.total_points_season ?? 0}</div></div>
        <div class="stat-card"><div class="stat-card__label">Goals</div><div class="stat-card__value">${p.goals ?? 0}</div></div>
        <div class="stat-card"><div class="stat-card__label">Assists</div><div class="stat-card__value">${p.assists ?? 0}</div></div>
        <div class="stat-card"><div class="stat-card__label">Clean sheets</div><div class="stat-card__value">${p.clean_sheets ?? 0}</div></div>
        <div class="stat-card"><div class="stat-card__label">Appearances</div><div class="stat-card__value">${p.apps ?? 0}</div></div>
        <div class="stat-card"><div class="stat-card__label">Form</div><div class="stat-card__value">${(p.form || 0).toFixed(1)}</div></div>
      </div>`);
  } catch (e) { showToast(e.message, 'error'); }
}

/* ---------- FIXTURES ---------- */
async function renderFixtures() {
  const root = document.getElementById('fixtures-root');
  const gws = await apiJson('/gameweeks/');
  const currentId = gws.current_gw ? gws.current_gw.id : (gws.gameweeks[0] && gws.gameweeks[0].id);
  root.innerHTML = `
    <div class="filters"><select id="fx-gw" onchange="loadFixtures()">
      ${gws.gameweeks.map((g) => `<option value="${g.id}" ${g.id === currentId ? 'selected' : ''}>Gameweek ${g.number}</option>`).join('')}
    </select></div>
    <div id="fx-list"><div class="loading">Loading fixtures&hellip;</div></div>`;
  await loadFixtures();
}

async function loadFixtures() {
  const gwId = document.getElementById('fx-gw').value;
  const data = await apiJson(`/fixtures/?gameweek_id=${gwId}`);
  const list = document.getElementById('fx-list');
  if (!data.fixtures.length) {
    list.innerHTML = '<div class="empty-state">No fixtures for this gameweek yet.</div>';
    return;
  }
  list.innerHTML = `<div class="card-grid card-grid--2">${data.fixtures.map((f) => `
    <div class="fixture-card">
      <div class="fixture-card__meta">${fmtDate(f.date)}</div>
      <div class="fixture-card__row">
        <div class="fixture-card__home">
          <strong>${escapeHtml(f.home_team)}</strong>${clubLogo(f.home_team, 'club-badge')}
          ${f.home_difficulty ? `<span class="fdr fpl-fdr-${f.home_difficulty}">${f.home_difficulty}</span>` : ''}
        </div>
        ${f.played
          ? `<div class="fixture-card__score">${f.home_score} &ndash; ${f.away_score}</div>`
          : '<div class="fixture-card__vs">vs</div>'}
        <div class="fixture-card__away">
          ${f.away_difficulty ? `<span class="fdr fpl-fdr-${f.away_difficulty}">${f.away_difficulty}</span>` : ''}
          ${clubLogo(f.away_team, 'club-badge')}<strong>${escapeHtml(f.away_team)}</strong>
        </div>
      </div>
    </div>`).join('')}</div>`;
}

/* ---------- GAMEWEEKS ---------- */
async function renderGameweeks() {
  const root = document.getElementById('gameweeks-root');
  const gws = await apiJson('/gameweeks/');
  root.innerHTML = `<div class="card-grid">${gws.gameweeks.map((g) => {
    const badge = g.is_current
      ? (g.closed ? '<span class="badge badge--closed">Closed</span>' : '<span class="badge badge--live">Current</span>')
      : g.scored ? '<span class="badge badge--closed">Scored</span>'
      : (g.deadline && new Date(g.deadline) > Date.now()) ? '<span class="badge badge--upcoming">Upcoming</span>'
      : '<span class="badge badge--open">Open</span>';
    return `
      <div class="card gw-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <div class="gw-card__number">GW ${g.number}</div>${badge}
        </div>
        <div class="gw-card__deadline">Deadline: ${fmtDate(g.deadline)}</div>
        <div class="gw-card__deadline">${g.fixture_count} fixtures</div>
      </div>`;
  }).join('')}</div>`;
}

/* ---------- HISTORY ---------- */
async function renderHistory() {
  const root = document.getElementById('history-root');
  if (!requireAuth('History')) return;
  if (!currentTeam) {
    root.innerHTML = '<div class="empty-state"><h2>No team yet</h2><p>Create a team to build history.</p></div>';
    return;
  }
  let hist = [];
  try {
    const data = await apiJson(`/leaderboard/${currentUser.id}/history`);
    hist = data.history || data.gameweeks || data || [];
  } catch (_) {}
  if (!Array.isArray(hist) || !hist.length) {
    root.innerHTML = '<div class="empty-state"><h2>No history yet</h2><p>Your gameweek results will appear here once gameweeks are scored.</p></div>';
    return;
  }
  // Drop malformed rows with no real gameweek number
  hist = hist.filter((h) => (h.gameweek ?? h.gameweek_number ?? h.number ?? 0) > 0);
  if (!hist.length) {
    root.innerHTML = '<div class="empty-state"><h2>No history yet</h2><p>Your gameweek results will appear here once gameweeks are scored.</p></div>';
    return;
  }
  root.innerHTML = `
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>GW</th><th class="num">Points</th><th class="num">Bench</th><th class="num">Transfers</th><th class="num">Hit</th><th class="num">Total</th><th class="num">Rank</th></tr></thead>
      <tbody>${hist.map((h) => `
        <tr>
          <td>GW ${h.gameweek ?? h.gameweek_number ?? h.number ?? '—'}</td>
          <td class="num"><strong>${h.points ?? '—'}</strong></td>
          <td class="num">${h.bench_points ?? '—'}</td>
          <td class="num">${h.transfers ?? h.transfers_made ?? '—'}</td>
          <td class="num">${h.transfer_cost ? '-' + h.transfer_cost : '—'}</td>
          <td class="num">${h.total_points ?? '—'}</td>
          <td class="num">${h.overall_rank ?? h.rank ?? '—'}</td>
        </tr>`).join('')}
      </tbody>
    </table></div>`;
}

/* ---------- LEADERBOARD ---------- */
async function renderLeaderboard() {
  const root = document.getElementById('leaderboard-root');
  const data = await apiJson('/leaderboard/?limit=100');
  root.innerHTML = `
    <p style="margin-bottom:1.6rem;color:var(--theme-on-surface-variant)">${data.total_teams} managers this season</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th class="num">Rank</th><th>Manager</th><th>Team</th><th class="num">GW pts</th><th class="num">Total</th></tr></thead>
      <tbody>${data.entries.map((e) => `
        <tr ${currentUser && e.user_id === currentUser.id ? 'style="background:var(--theme-primary-container)"' : ''}>
          <td class="num"><strong>${e.rank}</strong></td>
          <td>${escapeHtml(e.username)}</td>
          <td>${escapeHtml(e.team_name)}</td>
          <td class="num">${e.gameweek_points ?? '—'}</td>
          <td class="num"><strong>${e.total_points}</strong></td>
        </tr>`).join('')}
      </tbody>
    </table></div>`;
}

/* ---------- LEAGUES ---------- */
async function renderLeagues() {
  const root = document.getElementById('leagues-root');
  if (!requireAuth('Leagues')) return;
  root.innerHTML = `
    <div class="card-grid card-grid--2">
      <div class="card">
        <h3 class="card__title">Create a league</h3>
        <form onsubmit="createLeague(event)">
          <div class="form-field"><label for="lg-name">League name</label><input id="lg-name" required maxlength="60"></div>
          <button class="button button--filled" type="submit">Create</button>
        </form>
      </div>
      <div class="card">
        <h3 class="card__title">Join a league</h3>
        <form onsubmit="joinLeague(event)">
          <div class="form-field"><label for="lg-code">League code</label><input id="lg-code" required maxlength="12" style="text-transform:uppercase"></div>
          <button class="button button--filled" type="submit">Join</button>
        </form>
      </div>
    </div>
    <div id="my-leagues" style="margin-top:2.4rem"><div class="loading">Loading your leagues&hellip;</div></div>`;
  loadMyLeagues();
}

async function loadMyLeagues() {
  const el = document.getElementById('my-leagues');
  if (!currentUser) { el.innerHTML = ''; return; }
  let leagues = [];
  try {
    const data = await apiJson('/leagues/my-leagues');
    leagues = data.leagues || data || [];
  } catch (_) {}
  if (!Array.isArray(leagues) || !leagues.length) {
    el.innerHTML = '<div class="empty-state">You are not in any leagues yet.</div>';
    return;
  }
  el.innerHTML = `
    <h2 style="margin-bottom:1.6rem">Your leagues</h2>
    <div class="card-grid">${leagues.map((l) => `
      <div class="card">
        <h3 class="card__title">${escapeHtml(l.name)}</h3>
        <p style="color:var(--theme-on-surface-variant);font-size:1.4rem">Code: <strong style="letter-spacing:0.1em">${escapeHtml(l.code)}</strong> &middot; ${l.member_count ?? (l.members ? l.members.length : '—')} members</p>
        ${Array.isArray(l.standings) && l.standings.length ? `
          <div class="table-wrap" style="margin-top:1.2rem"><table class="data-table">
            <thead><tr><th class="num">#</th><th>Team</th><th class="num">Pts</th></tr></thead>
            <tbody>${l.standings.slice(0, 10).map((s, i) => `
              <tr><td class="num">${i + 1}</td><td>${escapeHtml(s.team_name || s.name || '')}</td><td class="num">${s.total_points ?? s.points ?? 0}</td></tr>`).join('')}
            </tbody></table></div>` : ''}
      </div>`).join('')}</div>`;
}

async function createLeague(e) {
  e.preventDefault();
  if (!currentUser) { showToast('Sign in first', 'error'); return; }
  const name = document.getElementById('lg-name').value.trim();
  try {
    const ml = await apiJson('/leagues/', {
      method: 'POST',
      body: JSON.stringify({ name, is_h2h: false }),
    });
    showToast(`League created — code ${ml.code}`, 'success');
    loadMyLeagues();
  } catch (err) { showToast(err.message, 'error'); }
}

async function joinLeague(e) {
  e.preventDefault();
  if (!currentUser) { showToast('Sign in first', 'error'); return; }
  const code = document.getElementById('lg-code').value.trim().toUpperCase();
  try {
    await apiJson(`/leagues/join?code=${encodeURIComponent(code)}`, { method: 'POST' });
    showToast('Joined league', 'success');
    loadMyLeagues();
  } catch (err) { showToast(err.message, 'error'); }
}

/* ---------- DREAM TEAM ---------- */
async function renderDreamTeam() {
  const root = document.getElementById('dream-team-root');
  const gws = await apiJson('/gameweeks/');
  const scored = gws.gameweeks.filter((g) => g.scored);
  const def = scored.length ? scored[scored.length - 1].id : (gws.current_gw ? gws.current_gw.id : null);
  root.innerHTML = `
    <div class="filters"><select id="dt-gw" onchange="loadDreamTeam()">
      ${gws.gameweeks.map((g) => `<option value="${g.id}" ${g.id === def ? 'selected' : ''}>Gameweek ${g.number}</option>`).join('')}
    </select></div>
    <div id="dt-root"><div class="loading">Loading dream team&hellip;</div></div>`;
  await loadDreamTeam();
}

async function loadDreamTeam() {
  const gwId = document.getElementById('dt-gw').value;
  const root = document.getElementById('dt-root');
  let data;
  try {
    data = await apiJson(`/gameweeks/${gwId}/dream-team`);
  } catch (_) {
    root.innerHTML = `<div class="empty-state"><h2>No dream team yet</h2><p>This gameweek has not been scored yet.</p></div>`;
    return;
  }
  const dt = data.dream_team || data;
  const players = dt.members || dt.players || [];
  if (!players.length) {
    root.innerHTML = `<div class="empty-state"><h2>No dream team yet</h2><p>${escapeHtml(dt.message || 'This gameweek has not been scored.')}</p></div>`;
    return;
  }
  const rows = [];
  for (let i = 0; i < players.length; i += 4) rows.push(players.slice(i, i + 4));
  root.innerHTML = `
    <div class="gw-banner"><div><strong>Gameweek ${dt.gameweek ?? ''} Dream Team</strong></div>
      <div class="gw-banner__countdown">${dt.total_points ?? 0} pts</div></div>
    <div class="pitch" style="margin-top:2.4rem">
      ${rows.map((row) => `<div class="pitch__row">${row.map((p) => `
        <div class="pitch-player">
          ${p.is_captain ? '<span class="pitch-player__c">C</span>' : ''}
          <div class="pitch-player__shirt">${clubLogo(p.team_name, '')}</div>
          <div class="pitch-player__name">${escapeHtml(p.player_name || p.name || '')}</div>
          <div class="pitch-player__pts">${p.points} pts</div>
        </div>`).join('')}</div>`).join('')}
    </div>`;
}

/* ---------- RANKINGS ---------- */
async function renderRankings() {
  const root = document.getElementById('rankings-root');
  root.innerHTML = `
    <div class="filters">
      <select id="rk-sort" onchange="loadRankings()">
        <option value="points">Sort: Points</option><option value="goals">Goals</option>
        <option value="assists">Assists</option><option value="form">Form</option><option value="price">Price</option>
      </select>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th class="num">#</th><th>Player</th><th>Club</th><th class="num">Pts</th><th class="num">G</th><th class="num">A</th><th class="num">Form</th><th class="num">Price</th></tr></thead>
      <tbody id="rk-tbody"><tr><td colspan="8" class="loading">Loading&hellip;</td></tr></tbody>
    </table></div>`;
  await loadRankings();
}

async function loadRankings() {
  const sort = document.getElementById('rk-sort').value;
  const data = await apiJson(`/players/rankings?sort_by=${sort}&limit=100`);
  document.getElementById('rk-tbody').innerHTML = data.rankings.map((r) => `
    <tr>
      <td class="num">${r.rank}</td>
      <td>${escapeHtml(r.name)}</td>
      <td><span class="team-cell">${clubLogo(r.team, 'club-badge club-badge--small')}${escapeHtml(r.team)}</span></td>
      <td class="num"><strong>${r.points ?? 0}</strong></td>
      <td class="num">${r.goals ?? 0}</td>
      <td class="num">${r.assists ?? 0}</td>
      <td class="num">${(r.form || 0).toFixed(1)}</td>
      <td class="num">&pound;${(r.price || 0).toFixed(1)}m</td>
    </tr>`).join('') || '<tr><td colspan="8">No players found.</td></tr>';
}
