#!/usr/bin/env python3
"""
familia-mundial auto-updater
Polls ESPN scoreboard, detects score/status changes vs index.html, patches and pushes.
teamStatuses is rebuilt from scratch after every update (never incremented) to stay in sync.
"""

import json, re, subprocess, urllib.request
from datetime import datetime

ESPN_URL = 'https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard'
INDEX    = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'
REPO_DIR = 'C:/Users/diazjuso/Desktop/familia-mundial'

# ESPN displayName → index.html team name mapping
ESPN_NAME_MAP = {
    'Bosnia and Herzegovina': 'Bosnia & Herz.',
    'Bosnia-Herzegovina':     'Bosnia & Herz.',
    'Curacao':                'Cura\u00e7ao',
    'DR Congo':               'DR Congo',
    'Congo DR':               'DR Congo',
    'Cape Verde':             'Cabo Verde',
    'Cape Verde Islands':     'Cabo Verde',
}

def espn_to_index_name(name):
    return ESPN_NAME_MAP.get(name, name)

def fetch_espn():
    req = urllib.request.Request(ESPN_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))

def parse_espn(data):
    games = []
    for e in data.get('events', []):
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
            'hscore':    int(hs)  if hs.isdigit()  else None,
            'ascore':    int(as_) if as_.isdigit() else None,
            'status':    st['description'],
            'completed': st.get('completed', False),
            'live':      st['state'] == 'in',
        })
    return games

def find_game_line(content, home, away):
    """Find the exact line for home vs away, return match object or None."""
    pattern = re.compile(
        r"(\{ group: '([A-Z])', md: (\d+), date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def build_replacement(group, md, date, home, hscore, away, ascore, completed, live):
    if completed:
        return "{ group: '%s', md: %d, date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: true }," % (
            group, md, date, home, hscore, away, ascore)
    elif live:
        return "{ group: '%s', md: %d, date: '%s', home: '%s', hscore: %d, away: '%s', ascore: %d, played: false, live: true }," % (
            group, md, date, home, hscore, away, ascore)
    return None

def rebuild_team_statuses(content):
    """
    Derive teamStatuses entirely from played: true match data.
    Replaces the entire useState({ ... }) block — no incrementing, always in sync.
    """
    wins, draws = {}, {}
    for line in content.split('\n'):
        if 'played: true' not in line:
            continue
        m = re.search(r"home: '([^']+)', hscore: ([0-9]+), away: '([^']+)', ascore: ([0-9]+)", line)
        if not m:
            continue
        h, hs, a, as_ = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        if hs > as_:
            wins[h] = wins.get(h, 0) + 1
        elif hs < as_:
            wins[a] = wins.get(a, 0) + 1
        else:
            draws[h] = draws.get(h, 0) + 1
            draws[a] = draws.get(a, 0) + 1

    # Build new teamStatuses object entries
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

    # Replace the existing useState({ ... }) block
    updated = re.sub(r'useState\(\{ .+? \}\)', new_ts, content)
    return updated, wins, draws

def run(dry_run=False):
    log = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    log.append('=== ESPN auto-update: %s ===' % now)

    try:
        data = fetch_espn()
    except Exception as ex:
        log.append('ERROR fetching ESPN: %s' % ex)
        print('\n'.join(log))
        return

    games   = parse_espn(data)
    content = open(INDEX, encoding='utf-8').read()
    changes = []

    for g in games:
        home, away     = g['home'], g['away']
        hscore, ascore = g['hscore'], g['ascore']
        completed, live = g['completed'], g['live']

        if hscore is None or ascore is None:
            continue

        # Find exact match by home+away pair
        m = find_game_line(content, home, away)
        if not m:
            # Try flipped (ESPN sometimes uses different home/away)
            m = find_game_line(content, away, home)
            if m:
                home, away = away, home
                hscore, ascore = ascore, hscore

        if not m:
            log.append('NOT FOUND: %s vs %s' % (home, away))
            continue

        group = m.group(2)
        md    = int(m.group(3))
        date  = m.group(4)

        new_line = build_replacement(group, md, date, home, hscore, away, ascore, completed, live)
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

    if changes and not dry_run:
        # Rebuild teamStatuses from scratch after all match updates
        content, wins, draws = rebuild_team_statuses(content)
        log.append('teamStatuses rebuilt from %d played games.' % sum(wins.values()) + sum(draws.values()))

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
