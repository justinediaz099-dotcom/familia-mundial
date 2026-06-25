#!/usr/bin/env python3
"""One-time rebuild of teamStatuses from played: true match data."""
import re, sys
sys.path.insert(0, '.')
from auto_update import rebuild_team_statuses

INDEX = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'

content = open(INDEX, encoding='utf-8').read()
updated, wins, draws = rebuild_team_statuses(content)

# Show diff summary
all_teams = sorted(set(wins) | set(draws))
print('Rebuilt teamStatuses from played games:')
for t in all_teams:
    w = wins.get(t, 0)
    d = draws.get(t, 0)
    print('  %-28s  W=%d D=%d  (%dpts)' % (t, w, d, w*3+d))

if '--apply' in sys.argv:
    open(INDEX, 'w', encoding='utf-8').write(updated)
    print('\nWritten to index.html.')
else:
    print('\n(dry run — pass --apply to write)')
