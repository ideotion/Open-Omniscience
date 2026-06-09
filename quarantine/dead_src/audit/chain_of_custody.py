"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
# Chain of Custody Module for Open-Omniscience Pillar 4
# Log every data interaction for legal admissibility

import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


class ChainOfCustody:
    def __init__(self, db_path='chain_of_custody.db'):
        self.db_path = db_path
        self.connection = sqlite3.connect(db_path)
        self._initialize_database()

    def _initialize_database(self):
        cursor = self.connection.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS custody_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_id TEXT NOT NULL,
            action TEXT NOT NULL,
            user_id TEXT,
            timestamp TEXT NOT NULL,
            metadata_json TEXT
        )""")
        self.connection.commit()

    def log_action(self, data_id, action, user_id=None, metadata=None):
        cursor = self.connection.cursor()
        metadata_json = json.dumps(metadata or {})
        timestamp = datetime.now(timezone.utc).isoformat()
        cursor.execute("INSERT INTO custody_log (data_id, action, user_id, timestamp, metadata_json) VALUES (?, ?, ?, ?, ?)",
                      (data_id, action, user_id, timestamp, metadata_json))
        self.connection.commit()
        return cursor.lastrowid

    def get_custody_chain(self, data_id):
        cursor = self.connection.cursor()
        cursor.execute("SELECT action, user_id, timestamp, metadata_json FROM custody_log WHERE data_id = ? ORDER BY timestamp ASC", (data_id,))
        chain = []
        for row in cursor.fetchall():
            action, user_id, timestamp, metadata_json = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            chain.append({
                'action': action,
                'user_id': user_id,
                'timestamp': timestamp,
                'metadata': metadata
            })
        return chain

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
