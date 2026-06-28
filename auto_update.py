#!/usr/bin/env python3
"""
familia-mundial auto-updater v4.0
Polls ESPN scoreboard, detects score/status changes vs index.html, patches and pushes.
Handles both group stage (group/md) and knockout round (round) line formats.
teamStatuses is rebuilt from scratch after every update (never incremented).
"""

import json, re, subprocess, urllib.request
from datetime import datetime, timedelta, timezone

ESPN_URL = 'https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard'
INDEX    = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'
REPO_DIR = 'C:/Users/diazjuso/Desktop/familia-mundial'

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
    """Fetch today + next 2 days to catch games in all timezones."""
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

# ── Line finders — one for each format ───────────────────────────────────────

def find_group_line(content, home, away):
    """Matches:  { group: 'X', md: N, date: '...', home: '...', hscore: ..., away: '...', ascore: ..., played: bool },"""
    pattern = re.compile(
        r"(\{ group: '([A-Z])', md: (\d+), date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def find_knockout_line(content, home, away):
    """Matches:  { round: 'r32', date: '...', home: '...', hscore: ..., away: '...', ascore: ..., played: bool },"""
    pattern = re.compile(
        r"(\{ round: '([^']+)', date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def find_game_line(content, home, away):
    """Try group format first, then knockout format."""
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

# ── teamStatuses rebuild ──────────────────────────────────────────────────────

def rebuild_team_statuses(content):
    """
    Recompute groupWins/groupDraws from all played:true GROUP STAGE lines.
    Knockout advancement flags (roundOf32, quarterFinal, etc.) are set manually — never touched here.
    """
    wins, draws = {}, {}

    for line in content.split('\n'):
        if 'played: true' not in line:
            continue
        # Only count group stage lines (has 'group:' field)
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

    # Preserve any existing knockout flags (roundOf32, quarterFinal, etc.)
    # by merging them back in from the current useState block
    existing = re.search(r'useState\(\{ (.+?) \}\)', content)
    if existing:
        existing_str = existing.group(1)
        # Extract teams that have knockout flags
        ko_flags = ['roundOf32', 'quarterFinal', 'semiFinal', 'runnerUp', 'champion', 'eliminated']
        for team_match in re.finditer(r'"([^"]+)":\s*\{([^}]+)\}', existing_str):
            tname = team_match.group(1)
            tdata = team_match.group(2)
            has_ko = any(f in tdata for f in ko_flags)
            if not has_ko:
                continue
            # Merge KO flags into the new entry for this team
            ko_parts = []
            for flag in ko_flags:
                if flag + ': true' in tdata:
                    ko_parts.append('%s: true' % flag)
            if ko_parts:
                # Find and update this team's entry in new_ts
                team_pattern = re.compile(r'"%s": \{ ([^}]*) \}' % re.escape(tname))
                m2 = team_pattern.search(new_ts)
                if m2:
                    merged = m2.group(1).rstrip(', ') + ', ' + ', '.join(ko_parts)
                    new_ts = new_ts[:m2.start()] + '"%s": { %s }' % (tname, merged) + new_ts[m2.end():]
                else:
                    # Team only has KO flags (0 group wins/draws) — add them
                    insert = ', "%s": { %s }' % (tname, ', '.join(ko_parts))
                    new_ts = new_ts[:-1] + insert + '}'  # before closing )

    updated = re.sub(r'useState\(\{ .+? \}\)', new_ts, content)
    return updated, wins, draws

# ── Main run loop ─────────────────────────────────────────────────────────────

def run(dry_run=False):
    log = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    log.append('=== ESPN auto-update v4.0: %s ===' % now)

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
            # Try reversed
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
        else:  # knockout
            round_name = m.group(2)
            date       = m.group(3)
            new_line   = build_knockout_replacement(round_name, date, home, hscore, away, ascore, completed, live)

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
            content = content[:m.start(1)] + new_line + content[m.end(1):]
            # Also sync r32schedule tab's r32All array (mirror of KO_MATCHES)
            if fmt == 'knockout':
                # Build r32schedule line (no matchId field)
                r32sched_line = re.sub(r',?\s*matchId: \d+', '', new_line)
                m2, _ = find_game_line(content[content.find("tab === 'r32schedule'"):], home, away)
                if m2:
                    tab_offset = content.find("tab === 'r32schedule'")
                    abs_start = tab_offset + m2.start(1)
                    abs_end   = tab_offset + m2.end(1)
                    content = content[:abs_start] + r32sched_line + content[abs_end:]
                    log.append('SYNCED r32schedule: %s vs %s' % (home, away))

    if changes and not dry_run:
        content, wins, draws = rebuild_team_statuses(content)
        total = sum(wins.values()) + sum(draws.values())
        log.append('teamStatuses rebuilt from %d played group-stage games (KO flags preserved).' % total)

        open(INDEX, 'w', encoding='utf-8').write(content)
        msg = 'auto: ' + ' | '.join(changes)
        subprocess.run(['git', 'add', 'index.html'], cwd=REPO_DIR)
        subprocess.run(['git', 'commit', '-m', msg],  cwd=REPO_DIR)
        subprocess.run(['git', 'push'],               cwd=REPO_DIR)
        log.append('PUSHED.')
    elif not changes:
        log.append('Nothing to update.')

    result = '\n'.join(log)
    print(result)
    return result

if __name__ == '__main__':
    import sys
    dry = '--dry' in sys.argv
    run(dry_run=dry)
