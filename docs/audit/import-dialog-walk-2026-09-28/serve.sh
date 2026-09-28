#!/bin/bash
# serve.sh <datadir> <port> <log>
cd /tmp/claude-0/imp/app
OO_DATA_DIR="$1" OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 nohup /tmp/claude-0/venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port "$2" > "$3" 2>&1 &
echo $! > "$3.pid"
