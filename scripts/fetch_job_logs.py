import urllib.request
import json

url = 'https://api.github.com/repos/tanmay17-gif/Sidekick/actions/runs/39855997528/jobs'
req = urllib.request.Request(url, headers={'User-Agent': 'Python'})
res = json.loads(urllib.request.urlopen(req).read().decode())
for j in res.get('jobs', []):
    if j['name'] == 'python packaging, contracts and test suite':
        print("JOB ID:", j['id'])
        log_url = f"https://api.github.com/repos/tanmay17-gif/Sidekick/actions/jobs/{j['id']}/logs"
        try:
            req_log = urllib.request.Request(log_url, headers={'User-Agent': 'Python'})
            with urllib.request.urlopen(req_log) as resp:
                log_text = resp.read().decode('utf-8', errors='replace')
                print("LOG LENGTH:", len(log_text))
                # print last 100 lines
                lines = log_text.splitlines()
                for line in lines[-80:]:
                    print(line)
        except Exception as e:
            print("Could not fetch log:", e)
