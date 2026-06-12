import re

path = 'C:/Users/diazjuso/Desktop/familia-mundial/index.html'
content = open(path, encoding='utf-8').read()
out = open('C:/Users/diazjuso/Desktop/familia-mundial/check_output.txt', 'w', encoding='utf-8')

# --- Player Count Check ---
players = re.findall(r'\{ id: \d+,\s+name:', content)
player_count = len(players)
out.write(f"player_count: {player_count} {'OK' if player_count == 16 else '*** FAIL — expected 16 ***'}\n")

# --- Extract player names for audit ---
names = re.findall(r'name:\s*"([^"]+)",\s*emoji:', content)
for i, n in enumerate(names):
    out.write(f"  {i+1}. {n}\n")

out.write('\n')

# --- Standard checks ---
checks = {
    'Mexico_win':       '"Mexico": { groupWins: 1 }' in content,
    'SouthKorea_win':   '"South Korea": { groupWins: 1 }' in content,
    'no_live_flag':     'live: true' not in content,
    'keyframes':        '@keyframes livePulse' in content,
    'jose_present':     '"Jose"' in content,
}
for k, v in checks.items():
    out.write(f"{k}: {'OK' if v else '*** MISSING ***'}\n")

out.write(f"\nTotal lines: {len(content.splitlines())}\n")
out.close()
print("verify done")
