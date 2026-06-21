# check_points.py — derives points directly from played games in index.html

import re

content = open('index.html', encoding='utf-8').read()

# Extract all played games
wins = {}
draws = {}

for line in content.split('\n'):
    if 'played: true' not in line:
        continue
    m = re.search(r"home: '([^']+)', hscore: (\d+), away: '([^']+)', ascore: (\d+)", line)
    if not m:
        continue
    home, hs, away, as_ = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    if hs > as_:
        wins[home] = wins.get(home, 0) + 1
    elif hs < as_:
        wins[away] = wins.get(away, 0) + 1
    else:
        draws[home] = draws.get(home, 0) + 1
        draws[away] = draws.get(away, 0) + 1

roster = [
    ('Socorro',     ['Colombia', 'Portugal', 'Egypt']),
    ('Mayra',       ['Czechia', 'Switzerland', 'Cura\u00e7ao']),
    ('Fifiz',       ['South Korea', 'Bosnia & Herz.', 'Morocco']),
    ('Crystal',     ['Iraq', 'Australia', 'Algeria']),
    ('Carmen',      ['Haiti', 'Japan', 'Belgium']),
    ('Evelyn',      ['DR Congo', 'England', 'Argentina']),
    ('Yvette',      ['Mexico', 'South Africa', 'Ecuador']),
    ('Chilo (Tio)', ['Ivory Coast', 'Uzbekistan', 'Canada']),
    ('Ivy',         ['Jordan', 'Senegal', 'Cabo Verde']),
    ('Jose',        ['France', 'Iran', 'Germany']),
    ('Grampa',      ['Scotland', 'New Zealand', 'Saudi Arabia']),
    ('Chapetes',    ['Norway', 'Spain', 'Netherlands']),
    ('Pedro',       ['Croatia', 'Ghana', 'Qatar']),
    ('Checha',      ['Austria', 'Sweden', 'Uruguay']),
    ('Justin',      ['Panama', 'Paraguay', 'Brazil']),
    ('Andrew',      ['USA', 'Turkey', 'Tunisia']),
]

scores = []
for name, teams in roster:
    pts = sum(wins.get(t, 0) * 3 + draws.get(t, 0) for t in teams)
    detail = ' | '.join('%s:%d' % (t, wins.get(t, 0) * 3 + draws.get(t, 0)) for t in teams)
    scores.append((pts, name, detail))

scores.sort(key=lambda x: -x[0])
for i, (pts, name, detail) in enumerate(scores, 1):
    print('%2d. %-14s %3dpts  [%s]' % (i, name, pts, detail))
