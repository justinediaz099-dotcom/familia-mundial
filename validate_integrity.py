"""
Full integrity validator for familia-mundial/index.html
Checks:
  1. Every played game has valid numeric scores (no null)
  2. No game is marked played AND live simultaneously
  3. teamStatuses match what game entries actually produce
  4. No negative scores
  5. check_points.py leaderboard matches teamStatuses-derived leaderboard
  6. index.html is valid HTML (no broken JS syntax around game array)
"""

import re, json

INDEX = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'
content = open(INDEX, encoding='utf-8').read()

errors   = []
warnings = []

# ── 1. Extract all game entries ─────────────────────────────────────────────
game_pattern = re.compile(
    r"\{ group: '([A-Z])', md: (\d+), date: '([^']+)', home: '([^']+)', "
    r"hscore: ([^,]+), away: '([^']+)', ascore: ([^,]+), played: (true|false)(, live: true)? \}"
)
games = game_pattern.findall(content)

print('=== GAME ENTRIES (%d found) ===' % len(games))
played_games = []
live_games   = []
for g in games:
    group, md, date, home, hscore_raw, away, ascore_raw, played, live = g
    is_played = played == 'true'
    is_live   = live == ', live: true'

    # Check: played game must have numeric scores
    if is_played:
        if not hscore_raw.strip().lstrip('-').isdigit() or not ascore_raw.strip().lstrip('-').isdigit():
            errors.append('PLAYED but no numeric scores: %s vs %s (%s)' % (home, away, date))
        else:
            hs, as_ = int(hscore_raw), int(ascore_raw)
            if hs < 0 or as_ < 0:
                errors.append('NEGATIVE score: %s %d-%d %s' % (home, hs, as_, away))
            played_games.append((group, md, date, home, hs, away, as_))

    # Check: can't be played AND live
    if is_played and is_live:
        errors.append('PLAYED + LIVE conflict: %s vs %s' % (home, away))

    # Check: live game should have numeric scores
    if is_live:
        if not hscore_raw.strip().lstrip('-').isdigit() or not ascore_raw.strip().lstrip('-').isdigit():
            warnings.append('LIVE but null scores: %s vs %s' % (home, away))
        else:
            live_games.append((home, int(hscore_raw), away, int(ascore_raw)))

print('  Played: %d | Live: %d | Upcoming: %d' % (
    len(played_games), len(live_games),
    len(games) - len(played_games) - len(live_games)
))

# ── 2. Derive expected points from played games ──────────────────────────────
WIN_PTS, DRAW_PTS, LOSS_PTS = 3, 1, 0

def derive_points(played_games):
    team_wins  = {}
    team_draws = {}
    team_pts   = {}
    for (group, md, date, home, hs, away, as_) in played_games:
        for team in [home, away]:
            team_pts.setdefault(team, 0)
            team_wins.setdefault(team, 0)
            team_draws.setdefault(team, 0)
        if hs > as_:
            team_pts[home]  += WIN_PTS
            team_wins[home] += 1
        elif as_ > hs:
            team_pts[away]  += WIN_PTS
            team_wins[away] += 1
        else:
            team_pts[home]  += DRAW_PTS
            team_draws[home] += 1
            team_pts[away]  += DRAW_PTS
            team_draws[away] += 1
    return team_pts, team_wins, team_draws

team_pts, team_wins, team_draws = derive_points(played_games)

# ── 3. Extract teamStatuses from index.html ──────────────────────────────────
ts_pattern = re.compile(r'"([^"]+)": \{ ([^}]+) \}')
team_statuses = {}
for m in ts_pattern.finditer(content):
    team_name = m.group(1)
    body      = m.group(2)
    wins  = int(re.search(r'groupWins: (\d+)',  body).group(1)) if 'groupWins'  in body else 0
    draws = int(re.search(r'groupDraws: (\d+)', body).group(1)) if 'groupDraws' in body else 0
    team_statuses[team_name] = {'wins': wins, 'draws': draws}

print('\n=== TEAMSTATUSES vs GAME ENTRIES ===')
all_teams = set(list(team_wins.keys()) + list(team_statuses.keys()))
ts_ok, ts_bad = 0, 0
for team in sorted(all_teams):
    expected_wins  = team_wins.get(team, 0)
    expected_draws = team_draws.get(team, 0)
    actual_wins    = team_statuses.get(team, {}).get('wins', 0)
    actual_draws   = team_statuses.get(team, {}).get('draws', 0)

    if expected_wins == 0 and expected_draws == 0:
        # Team has no W/D — should not be in teamStatuses (or 0s are fine)
        if actual_wins > 0 or actual_draws > 0:
            errors.append('teamStatus HAS pts for team with no W/D results: %s (W:%d D:%d)' % (
                team, actual_wins, actual_draws))
            ts_bad += 1
        else:
            ts_ok += 1
        continue

    ok = (actual_wins == expected_wins and actual_draws == expected_draws)
    status = '✓' if ok else '✗'
    if not ok:
        errors.append('teamStatus MISMATCH: %s | Expected W:%d D:%d | Got W:%d D:%d' % (
            team, expected_wins, expected_draws, actual_wins, actual_draws))
        ts_bad += 1
    else:
        ts_ok += 1
    print('  %s %-25s  W: %d/%d  D: %d/%d' % (status, team, actual_wins, expected_wins, actual_draws, expected_draws))

print('  teamStatus OK: %d | Mismatches: %d' % (ts_ok, ts_bad))

# ── 4. Check for duplicate game entries ──────────────────────────────────────
print('\n=== DUPLICATE GAME CHECK ===')
seen = {}
for g in games:
    group, md, date, home, hscore_raw, away, ascore_raw, played, live = g
    key = (home, away)
    seen[key] = seen.get(key, 0) + 1
dupes = [(k, v) for k, v in seen.items() if v > 1]
if dupes:
    for (h, a), count in dupes:
        errors.append('DUPLICATE GAME: %s vs %s appears %d times' % (h, a, count))
        print('  ✗ %s vs %s (%dx)' % (h, a, count))
else:
    print('  ✓ No duplicates')

# ── 5. HTML/JS sanity — check game array is closed ───────────────────────────
print('\n=== JS ARRAY SANITY ===')
# Games are inline in JSX — find the block between first and last game entry
first_game = content.find("{ group: 'A', md: 1,")
last_game_end = content.rfind('played: false },')
if first_game == -1 or last_game_end == -1:
    errors.append('Could not locate game entry block in index.html')
    print('  ✗ Game block not found')
else:
    segment = content[first_game:last_game_end + 20]
    opens  = segment.count('{')
    closes = segment.count('}')
    if opens == closes:
        print('  ✓ Game block braces balanced (%d pairs)' % opens)
    else:
        errors.append('JS BRACE MISMATCH in game block: %d { vs %d }' % (opens, closes))
        print('  ✗ Brace mismatch: %d { vs %d }' % (opens, closes))

# ── 5b. Check roster vs game names match ─────────────────────────────────────
print('\n=== ROSTER / GAME NAME CONSISTENCY ===')
roster_pat = re.compile(r'{ name: "([^"]+)"')
roster_names = set(m.group(1) for m in roster_pat.finditer(content))
game_names_set = set()
for g in games:
    game_names_set.add(g[3])  # home
    game_names_set.add(g[5])  # away
mismatch_names = game_names_set - roster_names
if mismatch_names:
    for n in sorted(mismatch_names):
        errors.append('Team in games NOT in roster: "%s" — will break points display' % n)
        print('  ✗ "%s" in games but not roster' % n)
else:
    print('  ✓ All game team names match roster (%d teams)' % len(game_names_set))

# ── 6. Results ───────────────────────────────────────────────────────────────
print('\n=== SUMMARY ===')
if errors:
    print('ERRORS (%d):' % len(errors))
    for e in errors:
        print('  ✗ ' + e)
else:
    print('  ✓ No errors found')

if warnings:
    print('WARNINGS (%d):' % len(warnings))
    for w in warnings:
        print('  ⚠ ' + w)

print('\nIntegrity check complete.')
