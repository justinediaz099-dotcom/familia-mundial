#!/usr/bin/env python3
"""
familia-mundial auto-updater v5.1
Polls ESPN scoreboard, detects score/status changes vs index.html, patches and pushes.
Handles both group stage (group/md) and knockout round (round) line formats.
teamStatuses is rebuilt from scratch after every update (never incremented).

v5.0: Auto-advancement flags
  - When a knockout match flips to played:true with a clear winner (hscore != ascore),
    automatically sets roundOf32/roundOf16/quarterFinal/semiFinal flag on the winning team.
  - Tied scores (extra time / penalties) → logs NEEDS_WINNER_CONFIRM warning, waits for manual input.

v5.1: Mirror sync fix
  - KO match updates now sync ALL three arrays: KO_MATCHES, r32All (r32schedule tab), and
    the matchId bracket array. Previously the r32schedule sync used a broken offset search,
    and the matchId array was never touched at all.
  - New sync_all_ko_mirrors() function handles all three with full-content regex — no offsets.
"""

import json, re, subprocess, urllib.request
from datetime import datetime, timedelta, timezone

ESPN_URL = 'https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard'
INDEX    = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'
REPO_DIR = 'C:/Users/diazjuso/Desktop/familia-mundial'

# Maps each knockout round to the flag awarded to the winner
ROUND_FLAG_MAP = {
    'r32': 'roundOf32',
    'r16': 'roundOf16',
    'qf':  'quarterFinal',
    'sf':  'semiFinal',
    'final': None,  # handled separately: champion + runnerUp
}

ESPN_NAME_MAP = {
    'Bosnia and Herzegovina': 'Bosnia & Herz.',
    'Bosnia-Herzegovina':     'Bosnia & Herz.',
    'Curacao':                'Curaçao',
    'DR Congo':               'DR Congo',
    'Congo DR':               'DR Congo',
    'Cape Verde':             'Cabo Verde',
    'Cape Verde Islands':     'Cabo Verde',
    'Türkiye':                'Turkey',
    'Turkiye':                'Turkey',
    'United States':          'USA',
}

def espn_to_index_name(name):
    return ESPN_NAME_MAP.get(name, name)

def fetch_espn():
    """Fetch today ±2 days to catch games in all timezones."""
    pdt = timezone(timedelta(hours=-7))
    today = datetime.now(pdt)
    all_games = []
    seen = set()
    for offset in range(-1, 3):
        d = today + timedelta(days=offset)
        url = ESPN_URL + '?dates=' + d.strftime('%Y%m%d')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode('utf-8'))
            for e in data.get('events', []):
                eid = e.get('id', e.get('name', ''))
                if eid in seen:
                    continue
                seen.add(eid)
                all_games.append(e)
        except Exception:
            pass
    return all_games

def parse_espn(events):
    games = []
    for e in events:
        comp  = e['competitions'][0]
        st    = comp['status']['type']
        teams = comp['competitors']
        home  = next(t for t in teams if t['homeAway'] == 'home')
        away  = next(t for t in teams if t['homeAway'] == 'away')
        hs    = home.get('score', '')
        as_   = away.get('score', '')
        games.append({
            'home':      espn_to_index_name(home['team']['displayName']),
            'away':      espn_to_index_name(away['team']['displayName']),
            'hscore':    int(hs)  if str(hs).isdigit()  else None,
            'ascore':    int(as_) if str(as_).isdigit() else None,
            'status':    st['description'],
            'completed': st.get('completed', False),
            'live':      st['state'] == 'in',
        })
    return games

# ── Line finders ──────────────────────────────────────────────────────────────

def find_group_line(content, home, away):
    pattern = re.compile(
        r"(\{ group: '([A-Z])', md: (\d+), date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def find_knockout_line(content, home, away):
    """Matches KO lines with or without matchId field."""
    pattern = re.compile(
        r"(\{ round: '([^']+)',(?:\s*matchId: \d+,)? date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def find_game_line(content, home, away):
    m = find_group_line(content, home, away)
    if m:
        return m, 'group'
    m = find_knockout_line(content, home, away)
    if m:
        return m, 'knockout'
    return None, None

def build_group_replacement(group, md, date, home, hscore, away, ascore, completed, live):
    if completed:
        return "{ group: '%s', md: %d, date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: true }," % (
            group, md, date, home, hscore, away, ascore)
    elif live:
        return "{ group: '%s', md: %d, date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: false, live: true }," % (
            group, md, date, home, hscore, away, ascore)
    return None

def build_knockout_replacement(round_name, date, home, hscore, away, ascore, completed, live):
    if completed:
        return "{ round: '%s', date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: true }," % (
            round_name, date, home, hscore, away, ascore)
    elif live:
        return "{ round: '%s', date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: false, live: true }," % (
            round_name, date, home, hscore, away, ascore)
    return None

def build_knockout_replacement_with_id(round_name, match_id, date, home, hscore, away, ascore, completed, live):
    """Preserve matchId field — required so r32W(id) lookup in bracket tab keeps working."""
    if completed:
        return "{ round: '%s', matchId: %s,  date:'%s', home:'%s', hscore:%d,    away:'%s',         ascore:%d,    played:true }," % (
            round_name, match_id, date, home, hscore, away, ascore)
    elif live:
        return "{ round: '%s', matchId: %s,  date:'%s', home:'%s', hscore:%d,    away:'%s',         ascore:%d,    played:false, live:true }," % (
            round_name, match_id, date, home, hscore, away, ascore)
    return None

# ── Mirror sync: update ALL KO arrays in one pass ────────────────────────────

def sync_all_ko_mirrors(content, home, away, round_name, date, hscore, ascore, completed, live, log):
    """
    Sync every KO array in index.html for this match:
      1. KO_MATCHES (main array) — already patched by caller, skip re-patching
      2. r32All array (r32schedule tab) — no matchId field
      3. bracket matchId array (knockout tab) — has matchId field, different spacing

    Uses full-content regex for each pattern — no substring offsets, no missed arrays.
    """
    base_line = build_knockout_replacement(round_name, date, home, hscore, away, ascore, completed, live)
    if not base_line:
        return content

    synced = []

    # ── Mirror 2: r32All — tight spacing, no matchId ─────────────────────────
    # Pattern: { round: 'r32', date:'Jun 28', home:'South Africa', hscore:0, away:'Canada', ascore:X, played:... },
    r32all_pattern = re.compile(
        r"\{ round: '" + re.escape(round_name) + r"', date:'" + re.escape(date) + r"', home:'" +
        re.escape(home) + r"', hscore:[^,]+, away:'" + re.escape(away) +
        r"', ascore:[^,]+, played:(?:true|false)(?:, live:true)? \},"
    )
    # Build replacement preserving tight spacing style
    if completed:
        r32all_new = "{ round: '%s', date:'%s', home:'%s', hscore:%d, away:'%s', ascore:%d, played:true }," % (
            round_name, date, home, hscore, away, ascore)
    elif live:
        r32all_new = "{ round: '%s', date:'%s', home:'%s', hscore:%d, away:'%s', ascore:%d, played:false, live:true }," % (
            round_name, date, home, hscore, away, ascore)
    else:
        r32all_new = None

    if r32all_new:
        new_content, n = r32all_pattern.subn(r32all_new, content)
        if n > 0:
            content = new_content
            synced.append('r32All (%d occurrence(s))' % n)
        else:
            log.append('MIRROR WARN: r32All pattern not matched for %s vs %s' % (home, away))

    # ── Mirror 3: matchId bracket array — has matchId field, wide spacing ────
    # Pattern: { round: 'r32', matchId: 0,  date:'Jun 28', home:'South Africa', hscore:0,    away:'Canada',         ascore:X,    played:... },
    matchid_pattern = re.compile(
        r"\{ round: '" + re.escape(round_name) + r"', matchId: (\d+),\s+date:'[^']+',\s+home:'" +
        re.escape(home) + r"',\s+hscore:[^,]+,\s+away:'" + re.escape(away) +
        r"',\s+ascore:[^,]+,\s+played:(?:true|false)(?:, live:true)? \},"
    )
    match = matchid_pattern.search(content)
    if match:
        mid = match.group(1)
        if completed:
            matchid_new = "{ round: '%s', matchId: %s,  date:'%s', home:'%s', hscore:%d,    away:'%s',         ascore:%d,    played:true }," % (
                round_name, mid, date, home, hscore, away, ascore)
        elif live:
            matchid_new = "{ round: '%s', matchId: %s,  date:'%s', home:'%s', hscore:%d,    away:'%s',         ascore:%d,    played:false, live:true }," % (
                round_name, mid, date, home, hscore, away, ascore)
        else:
            matchid_new = None

        if matchid_new:
            content = content[:match.start()] + matchid_new + content[match.end():]
            synced.append('matchId bracket array (matchId=%s)' % mid)
    else:
        log.append('MIRROR WARN: matchId pattern not matched for %s vs %s' % (home, away))

    if synced:
        log.append('SYNCED mirrors: %s — %s vs %s' % (', '.join(synced), home, away))

    return content

# ── Auto-advancement: set winner's flag in teamStatuses ──────────────────────

def apply_advancement_flag(content, winner, round_name, log):
    flag = ROUND_FLAG_MAP.get(round_name)
    if flag is None:
        return content

    existing = re.search(r'useState\(\{ (.+?) \}\)', content)
    if not existing:
        log.append('WARNING: useState block not found — cannot set %s flag for %s' % (flag, winner))
        return content

    ts_str = existing.group(1)
    team_match = re.search(r'"%s":\s*\{([^}]+)\}' % re.escape(winner), ts_str)
    if team_match and flag + ': true' in team_match.group(1):
        log.append('FLAG ALREADY SET: %s %s: true (skipping)' % (winner, flag))
        return content

    if team_match:
        old_entry = team_match.group(0)
        new_entry = old_entry.rstrip('}').rstrip() + ', %s: true }' % flag
        ts_str = ts_str[:team_match.start()] + new_entry + ts_str[team_match.end():]
    else:
        ts_str = ts_str + ', "%s": { %s: true }' % (winner, flag)

    new_useState = 'useState({ %s })' % ts_str
    content = re.sub(r'useState\(\{ .+? \}\)', new_useState, content)
    log.append('AUTO-ADVANCED: %s → %s: true' % (winner, flag))
    return content

def apply_final_flags(content, champion, runner_up, log):
    for team, flag in [(champion, 'champion'), (runner_up, 'runnerUp')]:
        existing = re.search(r'useState\(\{ (.+?) \}\)', content)
        if not existing:
            break
        ts_str = existing.group(1)
        team_match = re.search(r'"%s":\s*\{([^}]+)\}' % re.escape(team), ts_str)
        if team_match and flag + ': true' in team_match.group(1):
            continue
        if team_match:
            old_entry = team_match.group(0)
            new_entry = old_entry.rstrip('}').rstrip() + ', %s: true }' % flag
            ts_str = ts_str[:team_match.start()] + new_entry + ts_str[team_match.end():]
        else:
            ts_str = ts_str + ', "%s": { %s: true }' % (team, flag)
        new_useState = 'useState({ %s })' % ts_str
        content = re.sub(r'useState\(\{ .+? \}\)', new_useState, content)
        log.append('AUTO-ADVANCED: %s → %s: true' % (team, flag))
    return content

# ── teamStatuses rebuild ──────────────────────────────────────────────────────

def rebuild_team_statuses(content):
    wins, draws = {}, {}
    for line in content.split('\n'):
        if 'played: true' not in line:
            continue
        if "group: '" not in line:
            continue
        m = re.search(r"home: '([^']+)', hscore: ([0-9]+), away: '([^']+)', ascore: ([0-9]+)", line)
        if not m:
            continue
        h, hs, a, as_ = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        if hs > as_:
            wins[h]  = wins.get(h, 0) + 1
        elif hs < as_:
            wins[a]  = wins.get(a, 0) + 1
        else:
            draws[h] = draws.get(h, 0) + 1
            draws[a] = draws.get(a, 0) + 1

    all_teams = sorted(set(wins) | set(draws))
    entries = []
    for team in all_teams:
        w = wins.get(team, 0)
        d = draws.get(team, 0)
        parts = []
        if w: parts.append('groupWins: %d' % w)
        if d: parts.append('groupDraws: %d' % d)
        entries.append('"%s": { %s }' % (team, ', '.join(parts)))

    new_ts_body = ', '.join(entries)
    new_ts = 'useState({ %s })' % new_ts_body

    # Preserve KO flags from existing useState
    existing = re.search(r'useState\(\{ (.+?) \}\)', content)
    if existing:
        existing_str = existing.group(1)
        ko_flags = ['roundOf32', 'roundOf16', 'quarterFinal', 'semiFinal', 'runnerUp', 'champion', 'eliminated']
        for team_match in re.finditer(r'"([^"]+)":\s*\{([^}]+)\}', existing_str):
            tname = team_match.group(1)
            tdata = team_match.group(2)
            has_ko = any(f in tdata for f in ko_flags)
            if not has_ko:
                continue
            ko_parts = [f + ': true' for f in ko_flags if f + ': true' in tdata]
            if ko_parts:
                team_pattern = re.compile(r'"%s": \{ ([^}]*) \}' % re.escape(tname))
                m2 = team_pattern.search(new_ts)
                if m2:
                    merged = m2.group(1).rstrip(', ') + ', ' + ', '.join(ko_parts)
                    new_ts = new_ts[:m2.start()] + '"%s": { %s }' % (tname, merged) + new_ts[m2.end():]
                else:
                    insert = ', "%s": { %s }' % (tname, ', '.join(ko_parts))
                    new_ts = new_ts[:-1] + insert + '}'

    updated = re.sub(r'useState\(\{ .+? \}\)', new_ts, content)
    return updated, wins, draws

# ── Main run loop ─────────────────────────────────────────────────────────────

def run(dry_run=False):
    log = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    log.append('=== ESPN auto-update v5.1: %s ===' % now)

    # Always pull latest before reading — prevents overwriting manual fixes
    try:
        pull = subprocess.run(['git', 'pull', '--rebase'], cwd=REPO_DIR, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        log.append('git pull: ' + (pull.stdout or '').strip() + ' ' + (pull.stderr or '').strip())
    except Exception as ex:
        log.append('git pull ERROR: %s' % ex)

    try:
        events = fetch_espn()
        games  = parse_espn(events)
        log.append('ESPN returned %d games.' % len(games))
    except Exception as ex:
        log.append('ERROR fetching ESPN: %s' % ex)
        print('\n'.join(log))
        return

    content = open(INDEX, encoding='utf-8').read()
    changes = []

    for g in games:
        home, away      = g['home'], g['away']
        hscore, ascore  = g['hscore'], g['ascore']
        completed, live = g['completed'], g['live']

        if hscore is None or ascore is None:
            continue

        m, fmt = find_game_line(content, home, away)
        if not m:
            m, fmt = find_game_line(content, away, home)
            if m:
                home, away     = away, home
                hscore, ascore = ascore, hscore

        if not m:
            log.append('NOT FOUND: %s vs %s' % (home, away))
            continue

        if fmt == 'group':
            group = m.group(2)
            md    = int(m.group(3))
            date  = m.group(4)
            new_line = build_group_replacement(group, md, date, home, hscore, away, ascore, completed, live)
        else:
            round_name = m.group(2)
            date       = m.group(3)
            # Check if matched line has a matchId field — preserve it if so
            import re as _re
            mid_search = _re.search(r'matchId: (\d+)', m.group(1))
            if mid_search:
                new_line = build_knockout_replacement_with_id(
                    round_name, mid_search.group(1), date, home, hscore, away, ascore, completed, live)
            else:
                new_line = build_knockout_replacement(round_name, date, home, hscore, away, ascore, completed, live)

        if not new_line:
            log.append('SCHEDULED (skip): %s vs %s' % (home, away))
            continue

        if m.group(1) == new_line:
            log.append('NO CHANGE: %s %d-%d %s' % (home, hscore, ascore, away))
            continue

        label = '%s %d-%d %s [%s]' % (home, hscore, ascore, away, g['status'])
        log.append('UPDATING: ' + label)
        changes.append(label)

        if not dry_run:
            # Patch the primary KO_MATCHES line
            content = content[:m.start(1)] + new_line + content[m.end(1):]

            # Sync ALL mirror arrays for knockout matches
            if fmt == 'knockout':
                content = sync_all_ko_mirrors(
                    content, home, away, round_name, date,
                    hscore, ascore, completed, live, log
                )

            # Auto-advancement on completion
            if fmt == 'knockout' and completed:
                if hscore != ascore:
                    winner = home if hscore > ascore else away
                    if round_name == 'final':
                        loser = away if hscore > ascore else home
                        content = apply_final_flags(content, winner, loser, log)
                    else:
                        content = apply_advancement_flag(content, winner, round_name, log)
                else:
                    warn_msg = (
                        '\n' +
                        '=' * 60 + '\n' +
                        '  ⚠️  NEEDS_WINNER_CONFIRM  ⚠️\n' +
                        '  Match: %s %d-%d %s\n' % (home, hscore, ascore, away) +
                        '  Tied at FT — penalties or ET winner not on ESPN.\n' +
                        '  ACTION: patch index.html manually with penWinner field.\n' +
                        '=' * 60
                    )
                    log.append(warn_msg)
                    print(warn_msg)
                    # Write a persistent flag file so it's easy to spot
                    import os
                    flag_path = os.path.join(REPO_DIR, 'PENDING_WINNER.txt')
                    with open(flag_path, 'a', encoding='utf-8') as wf:
                        from datetime import datetime as _dt
                        wf.write('[%s] %s %d-%d %s — set penWinner manually\n' % (
                            _dt.now().strftime('%Y-%m-%d %H:%M'), home, hscore, ascore, away))
                    log.append('FLAG FILE written: PENDING_WINNER.txt')

    if changes and not dry_run:
        content, wins, draws = rebuild_team_statuses(content)
        total = sum(wins.values()) + sum(draws.values())
        log.append('teamStatuses rebuilt (KO flags preserved). Group games counted: %d' % total)

        open(INDEX, 'w', encoding='utf-8').write(content)
        msg = 'auto: ' + ' | '.join(changes)
        subprocess.run(['git', 'add', 'index.html'], cwd=REPO_DIR, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(['git', 'commit', '-m', msg],  cwd=REPO_DIR, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(['git', 'push'],               cwd=REPO_DIR, creationflags=subprocess.CREATE_NO_WINDOW)
        log.append('PUSHED.')
    elif not changes:
        log.append('Nothing to update.')

    result = '\n'.join(log)
    print(result)
    # Always write to update_log.txt regardless of how script is invoked
    import os as _os
    log_path = _os.path.join(REPO_DIR, 'update_log.txt')
    with open(log_path, 'a', encoding='utf-8') as _lf:
        _lf.write(result + '\n')
    return result

if __name__ == '__main__':
    import sys
    dry = '--dry' in sys.argv
    run(dry_run=dry)
