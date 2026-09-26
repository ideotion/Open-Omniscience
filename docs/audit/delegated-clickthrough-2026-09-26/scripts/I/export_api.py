"""Scratch: unlock the SOURCE instance and run ONE export through the same endpoints the
Export dialog calls (export-folder -> v2/volumes/start -> poll -> export-summary)."""
import json, sys, time, urllib.request
port, parent, bpass = sys.argv[1], sys.argv[2], sys.argv[3]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    with op.open(req, timeout=120) as r:
        return json.loads(r.read() or b"null")
ls = call("GET", "/api/system/lock-state")
if ls.get("locked"):
    print("unlock:", call("POST", "/api/system/unlock", {"passphrase": "walk-pass-2026"}).get("unlocked"))
    time.sleep(3)
made = call("POST", "/api/backup/export-folder", {"parent": parent})
dest = made["dir"]; print("dest", dest)
print(call("POST", "/api/backup/v2/volumes/start", {"dest": dest, "passphrase": bpass, "verify_after_write": True}).get("state"))
while True:
    st = call("GET", "/api/backup/v2/volumes/status")
    if st.get("state") not in ("running", "starting", "queued"):
        break
    time.sleep(1)
print("final", st.get("state"), st.get("mode"), st.get("error"))
w = call("POST", "/api/backup/export-summary", {"dir": dest})
print("summary", w.get("summary_path"))
