"""Find all team name variants in game entries and teamStatuses"""
import re
content = open('C:/Users/diazjuso/Desktop/familia-mundial/index.html', encoding='utf-8').read()

# Extract all home/away names from game entries
game_pat = re.compile(r"home: '([^']+)', hscore: [^,]+, away: '([^']+)'")
names = set()
for m in game_pat.finditer(content):
    names.add(m.group(1))
    names.add(m.group(2))

# Extract all team names from roster array
roster_pat = re.compile(r'{ name: "([^"]+)"')
roster = set(m.group(1) for m in roster_pat.finditer(content))

lines = []
lines.append('=== Teams in game entries (%d) ===' % len(names))
for n in sorted(names): lines.append('  ' + n)

lines.append('\n=== Teams in roster array (%d) ===' % len(roster))
for n in sorted(roster): lines.append('  ' + n)

lines.append('\n=== In games but NOT in roster ===')
for n in sorted(names - roster): lines.append('  MISSING: ' + n)

lines.append('\n=== In roster but NOT in games ===')
for n in sorted(roster - names): lines.append('  UNUSED: ' + n)

open('C:/Users/diazjuso/Desktop/familia-mundial/check_names_out.txt', 'w', encoding='utf-8').write('\n'.join(lines))
