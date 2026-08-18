#!/usr/bin/env python3
"""Import 25/26 season players (PL + Division 2) into the FFIOM player DB.

- Adds Division 2 ('Druggan Ltd Division 2') + 8 D2 teams.
- Inserts NEW players only (existing rows are never touched).
- 26/27 Premier League clubs -> is_active=1; relegated/D2 -> is_active=0 (hidden).
- Price = established formula (verified 172/172): 5.0 floor, +0.05 per 25/26 fantasy
  point (4*goals + 3*assists), 17.0 cap, <5 apps -> 5.0.
- Season stat columns are left zeroed (25/26 is over; 26/27 is the live season).

Usage: python build_import.py <db-path>
"""
import json
import os
import sqlite3
import sys
from collections import Counter

WS = os.path.dirname(os.path.abspath(__file__))

ACTIVE_TEAMS = {
    "Ayre United", "Braddan", "Colby", "Corinthians", "Laxey", "Onchan", "Peel",
    "RYCOB", "Ramsey", "Rushen United", "St Johns", "St Marys", "Union Mills",
}
# D2-page rows that are zero-stat duplicates of PL-page players (same names, 0 apps)
SKIP_D2_TEAMS = {"Braddan", "DHSOB"}
# D2 teams to create (division 2)
D2_TEAMS = [
    "Castletown", "Douglas & District", "Douglas Royal", "Governors Athletic",
    "Malew", "Marown", "Pulrose United", "St Georges",
]
D2_DIVISION = ("715559946", "Druggan Ltd Division 2")


def clean_team(raw: str) -> str:
    raw = (raw or "").strip()
    if "," in raw:
        raw = raw.split(",")[0].strip()
    for suf in (" First", " Combination", " Reserves"):
        raw = raw.replace(suf, "")
    raw = raw.strip()
    if raw == "St Johns United":
        raw = "St Johns"
    return raw


def price_for(apps: int, pts: int) -> float:
    if apps < 5:
        return 5.0
    return round(min(17.0, max(5.0, 5.0 + 0.05 * pts)), 1)


def web_slug(name: str) -> str:
    slug = name.lower()
    out = []
    for ch in slug:
        if ch.isalnum():
            out.append(ch)
        elif ch in " '-":
            out.append("_")
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def build_import_list():
    recs = json.load(open(os.path.join(WS, "scraped_players.json"), encoding="utf-8"))
    rows = {}
    for rec in recs:
        raw_team = rec["team_raw"]
        team = clean_team(raw_team)
        if rec["div"] == "D2" and team in SKIP_D2_TEAMS:
            continue
        if team not in ACTIVE_TEAMS and team not in D2_TEAMS and team not in {"Foxdale", "DHSOB"}:
            print(f"  UNMAPPED TEAM: {rec['name']!r} -> {raw_team!r}")
            continue
        key = (rec["name"].strip().lower(), team)
        apps = rec.get("apps") or 0
        goals = rec.get("goals") or 0
        assists = rec.get("assists") or 0
        pts = 4 * goals + 3 * assists
        row = {
            "name": rec["name"].strip(),
            "team": team,
            "apps": apps,
            "goals": goals,
            "assists": assists,
            "pts": pts,
            "price": price_for(apps, pts),
            "active": 1 if team in ACTIVE_TEAMS else 0,
            "div": rec["div"],
        }
        # duplicate (name, team) across pages -> keep the one with more apps
        if key not in rows or row["apps"] > rows[key]["apps"]:
            rows[key] = row
    return list(rows.values())


def main():
    if len(sys.argv) != 2:
        print("usage: build_import.py <db-path>")
        sys.exit(2)
    db_path = sys.argv[1]
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    try:
        # --- reference: mirror one existing row so new rows match the house style ---
        ref = con.execute(
            "select * from players where is_active=1 and position is not null limit 1"
        ).fetchone()
        cols = [c[1] for c in con.execute("pragma table_info(players)")]
        print("=== reference existing row ===")
        for c, v in zip(cols, ref):
            print(f"   {c:22} = {v!r}")

        # --- division ---
        d = con.execute(
            "select id from divisions where ft_id=?", (D2_DIVISION[0],)
        ).fetchone()
        if d:
            d2_id = d[0]
        else:
            cur = con.execute(
                "insert into divisions (ft_id, name, league_id) values (?,?,1)",
                (D2_DIVISION[0], D2_DIVISION[1]),
            )
            d2_id = cur.lastrowid
            print(f"created division {d2_id}: {D2_DIVISION[1]}")

        # --- D2 teams ---
        team_ids = {}
        for r in con.execute("select id, name from teams"):
            team_ids[r[1]] = r[0]
        for t in D2_TEAMS:
            if t in team_ids:
                continue
            cur = con.execute(
                "insert into teams (name, division_id) values (?,?)", (t, d2_id)
            )
            team_ids[t] = cur.lastrowid
            print(f"created team {cur.lastrowid}: {t} (division {d2_id})")
        # sanity: promoted clubs are in division 1
        for t in ("Colby", "RYCOB"):
            did = con.execute(
                "select division_id from teams where id=?", (team_ids[t],)
            ).fetchone()[0]
            print(f"  {t}: id={team_ids[t]} division_id={did}")

        # --- fix: promoted clubs missing division_id (26/27 PL clubs) ---
        fixed_div = []
        for t in ("Colby", "RYCOB"):
            r = con.execute(
                "update teams set division_id=1 where id=? and division_id is null",
                (team_ids[t],),
            )
            if r.rowcount:
                fixed_div.append(t)
        if fixed_div:
            print(f"  set division_id=1 (Premier League) for: {fixed_div}")

        # --- fix: relegated clubs' existing players must be hidden in 26/27 ---
        ph = ",".join("?" * len(ACTIVE_TEAMS))
        rel = con.execute(
            "select p.name, t.name from players p join teams t on t.id=p.team_id "
            "where p.is_active=1 and t.name not in (" + ph + ")",
            tuple(sorted(ACTIVE_TEAMS)),
        ).fetchall()
        if rel:
            con.execute(
                "update players set is_active=0 where is_active=1 and team_id in "
                "(select id from teams where name not in (" + ph + "))",
                tuple(sorted(ACTIVE_TEAMS)),
            )
            print(f"  deactivated {len(rel)} relegated-clubs players (now hidden):")
            for name, tname in rel:
                print(f"     - {name} ({tname})")
        else:
            print("  no active players on non-26/27-PL clubs (nothing to hide)")

        # --- existing players (never modified, only skipped) ---
        existing = set()
        for r in con.execute("select lower(name), team_id from players"):
            existing.add((r[0], r[1]))
        start_id = con.execute("select coalesce(max(id), 0) from players").fetchone()[0]

        # --- import list ---
        rows = build_import_list()
        new_rows, skipped = [], 0
        for row in rows:
            key = (row["name"].lower(), team_ids[row["team"]])
            if key in existing:
                skipped += 1
                continue
            new_rows.append(row)

        insert_cols = [
            "name", "web_name", "team_id", "position", "price", "price_start",
            "price_change", "price_change_event", "price_change_fall",
            "price_change_total", "selected_by_percent", "form", "in_dreamteam",
            "apps", "goals", "assists", "clean_sheets", "yellow_cards",
            "red_cards", "saves", "minutes_played", "bonus", "goals_conceded",
            "own_goals", "penalties_saved", "penalties_missed", "influence",
            "creativity", "threat", "ict_index", "goals_per_game",
            "total_points_season", "transfers_in", "transfers_out",
            "is_active", "is_injured", "now_playing",
        ]
        q = ",".join("?" for _ in insert_cols)
        sql = f"insert into players ({','.join(insert_cols)}) values ({q})"
        n_active = n_hidden = 0
        for row in new_rows:
            p = row["price"]
            vals = [
                row["name"], web_slug(row["name"]), team_ids[row["team"]], None,
                p, p, 0, 0, 0, 0, 0.0, 0.0, 0,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0,
                row["active"], 0, 1,
            ]
            con.execute(sql, vals)
            if row["active"]:
                n_active += 1
            else:
                n_hidden += 1

        con.commit()

        # --- verification ---
        total = con.execute("select count(*) from players").fetchone()[0]
        act = con.execute("select count(*) from players where is_active=1").fetchone()[0]
        hid = con.execute("select count(*) from players where is_active=0").fetchone()[0]
        fk = con.execute("pragma foreign_key_check").fetchall()
        dup = con.execute(
            "select lower(name), team_id, count(*) c from players group by 1,2 having c>1"
        ).fetchall()
        no_price = con.execute(
            "select count(*) from players where price_start is null or price is null"
        ).fetchone()[0]
        print("\n=== RESULT ===")
        print(f"  existing rows skipped (untouched): {skipped}")
        print(f"  new players inserted: {len(new_rows)}  (active {n_active} / hidden {n_hidden})")
        print(f"  total players now: {total}  (active {act} / hidden {hid})")
        print(f"  foreign_key_check: {fk or 'OK'}")
        print(f"  duplicate (name,team): {dup or 'none'}")
        print(f"  missing prices: {no_price}")
        print("  per-team counts:")
        for r in con.execute(
            "select t.name, d.name, count(*), sum(p.is_active) "
            "from players p join teams t on t.id=p.team_id "
            "join divisions d on d.id=t.division_id "
            "group by t.id order by t.id"
        ):
            print(f"   {r[0]:22} [{r[1][:28]:28}] total={r[2]:3} active={r[3]}")
        new_ids = [r[0] for r in con.execute("select id from players where id > ?", (start_id,))]
        if new_ids:
            r = con.execute(
                f"select min(price), max(price), round(avg(price),2) from players where id in "
                f"({','.join('?'*len(new_ids))})", new_ids
            ).fetchone()
            print(f"  new-player prices: min={r[0]} max={r[1]} avg={r[2]}")
    except Exception as e:
        con.rollback()
        print(f"ERROR (rolled back): {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        con.close()


if __name__ == "__main__":
    main()
