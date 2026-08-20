#!/usr/bin/env python3
"""FullTime sync: update the FFIOM reference DB from FA FullTime.

Phases
------
results  Write scores, half-time scores, kickoff times, walkovers and played
         flags onto MATCHING fixtures already in the DB, from the FullTime
         API results feed. Fixtures not in the DB are reported, never
         inserted (gameweek mapping stays manual).
teams    Identify each player's CURRENT first team. The authoritative signal
         is the most recent first-team league fixture a player appeared in
         (lineups are scraped from FullTime fixture detail pages).
         players.team_id is updated on a move, and is_active/now_playing
         follow the division of the new team (Premier League -> in the
         fantasy pool; anything else -> out).
stats    Scrape the divisional statLeaders tables (all pages) and update
         season stats (apps, goals, assists, cards, minutes) on matching
         players. Rows carry a stable FullTime personID which is stored in
         players.ft_person_id (created lazily) so identity survives moves.

There is NO transfer window in this league and moves are not reported
anywhere, so the lineup signal is the only reliable source of truth for
"who does this player currently play for".

Data sources (verified 2026-08-20)
----------------------------------
- Results: FullTime API JSON (public instance by default — set
  FULLTIME_API_BASE_URL to use a local one). No lineup/stat-leaderboard
  endpoint exists, so those two stay on HTML scraping.
- HTML scraping uses curl_cffi with Chrome TLS impersonation (Cloudflare
  blocks plain clients). Fixture detail pages (lineups) and statLeaders
  tables are fully server-rendered.
- The HTML results listing needs the season's fixture-group key (changes
  every season); the script discovers it via a session season-switch.

Usage
-----
    python scripts/fulltime_sync.py --all                 # live season, everything
    python scripts/fulltime_sync.py --results --stats     # individual phases
    python scripts/fulltime_sync.py --teams --last 8      # lineups of last 8 results
    python scripts/fulltime_sync.py --season 2025-26 --all --dry-run
    python scripts/fulltime_sync.py --db /tmp/copy.db --all

The DB is backed up to <db>.pre_fulltime_sync_<ts> before any write
(skipped with --dry-run).
"""
import argparse
import html as html_mod
import os
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from curl_cffi import requests as cr

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

FULLTIME_BASE = "https://fulltime.thefa.com"
# FullTime API (public instance by default; point at a local deployment later)
FULLTIME_API_BASE_URL = os.getenv("FULLTIME_API_BASE_URL", "https://faapi.jwhsolutions.co.uk/api")
IOM_LEAGUE_ID = os.getenv("IOM_LEAGUE_ID", "9057188")
DIVISIONS = {
    "all": "0",  # aggregated across all divisions — one row per player
    "premier": os.getenv("DIV_PREMIER", "175685803"),
    "d2": os.getenv("DIV_2", "715559946"),
}
PREMIER_LEAGUE_NAME = "Canada Life Premier League"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}
IMPERSONATE = "chrome131"
FETCH_DELAY = float(os.getenv("FT_FETCH_DELAY", "1.2"))  # seconds between requests
API_TIMEOUT = 60
MAX_PAGES = 30  # safety cap on pagination walks

# FullTime team suffixes that are NOT the first team. Appearances for these
# never change a player's current first team.
NON_FIRST_SUFFIXES = ("Combination", "Reserves", "U21", "A", "B")

# FullTime raw club name -> DB team name. Anything not here falls back to
# suffix stripping and is then matched case-insensitively against the DB.
TEAM_NAME_OVERRIDES = {
    "St Johns United": "St Johns",
}


def clean_ft_team(raw: str) -> Tuple[str, bool]:
    """Normalize a FullTime team cell to a club name.

    Returns (club_name, is_first_team). 'Peel First' -> ('Peel', True).
    'Laxey Combination' -> ('Laxey', False).
    """
    raw = (raw or "").strip()
    raw = html_mod.unescape(raw)
    if "," in raw:  # multi-team cell — caller decides; return as-is flagged
        return raw, False
    is_first = True
    for suf in ("First",) + NON_FIRST_SUFFIXES:
        if raw.endswith(" " + suf):
            is_first = suf == "First"
            raw = raw[: -(len(suf) + 1)]
            break
    raw = raw.strip()
    raw = TEAM_NAME_OVERRIDES.get(raw, raw)
    return raw, is_first


def norm_name(name: str) -> str:
    """Case/space-insensitive player-name key."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def split_multi_team(raw: str) -> List[str]:
    """Split a statLeaders Team cell that may hold several clubs.

    FullTime joins them with commas and/or <BR/> tags (both observed).
    Order is preserved: the FIRST listed club is the player's primary team.
    """
    txt = re.sub(r"<\s*[Bb][Rr]\s*/?\s*>", ",", raw or "")
    parts = [html_mod.unescape(p).strip() for p in txt.split(",")]
    return [p for p in parts if p]


def strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

def fetch(url: str, retries: int = 3) -> str:
    """GET a fulltime.thefa.com page with Chrome TLS impersonation."""
    last_err = None
    for attempt in range(retries):
        try:
            r = cr.get(url, impersonate=IMPERSONATE, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r.text
            last_err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(FETCH_DELAY * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_err}")


def api_get(endpoint: str) -> list:
    """GET a FullTime API endpoint (JSON list)."""
    url = f"{FULLTIME_API_BASE_URL}/{endpoint}"
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=API_TIMEOUT, headers={"User-Agent": UA})
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(FETCH_DELAY * (attempt + 1))
    raise RuntimeError(f"FullTime API request failed for {url}: {last_err}")


# --------------------------------------------------------------------------
# Season / fixture-group discovery (HTML — the API has no season listing)
# --------------------------------------------------------------------------

def _selected_option(block_html: str) -> Optional[str]:
    m = re.search(r'<option value="([^"]*)"[^>]*selected', block_html)
    return m.group(1) if m else None


def discover_seasons() -> Dict[str, str]:
    """Parse the season dropdown on the results page: {'2025-26': '804198730'}."""
    page = fetch(f"{FULLTIME_BASE}/results.html?league={IOM_LEAGUE_ID}"
                 f"&selectedDivision={DIVISIONS['premier']}&selectedCompetition=0")
    m = re.search(r'<select name="selectedSeason".*?</select>', page, re.DOTALL)
    if not m:
        raise RuntimeError("could not find season dropdown on results page")
    seasons = {}
    for value, label in re.findall(
        r'<option value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', m.group(0)
    ):
        seasons[label.strip()] = value
    return seasons


def _parse_group_dropdown(page_html: str) -> Dict[str, str]:
    """fixture-group dropdown -> {'Canada Life Premier League': '1_xxx', ...}"""
    m = re.search(r'<select name="selectedFixtureGroupKey".*?</select>', page_html, re.DOTALL)
    groups = {}
    if m:
        for value, label in re.findall(
            r'<option value="([^"]*)"[^>]*>\s*([^<]+?)\s*</option>', m.group(0)
        ):
            groups[html_mod.unescape(label.strip())] = value
    return groups


def discover_fixture_group(season_id: str) -> str:
    """Find the Premier League fixture-group key for a season.

    The key changes every season, and the fixture-group dropdown only
    reflects the season the SESSION is currently viewing. Proven flow
    (verified 2026-08-20): bootstrap a session with the plain results URL
    shape carrying the CURRENT season's key (read from the league index
    page), then switch seasons with a form-style GET using previousSelected*
    params — FullTime only honours the switch inside an established session.
    """
    from collections import Counter
    s = cr.Session(impersonate=IMPERSONATE, headers=HEADERS)

    # 1. read the current season + its PL group key from the league index page
    idx = s.get(f"{FULLTIME_BASE}/index.html?league={IOM_LEAGUE_ID}", timeout=60)
    sel = re.search(r'<select name="selectedSeason".*?</select>', idx.text, re.DOTALL)
    cur_season = _selected_option(sel.group(0)) if sel else None
    keys = Counter(k for k in re.findall(r"selectedFixtureGroupKey=([0-9_]+)", idx.text)
                   if k.startswith("1_"))  # 1_ = league groups, 2_ = cups
    if not keys:
        raise RuntimeError("no fixture group key on league index page")
    cur_key = keys.most_common(1)[0][0]
    time.sleep(FETCH_DELAY)

    # 2. establish the session on the plain results page with that key
    r = s.get(f"{FULLTIME_BASE}/results.html?selectedSeason={cur_season}"
              f"&selectedFixtureGroupAgeGroup=0&selectedFixtureGroupKey={cur_key}"
              f"&selectedRelatedFixtureOption=1&selectedClub=&selectedTeam="
              f"&selectedDateCode=all&previousSelectedFixtureGroupAgeGroup="
              f"&previousSelectedFixtureGroupKey={cur_key}&previousSelectedClub=",
              timeout=60)
    page = r.text

    # 3. switch seasons within the session if needed
    if cur_season != season_id:
        time.sleep(FETCH_DELAY)
        r = s.get(f"{FULLTIME_BASE}/results.html?selectedSeason={season_id}"
                  f"&selectedFixtureGroupAgeGroup=0&selectedFixtureGroupKey={cur_key}"
                  f"&selectedRelatedFixtureOption=1&selectedClub=&selectedTeam="
                  f"&selectedDateCode=all&previousSelectedFixtureGroupAgeGroup=0"
                  f"&previousSelectedFixtureGroupKey={cur_key}&previousSelectedClub=",
                  timeout=60)
        page = r.text
        sel = re.search(r'<select name="selectedSeason".*?</select>', page, re.DOTALL)
        now = _selected_option(sel.group(0)) if sel else None
        if now != season_id:
            raise RuntimeError(
                f"season switch failed: wanted {season_id}, page shows {now}")

    # 4. read the PL group key for the now-selected season
    groups = _parse_group_dropdown(page)
    key = groups.get(PREMIER_LEAGUE_NAME)
    if key:
        return key

    # Fallback: a season with no results yet renders an EMPTY fixture-group
    # dropdown. In that case read the key off the fixtures page instead.
    try:
        fx = s.get(f"{FULLTIME_BASE}/fixtures.html?selectedSeason={season_id}"
                   f"&selectedDivision={DIVISIONS['premier']}", timeout=60)
        fx_groups = _parse_group_dropdown(fx.text)
        key = fx_groups.get(PREMIER_LEAGUE_NAME)
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(f"no '{PREMIER_LEAGUE_NAME}' fixture group found for season {season_id}")


# --------------------------------------------------------------------------
# Phase 1: results (FullTime API)
# --------------------------------------------------------------------------

@dataclass
class FtResult:
    fixture_id: Optional[str]  # HTML only; None when sourced from the API
    date: datetime
    home_raw: str
    away_raw: str
    home_score: Optional[int]
    away_score: Optional[int]
    ht_home: Optional[int]
    ht_away: Optional[int]
    walkover: Optional[str]  # None | 'home' | 'away' | 'pending'
    competition: str


def parse_api_score(score_str: str) -> Tuple[Optional[int], Optional[int],
                                              Optional[int], Optional[int], Optional[str]]:
    """Parse FullTime API score strings -> (hs, as, ht_h, ht_a, walkover)."""
    if not score_str:
        return None, None, None, None, "pending"
    if "Walkover" in score_str:
        return None, None, None, None, ("home" if score_str.startswith("Home") else "away")
    m = re.match(r"(\d+)\s*-\s*(\d+)", score_str.strip())
    if not m:
        return None, None, None, None, "pending"
    hs, ws = int(m.group(1)), int(m.group(2))
    ht = re.search(r"\(HT\s+(\d+)\s*-\s*(\d+)\)", score_str)
    ht_home, ht_away = (int(ht.group(1)), int(ht.group(2))) if ht else (None, None)
    return hs, ws, ht_home, ht_away, None


def fetch_results_api(season_id: str, last: Optional[int] = None) -> List[FtResult]:
    """Season results from the FullTime API, Premier League only, newest first."""
    rows = api_get(f"Results/{DIVISIONS['premier']}/season/{season_id}")
    out: List[FtResult] = []
    for row in rows:
        comp = row.get("division", "") or ""
        if PREMIER_LEAGUE_NAME.lower() not in comp.lower():
            continue  # skip cups/shields — the fantasy DB tracks league only
        try:
            date = datetime.strptime(row["fixtureDateTime"], "%d/%m/%y %H:%M")
        except (KeyError, ValueError):
            continue
        hs, ws, ht_h, ht_a, walkover = parse_api_score(row.get("score", ""))
        out.append(FtResult(None, date, row.get("homeTeam", ""), row.get("awayTeam", ""),
                            hs, ws, ht_h, ht_a, walkover, comp))
    out.sort(key=lambda r: r.date, reverse=True)
    return out[:last] if last else out


def parse_results_page(page_html: str) -> List[FtResult]:
    """Parse one HTML results page (fixture ids + everything else)."""
    out = []
    starts = [(m.group(1), m.start()) for m in re.finditer(r'<div id="fixture-(\d+)"', page_html)]
    for i, (fid, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(page_html)
        block = page_html[start:end]

        dt = re.search(r"<span>(\d\d/\d\d/\d\d)</span>\s*<span[^>]*>(\d\d:\d\d)</span>", block)
        if not dt:
            continue
        date = datetime.strptime(dt.group(1), "%d/%m/%y")
        time_str = dt.group(2)

        home_m = re.search(r'home-team-col.*?<a href="/displayFixture[^"]*">\s*([^<]+?)\s*</a>', block, re.DOTALL)
        away_m = re.search(r'road-team-col.*?<a href="/displayFixture[^"]*">\s*([^<]+?)\s*</a>', block, re.DOTALL)
        if not home_m or not away_m:
            continue
        home_raw = html_mod.unescape(home_m.group(1).strip())
        away_raw = html_mod.unescape(away_m.group(1).strip())

        score_m = re.search(r'<div class="score-col">(.*?)</div>', block, re.DOTALL)
        hs = ws = ht_home = ht_away = None
        walkover = None
        if score_m:
            sc = score_m.group(1)
            hs, ws, ht_home, ht_away, walkover = parse_api_score(strip_tags(sc))
            ht = re.search(r"\(HT\s+(\d+)\s*-\s*(\d+)\)", sc)
            if ht:
                ht_home, ht_away = int(ht.group(1)), int(ht.group(2))
            if walkover is None and hs is None:
                walkover = "pending"

        fg = re.search(r'<div class="fg-col">\s*<p[^>]*>([^<]+?)</p>', block)
        competition = html_mod.unescape(fg.group(1).strip()) if fg else ""

        try:
            kickoff = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            kickoff = None
        date = datetime.combine(date.date(), kickoff) if kickoff else date

        out.append(FtResult(fid, date, home_raw, away_raw, hs, ws,
                            ht_home, ht_away, walkover, competition))
    return out


def fetch_results_html(season_id: str, fixture_group: str,
                        last: Optional[int] = None) -> List[FtResult]:
    """Walk the paginated HTML results list (fixture ids), newest first."""
    all_rows: List[FtResult] = []
    page = 1
    while page <= MAX_PAGES:
        url = (f"{FULLTIME_BASE}/results/{page}/100.html?selectedSeason={season_id}"
               f"&selectedFixtureGroupAgeGroup=0&selectedFixtureGroupKey={fixture_group}"
               f"&selectedRelatedFixtureOption=1&selectedDateCode=all")
        rows = parse_results_page(fetch(url))
        # the listing also contains cup fixtures — keep PL only
        rows = [r for r in rows if PREMIER_LEAGUE_NAME.lower() in r.competition.lower()]
        if not rows:
            break
        all_rows.extend(rows)
        if last and len(all_rows) >= last:
            return all_rows[:last]
        if len(rows) < 100:  # short page = last page
            break
        page += 1
        time.sleep(FETCH_DELAY)
    return all_rows[:last] if last else all_rows


def find_db_fixture(con: sqlite3.Connection, res: FtResult,
                    team_ids_by_name: Dict[str, int], season: str) -> Optional[int]:
    home = clean_ft_team(res.home_raw)[0]
    away = clean_ft_team(res.away_raw)[0]
    hid = team_ids_by_name.get(home.casefold())
    aid = team_ids_by_name.get(away.casefold())
    date_iso = res.date.date().isoformat()
    rows = con.execute(
        "select id from fixtures where home_team_id=? and away_team_id=? and date(date)=?",
        (hid, aid, date_iso),
    ).fetchall() if hid and aid else []
    if not rows:
        rows = con.execute(
            "select id from fixtures where home_team_name=? and away_team_name=? and date(date)=?",
            (home, away, date_iso),
        ).fetchall()
        if not rows:
            rows = con.execute(
                "select id from fixtures where lower(home_team_name)=? and lower(away_team_name)=? and date(date)=?",
                (home.casefold(), away.casefold(), date_iso),
            ).fetchall()
    if not rows:
        # Rescheduled fixture: same home/away pairing (unique per season in a
        # double round-robin) but a different date. Restrict to the season
        # being synced so we never match another season's reverse fixture.
        rows = con.execute(
            "select f.id from fixtures f join gameweeks g on g.id=f.gameweek_id "
            "where g.season=? and f.home_team_id=? and f.away_team_id=?",
            (season, hid, aid),
        ).fetchall() if hid and aid else []
    return rows[0][0] if rows else None


def phase_results(con: sqlite3.Connection, results: List[FtResult],
                  team_ids_by_name: Dict[str, int], season: str,
                  dry_run: bool, verbose: bool) -> dict:
    stats = {"updated": 0, "already": 0, "unknown": [], "walkovers": 0, "pending": 0}
    for res in results:
        if res.walkover == "pending":
            stats["pending"] += 1
            continue  # result not entered on FullTime yet — nothing to sync
        fid = find_db_fixture(con, res, team_ids_by_name, season)
        if fid is None:
            stats["unknown"].append(res)
            continue
        cur = con.execute(
            "select home_score, away_score, half_time_home, half_time_away, played, kickoff_time "
            "from fixtures where id=?", (fid,),
        ).fetchone()
        kickoff = res.date.time().isoformat() if res.date.time() else None
        if res.walkover in ("home", "away"):
            new_vals = (None, None, None, None, 1, kickoff)
            stats["walkovers"] += 1
        else:
            new_vals = (res.home_score, res.away_score, res.ht_home, res.ht_away, 1, kickoff)
        if tuple(cur) == new_vals:
            stats["already"] += 1
            continue
        if verbose or dry_run:
            print(f"  fixture {fid}: {res.home_raw} vs {res.away_raw} on {res.date:%d/%m/%y} "
                  f"-> {new_vals[0]}-{new_vals[1]}" + (f" ({res.walkover} walkover)" if res.walkover else "")
                  + f"  [was {cur[0]}-{cur[1]}]")
        if not dry_run:
            con.execute(
                "update fixtures set home_score=?, away_score=?, half_time_home=?, "
                "half_time_away=?, played=?, kickoff_time=? where id=?",
                (*new_vals, fid),
            )
        stats["updated"] += 1
    return stats


# --------------------------------------------------------------------------
# Phase 2: lineups -> current team detection
# --------------------------------------------------------------------------

@dataclass
class FixtureLineups:
    fixture_id: str
    date: datetime
    home_raw: str
    away_raw: str
    home_players: List[str] = field(default_factory=list)  # starters + subs
    away_players: List[str] = field(default_factory=list)


def parse_fixture_detail(page_html: str) -> Optional[FixtureLineups]:
    i = page_html.find("fixture-lineup-statistics")
    if i < 0:
        return None
    j = page_html.find("</section>", i)
    block = page_html[i:j if j > 0 else i + 40000]

    hm = block.find("home-team flex right")
    rm = block.find("road-team flex left")
    if hm < 0 or rm < 0:
        return None
    home_part, road_part = block[hm:rm], block[rm:]

    def names(part: str) -> List[str]:
        # player blocks only; 'Lineup not yet announced' message divs have no
        # player blocks so they contribute nothing
        out = []
        for chunk in part.split('class="player flex middle"')[1:]:
            m = re.search(r"<p>\s*([^<]+?)\s*</p>", chunk)
            if m:
                out.append(html_mod.unescape(m.group(1).strip()))
        return out

    date_m = re.search(r"(\d\d/\d\d/\d\d)", page_html)
    date = datetime.strptime(date_m.group(1), "%d/%m/%y") if date_m else datetime.min
    teams = re.findall(r'alt="([^"]+)"', page_html)[:2]
    home_raw = teams[0] if len(teams) > 0 else ""
    away_raw = teams[1] if len(teams) > 1 else ""
    return FixtureLineups("", date, home_raw, away_raw, names(home_part), names(road_part))


def fetch_lineups(results: List[FtResult], verbose: bool) -> List[FixtureLineups]:
    """Fetch fixture detail pages for played, non-walkover results."""
    out = []
    for res in results:
        if res.walkover or not res.fixture_id:
            continue
        url = f"{FULLTIME_BASE}/displayFixture.html?id={res.fixture_id}"
        try:
            detail = parse_fixture_detail(fetch(url))
        except Exception as e:  # noqa: BLE001
            print(f"  ! lineup fetch failed for fixture {res.fixture_id}: {e}")
            continue
        if detail:
            detail.fixture_id = res.fixture_id
            detail.date = res.date  # results-page date is authoritative
            detail.home_raw, detail.away_raw = res.home_raw, res.away_raw
            out.append(detail)
            if verbose:
                print(f"  lineup fixture {res.fixture_id}: "
                      f"{len(detail.home_players)} home / {len(detail.away_players)} away names")
        time.sleep(FETCH_DELAY)
    return out


def phase_teams(con: sqlite3.Connection, lineups: List[FixtureLineups],
                team_ids_by_name: Dict[str, int], team_division: Dict[int, int],
                premier_division_id: int, dry_run: bool, verbose: bool) -> dict:
    """Set each appearing player's current team from their LATEST appearance."""
    # newest-first appearance map: norm_name -> (date, club_name, fixture_id)
    latest: Dict[str, Tuple[datetime, str, str]] = {}
    ambiguous = []
    for lu in sorted(lineups, key=lambda x: x.date):  # ascending; later wins
        for raw_side, players in ((lu.home_raw, lu.home_players), (lu.away_raw, lu.away_players)):
            club, is_first = clean_ft_team(raw_side)
            if not is_first:
                continue  # only first-team fixtures reassign first teams
            for pname in players:
                key = norm_name(pname)
                prev = latest.get(key)
                if prev and prev[0] == lu.date and prev[1] != club:
                    ambiguous.append((pname, lu.date.date().isoformat()))
                latest[key] = (lu.date, club, lu.fixture_id)

    stats = {"seen": len(latest), "moves": [], "reactivated": [], "deactivated": [],
             "unmapped_teams": [], "no_db_match": [], "ambiguous": ambiguous}

    for key, (date, club, fid) in sorted(latest.items()):
        club_key = club.casefold()
        new_team_id = team_ids_by_name.get(club_key)
        if new_team_id is None:
            stats["unmapped_teams"].append((key, club))
            continue
        row = con.execute(
            "select id, name, team_id, is_active, now_playing from players "
            "where lower(name)=? and team_id=?", (key, new_team_id),
        ).fetchone()
        if row is None:
            # player appears for a team they're not registered to in the DB:
            # find any DB row with this name (they moved)
            rows = con.execute(
                "select id, name, team_id, is_active, now_playing from players where lower(name)=?",
                (key,),
            ).fetchall()
            if not rows:
                stats["no_db_match"].append((key, club))
                continue
            if len(rows) > 1:
                stats["ambiguous"].append((key, f"{len(rows)} DB rows named {key}"))
                continue
            pid, pname, old_team_id, is_active, now_playing = rows[0]
            old_club = con.execute("select name from teams where id=?", (old_team_id,)).fetchone()[0]
            in_pool = team_division.get(new_team_id) == premier_division_id
            if verbose or dry_run:
                print(f"  MOVE: {pname}: {old_club} -> {club} "
                      f"(last seen {date:%d/%m/%y}, fixture {fid})"
                      + ("  [now in fantasy pool]" if in_pool else "  [leaves fantasy pool]"))
            if not dry_run:
                con.execute(
                    "update players set team_id=?, is_active=?, now_playing=? where id=?",
                    (new_team_id, 1 if in_pool else 0, 1 if in_pool else 0, pid),
                )
            stats["moves"].append((pname, old_club, club, date.date().isoformat()))
            if in_pool and not is_active:
                stats["reactivated"].append(pname)
            if not in_pool and is_active:
                stats["deactivated"].append(pname)
        else:
            # already registered to the right team; make sure flags are right
            pid, pname, team_id, is_active, now_playing = row
            in_pool = team_division.get(new_team_id) == premier_division_id
            want = 1 if in_pool else 0
            if is_active != want or now_playing != want:
                if not dry_run:
                    con.execute(
                        "update players set is_active=?, now_playing=? where id=?",
                        (want, want, pid),
                    )
                if want and not is_active:
                    stats["reactivated"].append(pname)
                if not want and is_active:
                    stats["deactivated"].append(pname)
    return stats


# --------------------------------------------------------------------------
# Phase 3: statLeaders season stats
# --------------------------------------------------------------------------

STAT_COLS = ["apps", "overall_goals", "goals", "penalties", "assists",
             "yellow_cards", "red_cards", "second_yellow", "sin_bin",
             "started", "subbed_on", "subbed_off", "bench_used",
             "bench_unused", "minutes_played", "own_goal_conceded",
             "captain", "player_of_match"]


@dataclass
class StatRow:
    person_id: Optional[str]
    name: str
    team_raw: str  # raw HTML cell; may join several clubs with , or <BR/>
    values: List[int]


def parse_stats_page(page_html: str) -> List[StatRow]:
    tbody = re.search(r"<tbody>(.*?)</tbody>", page_html, re.DOTALL)
    if not tbody or len(tbody.group(1).strip()) < 10:
        return []  # empty table (e.g. current season before first results)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.DOTALL):
        person_m = re.search(r'statsForPlayer\.html\?personID=(\d+)', tr)
        name_m = re.search(
            r'<th class="left nowrap fixed-col[^"]*">\s*(?:<a[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</th>', tr)
        # Team cell: the name div may contain <BR/> between multiple clubs,
        # so take the LAST non-empty <div> inside the mobile-scroll-col th.
        # Keep the raw HTML (<BR/> etc.) — split_multi_team() handles it.
        team_raw = ""
        tm = re.search(r'mobile-scroll-col.*?</th>', tr, re.DOTALL)
        if tm:
            for div_body in re.findall(r"<div>(.*?)</div>", tm.group(0), re.DOTALL):
                if strip_tags(div_body):
                    team_raw = div_body
        if not name_m:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        vals = []
        for td in tds:
            txt = strip_tags(td)
            try:
                vals.append(int(txt))
            except ValueError:
                vals.append(0)
        # pad/truncate to the known column count
        vals = (vals + [0] * len(STAT_COLS))[:len(STAT_COLS)]
        rows.append(StatRow(
            person_id=person_m.group(1) if person_m else None,
            name=html_mod.unescape(name_m.group(1).strip()),
            team_raw=team_raw,
            values=vals,
        ))
    return rows


def fetch_all_stats(season_id: str, division_id: str, verbose: bool) -> List[StatRow]:
    all_rows: List[StatRow] = []
    page = 1
    while page <= MAX_PAGES:
        url = (f"{FULLTIME_BASE}/statLeaders/{page}/100.html?selectedSeason={season_id}"
               f"&selectedFixtureGroupAgeGroup=0&selectedDivision={division_id}"
               f"&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=2520964")
        rows = parse_stats_page(fetch(url))
        if verbose:
            print(f"  stats page {page} (div {division_id}): {len(rows)} rows")
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 100:
            break
        page += 1
        time.sleep(FETCH_DELAY)
    return all_rows


def ensure_person_id_column(con: sqlite3.Connection):
    cols = [c[1] for c in con.execute("pragma table_info(players)")]
    if "ft_person_id" not in cols:
        con.execute("alter table players add column ft_person_id varchar(20)")
        con.execute("create index if not exists ix_players_ft_person_id "
                    "on players (ft_person_id)")


def phase_stats(con: sqlite3.Connection, stat_rows: List[StatRow],
                team_ids_by_name: Dict[str, int], dry_run: bool, verbose: bool) -> dict:
    """Update season stats. Match by person_id first, then name+team."""
    ensure_person_id_column(con)
    stats = {"updated": 0, "multi_team_skipped": [],
             "no_db_match": [], "pages_rows": len(stat_rows)}
    person_to_player: Dict[str, int] = {}
    for pid, pid_db in con.execute(
        "select ft_person_id, id from players where ft_person_id is not null"
    ):
        person_to_player[pid] = pid_db
    name_team_to_player: Dict[Tuple[str, int], int] = {}
    name_to_players: Dict[str, List[int]] = {}
    for pid_db, name, team_id in con.execute("select id, name, team_id from players"):
        name_team_to_player[(norm_name(name), team_id)] = pid_db
        name_to_players.setdefault(norm_name(name), []).append(pid_db)

    for row in stat_rows:
        apps, overall_goals, assists = row.values[0], row.values[1], row.values[4]
        yellows, reds, minutes = row.values[5], row.values[6], row.values[14]

        teams = split_multi_team(row.team_raw)
        club_ids = []
        for t in teams:
            c, _ = clean_ft_team(t)
            cid = team_ids_by_name.get(c.casefold())
            if cid is not None:
                club_ids.append(cid)

        pid_db = None
        if row.person_id and row.person_id in person_to_player:
            pid_db = person_to_player[row.person_id]
        else:
            # try name+club for EACH listed club in order (handles players
            # who appeared for several clubs this season and name duplicates)
            for cid in club_ids:
                pid_db = name_team_to_player.get((norm_name(row.name), cid))
                if pid_db is not None:
                    break
            if pid_db is None:
                cands = name_to_players.get(norm_name(row.name), [])
                if len(cands) == 1:
                    pid_db = cands[0]

        if pid_db is None:
            stats["no_db_match"].append((row.name, strip_tags(row.team_raw)))
            continue

        updates = {
            "apps": apps, "goals": overall_goals, "assists": assists,
            "yellow_cards": yellows, "red_cards": reds, "minutes_played": minutes,
        }
        if row.person_id:
            updates["ft_person_id"] = row.person_id

        if not dry_run:
            sets = ", ".join(f"{k}=?" for k in updates)
            con.execute(f"update players set {sets} where id=?",
                        (*updates.values(), pid_db))
        stats["updated"] += 1

        # multi-team players get flagged (the teams phase reconciles them)
        if len(teams) > 1:
            stats["multi_team_skipped"].append((row.name, strip_tags(row.team_raw)))
    return stats


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def load_teams(con: sqlite3.Connection):
    team_ids_by_name: Dict[str, int] = {}
    team_division: Dict[int, int] = {}
    for tid, name, div_id in con.execute("select id, name, division_id from teams"):
        team_ids_by_name[name.casefold()] = tid
        team_division[tid] = div_id
    premier_division_id = con.execute(
        "select id from divisions where ft_id=?", (DIVISIONS["premier"],)
    ).fetchone()
    premier_division_id = premier_division_id[0] if premier_division_id else 1
    return team_ids_by_name, team_division, premier_division_id


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.getenv("FFIOM_DB_PATH", "/data/ffiom/fantasy_iom.db"),
                    help="path to the FFIOM reference DB")
    ap.add_argument("--season", default="latest",
                    help="season label (e.g. 2025-26), FullTime season id, or 'latest'")
    ap.add_argument("--results", action="store_true", help="sync fixture results")
    ap.add_argument("--teams", action="store_true", help="detect current teams from lineups")
    ap.add_argument("--stats", action="store_true", help="sync season stats from statLeaders")
    ap.add_argument("--all", action="store_true", help="all phases")
    ap.add_argument("--last", type=int, default=None,
                    help="only the most recent N results (test mode)")
    ap.add_argument("--divisions", default="premier,d2",
                    help="comma list for the stats phase: premier,d2 (default — the divisions the "
                         "fantasy pool covers) or all (aggregated, includes combination/U21 noise)")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    do_results = args.results or args.all
    do_teams = args.teams or args.all
    do_stats = args.stats or args.all
    if not (do_results or do_teams or do_stats):
        ap.error("pick at least one phase: --results --teams --stats or --all")
    if not os.path.exists(args.db):
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    print(f"FFIOM FullTime sync — DB {args.db} — "
          f"phases: {'+'.join(p for p, on in (('results', do_results), ('teams', do_teams), ('stats', do_stats)) if on)}"
          + (" — DRY RUN" if args.dry_run else ""))
    print(f"FullTime API: {FULLTIME_API_BASE_URL}")

    # ---- resolve season ----
    seasons = discover_seasons()
    print(f"FullTime seasons available: {seasons}")
    if args.season == "latest":
        label = sorted(seasons)[-1]  # '2026-27' > '2025-26' lexically
        season_id = seasons[label]
    elif args.season in seasons:
        label, season_id = args.season, seasons[args.season]
    elif args.season in seasons.values():
        label = next(k for k, v in seasons.items() if v == args.season)
        season_id = args.season
    else:
        print(f"ERROR: unknown season {args.season!r}; available: {list(seasons)}", file=sys.stderr)
        sys.exit(1)
    print(f"Season: {label} (id {season_id})")

    # ---- backup ----
    if not args.dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{args.db}.pre_fulltime_sync_{ts}"
        shutil.copy2(args.db, backup)
        print(f"Backup: {backup}")

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys=ON")
    team_ids_by_name, team_division, premier_division_id = load_teams(con)

    try:
        # ---- phase 1: results (FullTime API) ----
        api_results: List[FtResult] = []
        if do_results:
            print(f"\n=== Fetching results from FullTime API (season {label}) ===")
            api_results = fetch_results_api(season_id, last=args.last)
            print(f"Fetched {len(api_results)} Premier League results"
                  + (f" (limited to last {args.last})" if args.last else ""))
            if api_results:
                print(f"  newest: {api_results[0].date:%d/%m/%y} {api_results[0].home_raw} vs {api_results[0].away_raw}")
                print(f"  oldest: {api_results[-1].date:%d/%m/%y} {api_results[-1].home_raw} vs {api_results[-1].away_raw}")
            r = phase_results(con, api_results, team_ids_by_name, label, args.dry_run, args.verbose)
            print(f"\n--- RESULTS: {r['updated']} updated, {r['already']} already current, "
                  f"{r['walkovers']} walkovers, {r['pending']} pending results, "
                  f"{len(r['unknown'])} not in DB ---")
            for res in r["unknown"]:
                print(f"    unknown fixture: {res.date:%d/%m/%y} {res.home_raw} vs {res.away_raw} "
                      f"({res.competition or '?'})")

        # ---- phase 2: current teams (HTML lineups) ----
        if do_teams:
            print("\n=== Discovering fixture group key (lineups need HTML) ===")
            try:
                fixture_group = discover_fixture_group(season_id)
            except RuntimeError as e:
                print(f"  ! skipping teams phase: {e}")
                fixture_group = None
            if fixture_group:
                print(f"Fixture group key for {label}: {fixture_group}")
                print(f"Fetching HTML results list (fixture ids), season {label}")
                html_results = fetch_results_html(season_id, fixture_group, last=args.last)
                print(f"Fetched {len(html_results)} results with fixture ids")
                lineups = fetch_lineups(html_results, args.verbose)
                t = phase_teams(con, lineups, team_ids_by_name, team_division,
                                premier_division_id, args.dry_run, args.verbose)
                print(f"\n--- TEAMS: {t['seen']} players seen in lineups, "
                      f"{len(t['moves'])} moves applied ---")
                for pname, old, new, d in t["moves"]:
                    print(f"    MOVE {pname}: {old} -> {new} (last seen {d})")
                if t["reactivated"]:
                    print(f"    reactivated (back in fantasy pool): {t['reactivated']}")
                if t["deactivated"]:
                    print(f"    deactivated (left fantasy pool): {t['deactivated']}")
                if t["no_db_match"]:
                    print(f"    no DB match (new players? {len(t['no_db_match'])}):")
                    for k, club in t["no_db_match"][:20]:
                        print(f"      - {k} ({club})")
                if t["unmapped_teams"]:
                    print(f"    unmapped FullTime teams: {sorted(set(t['unmapped_teams']))}")
                if t["ambiguous"]:
                    print(f"    ambiguous (NOT changed): {t['ambiguous'][:10]}")

        # ---- phase 3: season stats (HTML statLeaders) ----
        if do_stats:
            print(f"\n=== Fetching statLeaders tables (divisions: {args.divisions}) ===")
            all_stat_rows: List[StatRow] = []
            for div_key in [d.strip() for d in args.divisions.split(",") if d.strip()]:
                div_id = DIVISIONS.get(div_key)
                if not div_id:
                    print(f"  ! unknown division {div_key!r}, skipping")
                    continue
                rows = fetch_all_stats(season_id, div_id, args.verbose)
                print(f"  division {div_key}: {len(rows)} player rows")
                all_stat_rows.extend(rows)
            s = phase_stats(con, all_stat_rows, team_ids_by_name, args.dry_run, args.verbose)
            print(f"\n--- STATS: {s['updated']} players updated of {s['pages_rows']} scraped ---")
            if s["multi_team_skipped"]:
                print(f"    multi-team players flagged ({len(s['multi_team_skipped'])}):")
                for name, tr in s["multi_team_skipped"][:15]:
                    print(f"      - {name}: {tr}")
            if s["no_db_match"]:
                print(f"    no DB match ({len(s['no_db_match'])}):")
                for name, tr in s["no_db_match"][:15]:
                    print(f"      - {name} ({tr})")

        if not args.dry_run:
            con.commit()
            print("\nCommitted.")
        else:
            con.rollback()
            print("\nDRY RUN — nothing written.")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
