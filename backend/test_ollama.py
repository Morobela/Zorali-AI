import urllib.request, json, sys

url = "http://localhost:11434/api/chat"
payload = json.dumps({
    "model": "llama3.2:1b",
    "messages": [{"role": "user", "content": "Say hi in one sentence."}],
    "stream": False
}).encode()

try:
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read())
        print("SUCCESS:", data["message"]["content"])
except Exception as e:
    print("FAIL:", e)
