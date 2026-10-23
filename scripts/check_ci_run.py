import urllib.request
import json

url = 'https://api.github.com/repos/tanmay17-gif/Sidekick/actions/runs/39855997528/jobs'
req = urllib.request.Request(url, headers={'User-Agent': 'Python'})
res = json.loads(urllib.request.urlopen(req).read().decode())
for j in res.get('jobs', []):
    print("JOB:", j['name'], "->", j['status'], j['conclusion'])
    for s in j.get('steps', []):
        print("  STEP:", s['name'], "->", s['status'], s['conclusion'])
