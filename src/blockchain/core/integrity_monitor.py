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

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Integrity Monitor for Open-Omniscience Blockchain

Provides real-time monitoring, automated backups, and integrity checks
for single-user deployments.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import os
import time
import threading
import shutil
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
from enum import Enum

# Import for restore functionality
from .crypto_utils import AuditLogger


class IntegrityStatus(Enum):
    """Status of integrity checks."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class IntegrityCheckResult:
    """Result of an integrity check."""
    check_name: str
    status: IntegrityStatus
    message: str
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'check_name': self.check_name,
            'status': self.status.value,
            'message': self.message,
            'timestamp': self.timestamp,
            'details': self.details,
        }


@dataclass
class BackupInfo:
    """Information about a backup."""
    backup_path: str
    timestamp: float
    size_bytes: int
    hash_value: str  # SHA-256 hash of the backup
    status: str = "completed"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'backup_path': self.backup_path,
            'timestamp': self.timestamp,
            'size_bytes': self.size_bytes,
            'hash_value': self.hash_value,
            'status': self.status,
        }


class IntegrityMonitor:
    """
    Real-time integrity monitor for blockchain data.
    
    Performs periodic checks and maintains backups for single-user deployments.
    
    Features:
    - Periodic integrity verification
    - Automated backups
    - Alert system for issues
    - Self-healing capabilities
    """
    
    DEFAULT_CHECK_INTERVAL = 300  # 5 minutes
    DEFAULT_BACKUP_INTERVAL = 3600  # 1 hour
    DEFAULT_MAX_BACKUPS = 10
    
    def __init__(self,
                 hash_chain: Any,
                 check_interval: int = DEFAULT_CHECK_INTERVAL,
                 backup_interval: int = DEFAULT_BACKUP_INTERVAL,
                 backup_dir: str = "data/blockchain/backups",
                 max_backups: int = DEFAULT_MAX_BACKUPS,
                 alert_callback: Optional[Callable] = None):
        """
        Initialize integrity monitor.
        
        Args:
            hash_chain: LocalHashChain or EnhancedLocalHashChain instance
            check_interval: Seconds between integrity checks
            backup_interval: Seconds between backups
            backup_dir: Directory for backups
            max_backups: Maximum number of backups to keep
            alert_callback: Function to call when issues are detected
        """
        self.hash_chain = hash_chain
        self.check_interval = check_interval
        self.backup_interval = backup_interval
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
        self.alert_callback = alert_callback
        
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_check: float = 0
        self._last_backup: float = 0
        self._check_results: List[IntegrityCheckResult] = []
        self._backup_history: List[BackupInfo] = []
        self._lock = threading.Lock()
        
        # Create backup directory
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Load backup history
        self._load_backup_history()
    
    def _load_backup_history(self) -> None:
        """Load backup history from file."""
        history_file = self.backup_dir / "backup_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self._backup_history = [
                        BackupInfo(**item) for item in data
                    ]
            except (json.JSONDecodeError, KeyError):
                self._backup_history = []
    
    def _save_backup_history(self) -> None:
        """Save backup history to file."""
        history_file = self.backup_dir / "backup_history.json"
        with open(history_file, 'w') as f:
            json.dump(
                [b.to_dict() for b in self._backup_history],
                f,
                indent=2
            )
    
    def start(self) -> None:
        """Start the integrity monitor."""
        if self._running:
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
    
    def stop(self) -> None:
        """Stop the integrity monitor."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                current_time = time.time()
                
                # Run integrity checks
                if current_time - self._last_check >= self.check_interval:
                    self.run_integrity_checks()
                    self._last_check = current_time
                
                # Run backup
                if current_time - self._last_backup >= self.backup_interval:
                    self.create_backup()
                    self._last_backup = current_time
                
                # Sleep for a short interval
                time.sleep(1)
                
            except Exception as e:
                # Log error but continue monitoring
                self._log_error(f"Monitor error: {e}")
                time.sleep(5)
    
    def run_integrity_checks(self) -> List[IntegrityCheckResult]:
        """
        Run all integrity checks.
        
        Returns:
            List of check results
        """
        results = []
        
        # Check 1: Block chain integrity
        try:
            chain_ok = self.hash_chain.verify_block_chain_integrity()
            if chain_ok:
                results.append(IntegrityCheckResult(
                    check_name="block_chain_integrity",
                    status=IntegrityStatus.HEALTHY,
                    message="Block chain integrity verified"
                ))
            else:
                results.append(IntegrityCheckResult(
                    check_name="block_chain_integrity",
                    status=IntegrityStatus.CRITICAL,
                    message="Block chain integrity check failed",
                    details={"action": "Run verify_block_chain_integrity manually"}
                ))
                self._alert("CRITICAL: Block chain integrity check failed!")
        except Exception as e:
            results.append(IntegrityCheckResult(
                check_name="block_chain_integrity",
                status=IntegrityStatus.CRITICAL,
                message=f"Block chain integrity check error: {e}"
            ))
            self._alert(f"CRITICAL: Block chain integrity check error: {e}")
        
        # Check 2: Database file integrity
        try:
            db_ok = self._check_database_integrity()
            if db_ok:
                results.append(IntegrityCheckResult(
                    check_name="database_integrity",
                    status=IntegrityStatus.HEALTHY,
                    message="Database file integrity verified"
                ))
            else:
                results.append(IntegrityCheckResult(
                    check_name="database_integrity",
                    status=IntegrityStatus.CRITICAL,
                    message="Database file integrity check failed"
                ))
                self._alert("CRITICAL: Database file integrity check failed!")
        except Exception as e:
            results.append(IntegrityCheckResult(
                check_name="database_integrity",
                status=IntegrityStatus.WARNING,
                message=f"Database integrity check error: {e}"
            ))
        
        # Check 3: Backup existence
        try:
            backup_count = len(self._backup_history)
            if backup_count >= 1:
                results.append(IntegrityCheckResult(
                    check_name="backup_existence",
                    status=IntegrityStatus.HEALTHY,
                    message=f"{backup_count} backups available"
                ))
            else:
                results.append(IntegrityCheckResult(
                    check_name="backup_existence",
                    status=IntegrityStatus.WARNING,
                    message="No backups available",
                    details={"action": "Create manual backup"}
                ))
                self._alert("WARNING: No backups available")
        except Exception as e:
            results.append(IntegrityCheckResult(
                check_name="backup_existence",
                status=IntegrityStatus.WARNING,
                message=f"Backup check error: {e}"
            ))
        
        # Check 4: Storage space
        try:
            space_ok = self._check_storage_space()
            if space_ok:
                results.append(IntegrityCheckResult(
                    check_name="storage_space",
                    status=IntegrityStatus.HEALTHY,
                    message="Sufficient storage space available"
                ))
            else:
                results.append(IntegrityCheckResult(
                    check_name="storage_space",
                    status=IntegrityStatus.WARNING,
                    message="Low storage space",
                    details={"action": "Free up disk space"}
                ))
                self._alert("WARNING: Low storage space")
        except Exception as e:
            results.append(IntegrityCheckResult(
                check_name="storage_space",
                status=IntegrityStatus.WARNING,
                message=f"Storage check error: {e}"
            ))
        
        # Check 5: Chain of Custody (CoC) integrity
        try:
            coc_ok, coc_errors = self._check_coc_integrity()
            if coc_ok:
                results.append(IntegrityCheckResult(
                    check_name="chain_of_custody",
                    status=IntegrityStatus.HEALTHY,
                    message="Chain of Custody integrity verified"
                ))
            else:
                results.append(IntegrityCheckResult(
                    check_name="chain_of_custody",
                    status=IntegrityStatus.CRITICAL,
                    message="Chain of Custody integrity check failed",
                    details={"errors": coc_errors}
                ))
                self._alert("CRITICAL: Chain of Custody integrity check failed!")
        except Exception as e:
            results.append(IntegrityCheckResult(
                check_name="chain_of_custody",
                status=IntegrityStatus.WARNING,
                message=f"Chain of Custody check error: {e}"
            ))
        
        # Store results
        with self._lock:
            self._check_results = results
        
        return results
    
    def _check_coc_integrity(self) -> tuple:
        """
        Check Chain of Custody integrity.
        
        Returns:
            Tuple of (is_ok, errors) where:
            - is_ok: True if all CoC entries are valid
            - errors: List of error messages (empty if valid)
        """
        try:
            from .coc import get_coc_logger
            coc_logger = get_coc_logger()
            
            # Get all articles with CoC entries
            articles = coc_logger.get_all_articles()
            
            if not articles:
                # No CoC entries yet - this is OK
                return True, []
            
            # Check all articles
            all_errors = []
            for article_id in articles:
                is_valid, errors = coc_logger.verify_coc(article_id)
                if not is_valid:
                    all_errors.extend(errors)
            
            if all_errors:
                return False, all_errors
            else:
                return True, []
                
        except Exception as e:
            # If CoC is not initialized or other error, return warning
            return True, [f"CoC check skipped: {e}"]
    
    def _check_database_integrity(self) -> bool:
        """Check database file integrity."""
        db_path = Path(self.hash_chain.db_path)
        if not db_path.exists():
            return False
        
        # Check file size > 0
        if db_path.stat().st_size == 0:
            return False
        
        # Check file is readable
        try:
            with open(db_path, 'rb') as f:
                f.read(1)
        except:
            return False
        
        return True
    
    def _check_storage_space(self) -> bool:
        """Check if there's sufficient storage space."""
        try:
            # Get disk usage
            total, used, free = shutil.disk_usage("/")
            # Require at least 100MB free
            return free > 100 * 1024 * 1024
        except:
            return True  # If we can't check, assume OK
    
    def create_backup(self, force: bool = False) -> Optional[BackupInfo]:
        """
        Create a backup of the blockchain data.
        
        Args:
            force: Force backup even if interval hasn't elapsed
            
        Returns:
            BackupInfo if backup was created, None otherwise
        """
        if not force and time.time() - self._last_backup < self.backup_interval:
            return None
        
        try:
            # Create backup directory with timestamp
            timestamp = time.time()
            timestamp_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
            backup_dir = self.backup_dir / f"backup_{timestamp_str}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # For SQLite in WAL mode, we need to ensure all data is flushed
            # We do this by checkpointing the WAL file
            if self.hash_chain.connection:
                try:
                    self.hash_chain.connection.execute("PRAGMA wal_checkpoint(FULL)")
                except:
                    pass
            
            # Copy database file and WAL files
            db_path = Path(self.hash_chain.db_path)
            if db_path.exists():
                # Copy main database file
                backup_db = backup_dir / db_path.name
                shutil.copy2(db_path, backup_db)
                
                # Copy WAL file if it exists
                wal_file = Path(str(db_path) + "-wal")
                if wal_file.exists():
                    shutil.copy2(wal_file, backup_dir / wal_file.name)
                
                # Copy SHM file if it exists
                shm_file = Path(str(db_path) + "-shm")
                if shm_file.exists():
                    shutil.copy2(shm_file, backup_dir / shm_file.name)
            
            # Copy audit log if it exists (use the chain's audit logger path)
            if hasattr(self.hash_chain, 'audit_logger'):
                audit_log_path = Path(self.hash_chain.audit_logger.log_path)
                if audit_log_path.exists():
                    shutil.copy2(audit_log_path, backup_dir / audit_log_path.name)
            
            # Copy Chain of Custody database if it exists
            try:
                from .coc import get_coc_logger
                coc_logger = get_coc_logger()
                coc_db_path = Path(coc_logger.db_path)
                if coc_db_path.exists():
                    # Checkpoint WAL if in WAL mode
                    if coc_logger._conn:
                        try:
                            coc_logger._conn.execute("PRAGMA wal_checkpoint(FULL)")
                        except:
                            pass
                    # Copy CoC database and WAL files
                    shutil.copy2(coc_db_path, backup_dir / coc_db_path.name)
                    
                    coc_wal_file = Path(str(coc_db_path) + "-wal")
                    if coc_wal_file.exists():
                        shutil.copy2(coc_wal_file, backup_dir / coc_wal_file.name)
                    
                    coc_shm_file = Path(str(coc_db_path) + "-shm")
                    if coc_shm_file.exists():
                        shutil.copy2(coc_shm_file, backup_dir / coc_shm_file.name)
            except Exception:
                # CoC not initialized or other error - skip
                pass
            
            # Copy config if it exists
            config_file = Path("configs/blockchain.yml")
            if config_file.exists():
                shutil.copy2(config_file, backup_dir / config_file.name)
            
            # Compute backup hash
            backup_hash = self._compute_backup_hash(backup_dir)
            
            # Get backup size
            backup_size = sum(
                f.stat().st_size for f in backup_dir.rglob('*') if f.is_file()
            )
            
            # Create backup info
            backup_info = BackupInfo(
                backup_path=str(backup_dir),
                timestamp=timestamp,
                size_bytes=backup_size,
                hash_value=backup_hash,
                status="completed"
            )
            
            # Add to history
            with self._lock:
                self._backup_history.append(backup_info)
                # Keep only max_backups
                if len(self._backup_history) > self.max_backups:
                    # Remove oldest backups
                    to_remove = len(self._backup_history) - self.max_backups
                    # Get the backups to remove before modifying the list
                    backups_to_remove = self._backup_history[:to_remove]
                    # Delete the backup directories
                    for old_backup in backups_to_remove:
                        try:
                            shutil.rmtree(old_backup.backup_path, ignore_errors=True)
                        except:
                            pass
                    # Remove from history
                    self._backup_history = self._backup_history[to_remove:]
                
                self._save_backup_history()
            
            return backup_info
            
        except Exception as e:
            self._log_error(f"Backup failed: {e}")
            with self._lock:
                self._backup_history.append(BackupInfo(
                    backup_path="",
                    timestamp=time.time(),
                    size_bytes=0,
                    hash_value="",
                    status=f"failed: {e}"
                ))
                self._save_backup_history()
            return None
    
    def _compute_backup_hash(self, backup_dir: Path) -> str:
        """Compute SHA-256 hash of all files in backup."""
        hasher = hashlib.sha256()
        
        for file_path in sorted(backup_dir.rglob('*')):
            if file_path.is_file():
                with open(file_path, 'rb') as f:
                    hasher.update(file_path.name.encode())
                    hasher.update(f.read())
        
        return hasher.hexdigest()
    
    def restore_from_backup(self, backup_info: BackupInfo) -> bool:
        """
        Restore blockchain data from a backup.
        
        Args:
            backup_info: Backup to restore from
            
        Returns:
            True if restore succeeded, False otherwise
        """
        try:
            backup_dir = Path(backup_info.backup_path)
            if not backup_dir.exists():
                return False
            
            # Close current database connection
            self.hash_chain.close()
            
            # Restore database file
            db_path = Path(self.hash_chain.db_path)
            # Find the database file in the backup
            backup_db_files = list(backup_dir.glob("*.db"))
            if backup_db_files:
                # Copy the first .db file found
                shutil.copy2(backup_db_files[0], db_path)
            
            # Restore audit log if it exists in backup
            backup_audit_files = list(backup_dir.glob("audit.log"))
            if backup_audit_files and hasattr(self.hash_chain, 'audit_logger'):
                audit_log_path = Path(self.hash_chain.audit_logger.log_path)
                audit_log_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_audit_files[0], audit_log_path)
            
            # Reopen connection directly without calling _initialize_database
            # (which would create a new connection and potentially reset things)
            self.hash_chain.connection = sqlite3.connect(str(db_path))
            self.hash_chain.connection.execute("PRAGMA foreign_keys = ON")
            self.hash_chain.connection.execute("PRAGMA journal_mode = WAL")
            
            # Reinitialize audit logger if it exists
            if hasattr(self.hash_chain, 'audit_logger'):
                self.hash_chain.audit_logger = AuditLogger(str(self.hash_chain.audit_logger.log_path))
            
            # Verify integrity after restore
            return self.hash_chain.verify_block_chain_integrity()
            
        except Exception as e:
            self._log_error(f"Restore failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_latest_backup(self) -> Optional[BackupInfo]:
        """Get the most recent backup."""
        with self._lock:
            if self._backup_history:
                return self._backup_history[-1]
            return None
    
    def get_backup_history(self) -> List[BackupInfo]:
        """Get all backup history."""
        with self._lock:
            return list(self._backup_history)
    
    def get_check_results(self) -> List[IntegrityCheckResult]:
        """Get the latest check results."""
        with self._lock:
            return list(self._check_results)
    
    def get_overall_status(self) -> IntegrityStatus:
        """Get overall integrity status."""
        with self._lock:
            if not self._check_results:
                return IntegrityStatus.UNKNOWN
            
            # If any critical, return critical
            if any(r.status == IntegrityStatus.CRITICAL for r in self._check_results):
                return IntegrityStatus.CRITICAL
            
            # If any warning, return warning
            if any(r.status == IntegrityStatus.WARNING for r in self._check_results):
                return IntegrityStatus.WARNING
            
            return IntegrityStatus.HEALTHY
    
    def _alert(self, message: str) -> None:
        """Send an alert."""
        self._log_error(message)
        if self.alert_callback:
            try:
                self.alert_callback(message)
            except:
                pass
    
    def _log_error(self, message: str) -> None:
        """Log an error message."""
        # For now, just print to stderr
        # In production, this would log to a file or monitoring system
        import sys
        print(f"[INTEGRITY MONITOR] {message}", file=sys.stderr)
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
