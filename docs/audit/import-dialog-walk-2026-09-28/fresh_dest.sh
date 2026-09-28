#!/bin/bash
# fresh_dest.sh <name> <port>: a destination install holding 3,000 of the first backup's articles
D=/tmp/claude-0/imp/dest-$1; L=/tmp/claude-0/imp/dest-$1.log
# Whatever holds the port goes, whichever run started it.
for pid in $(ps aux | grep "uvicorn src[.]api" | grep -- "--port $2" | awk '{print $2}'); do kill $pid; done
for i in $(seq 1 30); do curl -s -m 1 "http://127.0.0.1:$2/api/health" >/dev/null || break; sleep 1; done
rm -rf "$D"
cd /tmp/claude-0/imp/app && OO_DATA_DIR="$D" OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 TAG=a PYTHONPATH=. /tmp/claude-0/venv/bin/python ../seed_big.py 3000 >/dev/null 2>&1
/tmp/claude-0/imp/serve.sh "$D" "$2" "$L"
for i in $(seq 1 40); do curl -s -m 2 "http://127.0.0.1:$2/api/health" >/dev/null && break; sleep 1; done
# The server answering must be the one just started.
sleep 1; kill -0 $(cat "$L.pid") 2>/dev/null || { echo "dest $1: server did not stay up"; exit 1; }
echo "dest $1 on $2 (pid $(cat $L.pid))"
