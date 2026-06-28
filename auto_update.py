#!/usr/bin/env python3
"""
familia-mundial auto-updater v5.0
Polls ESPN scoreboard, detects score/status changes vs index.html, patches and pushes.
Handles both group stage (group/md) and knockout round (round) line formats.
teamStatuses is rebuilt from scratch after every update (never incremented).

v5.0: Auto-advancement flags
  - When a knockout match flips to played:true with a clear winner (hscore != ascore),
    automatically sets roundOf32/roundOf16/quarterFinal/semiFinal flag on the winning team
    in teamStatuses (useState block).
  - Tied scores (extra time / penalties) → logs a NEEDS_WINNER_CONFIRM warning,
    does NOT set any flag. Justin manually resolves with "X won on pens".
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
    # Final: winner = champion, loser = runnerUp — handled separately
    'final': None,
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
    pattern = re.compile(
        r"(\{ group: '([A-Z])', md: (\d+), date: '([^']+)', home: '" +
        re.escape(home) + r"', hscore: [^,]+, away: '" +
        re.escape(away) + r"', ascore: [^,]+, played: (?:true|false)(?:, live: true)? \},)"
    )
    return pattern.search(content)

def find_knockout_line(content, home, away):
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

# ── Auto-advancement: set winner's flag in teamStatuses ──────────────────────

def apply_advancement_flag(content, winner, round_name, log):
    """
    Sets the appropriate advancement flag on `winner` in the useState block.
    round_name: 'r32', 'r16', 'qf', 'sf', 'final'
    Final round: winner gets champion: true, logic handled by caller.
    Returns updated content.
    """
    flag = ROUND_FLAG_MAP.get(round_name)
    if flag is None:
        # Final round — handled separately
        return content

    existing = re.search(r'useState\(\{ (.+?) \}\)', content)
    if not existing:
        log.append('WARNING: useState block not found — cannot set %s flag for %s' % (flag, winner))
        return content

    ts_str = existing.group(1)

    # Check if flag already set for this team
    team_match = re.search(r'"%s":\s*\{([^}]+)\}' % re.escape(winner), ts_str)
    if team_match and flag + ': true' in team_match.group(1):
        log.append('FLAG ALREADY SET: %s %s: true (skipping)' % (winner, flag))
        return content

    if team_match:
        # Team exists in useState — append flag to their entry
        old_entry = team_match.group(0)
        new_entry = old_entry.rstrip('}').rstrip() + ', %s: true }' % flag
        ts_str = ts_str[:team_match.start()] + new_entry + ts_str[team_match.end():]
    else:
        # Team not yet in useState (0 group wins/draws) — add new entry
        ts_str = ts_str + ', "%s": { %s: true }' % (winner, flag)

    new_useState = 'useState({ %s })' % ts_str
    content = re.sub(r'useState\(\{ .+? \}\)', new_useState, content)
    log.append('AUTO-ADVANCED: %s → %s: true' % (winner, flag))
    return content

def apply_final_flags(content, champion, runner_up, log):
    """Sets champion: true on winner and runnerUp: true on loser."""
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
    """
    Recompute groupWins/groupDraws from all played:true GROUP STAGE lines.
    Knockout advancement flags are preserved from existing useState.
    """
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

    # Preserve knockout flags from existing useState
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
            ko_parts = []
            for flag in ko_flags:
                if flag + ': true' in tdata:
                    ko_parts.append('%s: true' % flag)
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
    log.append('=== ESPN auto-update v5.0: %s ===' % now)

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

            # Sync r32schedule tab mirror
            if fmt == 'knockout':
                r32sched_line = re.sub(r',?\s*matchId: \d+', '', new_line)
                m2, _ = find_game_line(content[content.find("tab === 'r32schedule'"):], home, away)
                if m2:
                    tab_offset = content.find("tab === 'r32schedule'")
                    abs_start = tab_offset + m2.start(1)
                    abs_end   = tab_offset + m2.end(1)
                    content = content[:abs_start] + r32sched_line + content[abs_end:]
                    log.append('SYNCED r32schedule: %s vs %s' % (home, away))

            # ── Auto-advancement on completion ────────────────────────────────
            if fmt == 'knockout' and completed:
                if hscore != ascore:
                    # Clear winner — auto-set advancement flag
                    winner = home if hscore > ascore else away
                    if round_name == 'final':
                        loser = away if hscore > ascore else home
                        content = apply_final_flags(content, winner, loser, log)
                    else:
                        content = apply_advancement_flag(content, winner, round_name, log)
                else:
                    # Tied at full time — could be pens, wait for manual confirm
                    log.append('NEEDS_WINNER_CONFIRM: %s %d-%d %s — tied at FT, set winner manually' % (
                        home, hscore, ascore, away))

    if changes and not dry_run:
        content, wins, draws = rebuild_team_statuses(content)
        total = sum(wins.values()) + sum(draws.values())
        log.append('teamStatuses rebuilt (KO flags preserved). Group games counted: %d' % total)

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
