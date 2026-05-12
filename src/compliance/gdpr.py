# GDPR Compliance Module for Open-Omniscience Pillar 4
# Anonymize PII locally and handle right to erasure

import json
import sqlite3
from datetime import datetime, timezone


class GDPRCompliance:
    PII_FIELDS = {
        'email', 'phone', 'address', 'ssn', 'password', 'name'
    }

    def __init__(self, db_path="gdpr_compliance.db"):
        self.db_path = db_path
        self.connection = sqlite3.connect(db_path)
        self._initialize_database()

    def _initialize_database(self):
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS pii_log (id INTEGER PRIMARY KEY AUTOINCREMENT, data_id TEXT NOT NULL, field_name TEXT NOT NULL, original_value TEXT, anonymized_value TEXT, action TEXT NOT NULL, timestamp TEXT NOT NULL)")
        self.connection.commit()

    def anonymize_pii(self, data, anonymize_fields=None):
        if anonymize_fields is None:
            anonymize_fields = self.PII_FIELDS
        
        anonymized_data = data.copy()
        for field in anonymize_fields:
            if field in anonymized_data:
                anonymized_data[field] = "[REDACTED]"
        return anonymized_data

    def right_to_erasure(self, data_id):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM pii_log WHERE data_id = ?", (data_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

def anonymize_pii(data):
    gdpr = GDPRCompliance()
    return gdpr.anonymize_pii(data)
