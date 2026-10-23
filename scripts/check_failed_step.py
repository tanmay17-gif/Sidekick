import urllib.request
import json

url = 'https://api.github.com/repos/tanmay17-gif/Sidekick/actions/runs/39855997528/jobs'
req = urllib.request.Request(url, headers={'User-Agent': 'Python'})
res = json.loads(urllib.request.urlopen(req).read().decode())
for j in res.get('jobs', []):
    if j['name'] == 'python packaging, contracts and test suite':
        for s in j.get('steps', []):
            if s['conclusion'] == 'failure':
                print("FAILED STEP OBJECT:", json.dumps(s, indent=2))
