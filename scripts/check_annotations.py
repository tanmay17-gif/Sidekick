import urllib.request
import json

# Check runs annotations
url = 'https://api.github.com/repos/tanmay17-gif/Sidekick/commits/40e4958/check-runs'
req = urllib.request.Request(url, headers={'User-Agent': 'Python'})
res = json.loads(urllib.request.urlopen(req).read().decode())
for cr in res.get('check_runs', []):
    print("CHECK RUN:", cr['name'], "status:", cr['status'], "conclusion:", cr['conclusion'])
    if cr.get('output'):
        print("  TITLE:", cr['output'].get('title'))
        print("  SUMMARY:", cr['output'].get('summary'))
        print("  TEXT:", cr['output'].get('text')[:500] if cr['output'].get('text') else None)
