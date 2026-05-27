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
"""
Chain of Custody (CoC) Module for Open-Omniscience

Provides legally admissible, tamper-evident tracking of all actions on articles,
with cryptographic timestamps, digital signatures, and exportable reports.

Features:
- RFC 3161 TSA (Timestamp Authority) support for legally binding timestamps
- Hybrid digital signatures (Ed25519 + Dilithium3) for non-repudiation and quantum resistance
- Cryptographic chaining of log entries for tamper detection
- Exportable PDF/JSON reports for legal proceedings
- Offline-first design with fallback to local timestamps
- Key rotation and forward secrecy support

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import json
import sqlite3
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import hashlib

# Import PQC and Key Manager
from .pqc import (
    HybridSignature,
    HybridKeyPair,
    HashAlgorithm,
    SignatureAlgorithm,
    sign_hybrid,
    verify_hybrid,
    hash_data,
    generate_hybrid_keypair,
    PQCError,
    PQCNotAvailableError,
)
from .key_manager import (
    KeyManager,
    KeyMetadata,
    KeyStatus,
    get_key_manager,
    reset_key_manager,
    KeyManagerError,
    KeyNotFoundError,
    KeyRevokedError,
    KeyExpiredError,
)

# Optional imports (for PDF generation and RFC 3161)
try:
    import pdfkit
    HAS_PDFKIT = True
except ImportError:
    HAS_PDFKIT = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleL, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


class CoCError(Exception):
    """Base exception for Chain of Custody errors."""
    pass


class CoCVerificationError(CoCError):
    """Raised when CoC verification fails."""
    pass


class CoCTimestampError(CoCError):
    """Raised when timestamping fails."""
    pass


class CoCSignatureError(CoCError):
    """Raised when signature verification fails."""
    pass


class CoCAction(Enum):
    """
    Enumeration of all possible actions that can be logged in the Chain of Custody.
    
    Each action represents a significant event in the lifecycle of an article,
    from ingestion to deletion, with full auditability.
    """
    INGEST = "ingest"          # Article ingested into the system
    MODIFY = "modify"          # Article metadata or content updated
    ACCESS = "access"          # Article accessed (read/exported)
    DELETE = "delete"          # Article deleted (secure wipe)
    VERIFY = "verify"          # Article verified (hash check)
    ANCHOR = "anchor"          # Article anchored to blockchain
    RESTORE = "restore"        # Article restored from backup
    EXPORT = "export"          # Article exported (e.g., to PDF/JSON)
    REDACT = "redact"         # Sensitive data redacted from article
    SIGN = "sign"             # Article signed (e.g., by journalist/editor)


@dataclass
class CoCEntry:
    """
    A single entry in the Chain of Custody log.
    
    Each entry is cryptographically signed, timestamped, and chained to the
    previous entry to ensure tamper-evidence. This class is immutable once
    created and hashed.
    
    Attributes:
        entry_id: Unique identifier (UUID4) for this entry.
        article_id: Reference to the article (hash or ID).
        article_hash: SHA-3-512 hash of the article content at the time of action.
        action: The type of action performed (from CoCAction enum).
        timestamp: Local timestamp when the action occurred (UTC).
        tsa_timestamp: RFC 3161 timestamp (if available).
        tsa_token: Raw TSA token for verification (if available).
        tsa_algorithm: Algorithm used for TSA (e.g., "dilithium3", "rsa", "ed25519").
        actor_id: Identifier of the actor (user, system, etc.).
        actor_signature: HybridSignature (Ed25519 + Dilithium3) of the entry.
        previous_entry_hash: Hash of the previous CoC entry for this article.
        entry_hash: SHA-3-512 hash of this entry (computed from all other fields).
        metadata: Additional context (e.g., modification details).
        key_id: ID of the key used for signing (for key rotation tracking).
        hash_algorithm: Hash algorithm used (default: SHA3_512).
    """
    entry_id: str
    article_id: str
    article_hash: str
    action: CoCAction
    timestamp: datetime
    tsa_timestamp: Optional[datetime] = None
    tsa_token: Optional[bytes] = None
    tsa_algorithm: Optional[str] = None
    actor_id: Optional[str] = None
    actor_signature: Optional[HybridSignature] = None
    previous_entry_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    entry_hash: Optional[str] = field(default=None, init=False)
    key_id: Optional[str] = None
    hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512

    def __post_init__(self) -> None:
        """Compute entry_hash after initialization."""
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """
        Compute hash of the entry (excluding entry_hash and actor_signature).
        
        This hash is used for:
        - Storing as entry_hash in the database
        - Signing the entry (actor_signature)
        - Verifying the entry's integrity
        
        Returns:
            Hexadecimal hash string (using the configured hash_algorithm).
        """
        # Serialize all fields except entry_hash and actor_signature
        # (actor_signature is excluded because it's derived from this hash)
        data = {
            "entry_id": self.entry_id,
            "article_id": self.article_id,
            "article_hash": self.article_hash,
            "action": self.action.value,
            "timestamp": self.timestamp.isoformat(),
            "tsa_timestamp": self.tsa_timestamp.isoformat() if self.tsa_timestamp else None,
            "tsa_token": self.tsa_token.hex() if self.tsa_token else None,
            "tsa_algorithm": self.tsa_algorithm,
            "actor_id": self.actor_id,
            # NOTE: actor_signature is EXCLUDED to avoid circular dependency
            "previous_entry_hash": self.previous_entry_hash,
            "metadata": json.dumps(self.metadata, sort_keys=True),
            "key_id": self.key_id,
            "hash_algorithm": self.hash_algorithm.value,
        }
        serialized = json.dumps(data, sort_keys=True)
        
        # Use the configured hash algorithm
        if self.hash_algorithm == HashAlgorithm.SHA256:
            return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        elif self.hash_algorithm == HashAlgorithm.SHA3_256:
            return hashlib.sha3_256(serialized.encode("utf-8")).hexdigest()
        elif self.hash_algorithm == HashAlgorithm.SHA3_512:
            return hashlib.sha3_512(serialized.encode("utf-8")).hexdigest()
        elif self.hash_algorithm == HashAlgorithm.BLAKE2B:
            return hashlib.blake2b(serialized.encode("utf-8"), digest_size=64).hexdigest()
        elif self.hash_algorithm == HashAlgorithm.BLAKE2S:
            return hashlib.blake2s(serialized.encode("utf-8"), digest_size=32).hexdigest()
        else:
            # Fallback to SHA-3-512
            return hashlib.sha3_512(serialized.encode("utf-8")).hexdigest()

    def to_dict(self, include_signature: bool = True) -> Dict[str, Any]:
        """
        Convert the entry to a dictionary.
        
        Args:
            include_signature: Whether to include the actor_signature in the output.
            
        Returns:
            Dictionary representation of the entry.
        """
        result = {
            "entry_id": self.entry_id,
            "article_id": self.article_id,
            "article_hash": self.article_hash,
            "action": self.action.value,
            "timestamp": self.timestamp.isoformat(),
            "tsa_timestamp": self.tsa_timestamp.isoformat() if self.tsa_timestamp else None,
            "tsa_token": self.tsa_token.hex() if self.tsa_token else None,
            "tsa_algorithm": self.tsa_algorithm,
            "actor_id": self.actor_id,
            "previous_entry_hash": self.previous_entry_hash,
            "entry_hash": self.entry_hash,
            "metadata": self.metadata,
            "key_id": self.key_id,
            "hash_algorithm": self.hash_algorithm.value,
        }
        if include_signature and self.actor_signature:
            result["actor_signature"] = self.actor_signature.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoCEntry":
        """
        Create a CoCEntry from a dictionary.
        
        Args:
            data: Dictionary containing entry fields.
            
        Returns:
            CoCEntry instance.
        """
        # Handle actor_signature (can be bytes or dict)
        actor_signature = None
        if data.get("actor_signature"):
            sig_data = data["actor_signature"]
            if isinstance(sig_data, dict):
                actor_signature = HybridSignature.from_dict(sig_data)
            elif isinstance(sig_data, str):
                # Legacy: assume it's a hex-encoded Ed25519 signature
                # Convert to HybridSignature with only Ed25519
                actor_signature = HybridSignature(
                    ed25519_signature=bytes.fromhex(sig_data),
                    algorithm=SignatureAlgorithm.ED25519,
                )
            elif isinstance(sig_data, bytes):
                # Legacy: assume it's an Ed25519 signature
                actor_signature = HybridSignature(
                    ed25519_signature=sig_data,
                    algorithm=SignatureAlgorithm.ED25519,
                )
        
        return cls(
            entry_id=data["entry_id"],
            article_id=data["article_id"],
            article_hash=data["article_hash"],
            action=CoCAction(data["action"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            tsa_timestamp=datetime.fromisoformat(data["tsa_timestamp"]) if data.get("tsa_timestamp") else None,
            tsa_token=bytes.fromhex(data["tsa_token"]) if data.get("tsa_token") else None,
            tsa_algorithm=data.get("tsa_algorithm"),
            actor_id=data.get("actor_id"),
            actor_signature=actor_signature,
            previous_entry_hash=data.get("previous_entry_hash"),
            metadata=data.get("metadata", {}),
            key_id=data.get("key_id"),
            hash_algorithm=HashAlgorithm(data.get("hash_algorithm", "sha3_512")),
        )

    def verify_hash(self) -> bool:
        """
        Verify that the entry_hash matches the computed hash of the entry.
        
        Returns:
            True if the hash is valid, False otherwise.
        """
        return self.entry_hash == self._compute_hash()


@dataclass
class CoCReport:
    """
    An exportable Chain of Custody report for legal use.
    
    This report contains the full history of actions performed on an article,
    along with cryptographic proofs (signatures, timestamps, hashes) for
    verification in court or by third parties.
    
    Attributes:
        report_id: Unique identifier for this report.
        generated_at: Timestamp when the report was generated.
        generated_by: Identifier of the system/user that generated the report.
        article_id: Reference to the article.
        article_hash: SHA-256 hash of the article content.
        article_metadata: Additional metadata about the article.
        coc_entries: List of all CoC entries for the article.
        is_verified: Whether the CoC passed verification.
        verification_errors: List of errors (if verification failed).
        redact_actor_ids: Whether to redact actor IDs in exported reports.
        redact_metadata: Whether to redact metadata in exported reports.
    """
    report_id: str
    generated_at: datetime
    generated_by: str
    article_id: str
    article_hash: str
    article_metadata: Dict[str, Any]
    coc_entries: List[CoCEntry]
    is_verified: bool = True
    verification_errors: List[str] = field(default_factory=list)
    redact_actor_ids: bool = False
    redact_metadata: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the report to a dictionary (machine-readable).
        
        Returns:
            Dictionary representation of the report.
        """
        entries = []
        for entry in self.coc_entries:
            entry_dict = entry.to_dict(include_signature=True)
            if self.redact_actor_ids:
                entry_dict["actor_id"] = "REDACTED"
            if self.redact_metadata:
                entry_dict["metadata"] = "REDACTED"
            entries.append(entry_dict)

        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": self.generated_by,
            "article": {
                "id": self.article_id,
                "hash": self.article_hash,
                **self.article_metadata,
            },
            "chain_of_custody": entries,
            "verification": {
                "is_verified": self.is_verified,
                "errors": self.verification_errors,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert the report to a JSON string.
        
        Args:
            indent: JSON indentation level.
            
        Returns:
            JSON string representation of the report.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def to_pdf(self, output_path: str) -> None:
        """
        Export the report as a PDF (human-readable).
        
        Args:
            output_path: Path to save the PDF file.
            
        Raises:
            CoCError: If PDF generation fails.
        """
        if HAS_PDFKIT:
            self._export_with_pdfkit(output_path)
        elif HAS_REPORTLAB:
            self._export_with_reportlab(output_path)
        else:
            raise CoCError(
                "PDF generation requires either 'pdfkit' or 'reportlab'. "
                "Install with: pip install pdfkit or pip install reportlab"
            )

    def _export_with_pdfkit(self, output_path: str) -> None:
        """Export using pdfkit (requires wkhtmltopdf)."""
        html = self._generate_html_report()
        try:
            pdfkit.from_string(html, output_path)
        except Exception as e:
            raise CoCError(f"PDF generation failed (pdfkit): {e}")

    def _export_with_reportlab(self, output_path: str) -> None:
        """Export using reportlab (pure Python)."""
        try:
            doc = SimpleDocTemplate(
                output_path,
                pagesize=letter,
                title=f"CoC Report - {self.article_id}",
            )
            story = []
            styles = getSampleStyleL()

            # Title
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Heading1"],
                fontSize=24,
                textColor=colors.black,
                spaceAfter=30,
            )
            story.append(Paragraph(f"Chain of Custody Report", title_style))
            story.append(Spacer(1, 12))

            # Report metadata
            story.append(Paragraph(f"<b>Report ID:</b> {self.report_id}", styles["Normal"]))
            story.append(Paragraph(f"<b>Generated:</b> {self.generated_at}", styles["Normal"]))
            story.append(Paragraph(f"<b>Generated By:</b> {self.generated_by}", styles["Normal"]))
            story.append(Spacer(1, 12))

            # Article metadata
            story.append(Paragraph("<b>Article Details</b>", styles["Heading2"]))
            story.append(Paragraph(f"<b>Article ID:</b> {self.article_id}", styles["Normal"]))
            story.append(Paragraph(f"<b>Article Hash:</b> {self.article_hash}", styles["Normal"]))
            story.append(Spacer(1, 12))

            # Verification status
            status_color = colors.green if self.is_verified else colors.red
            status_text = "✅ Valid" if self.is_verified else "❌ Invalid"
            story.append(Paragraph(f"<b>Verification Status:</b> <font color={status_color}>{status_text}</font>", styles["Normal"]))
            story.append(Spacer(1, 12))

            # Chain of Custody table
            story.append(Paragraph("Chain of Custody Entries", styles["Heading2"]))
            
            # Prepare table data
            table_data = [
                ["#", "Action", "Timestamp", "TSA Timestamp", "Actor", "Entry Hash"],
            ]
            for i, entry in enumerate(self.coc_entries, 1):
                actor = entry.actor_id if not self.redact_actor_ids else "REDACTED"
                tsa_ts = entry.tsa_timestamp.isoformat() if entry.tsa_timestamp else "N/A"
                table_data.append([
                    str(i),
                    entry.action.value,
                    entry.timestamp.isoformat(),
                    tsa_ts,
                    actor or "N/A",
                    entry.entry_hash[:16] + "..." if entry.entry_hash else "N/A",
                ])

            # Create table
            table = Table(table_data)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]))
            story.append(table)
            story.append(Spacer(1, 12))

            # Verification errors
            if self.verification_errors:
                story.append(Paragraph("Verification Errors", styles["Heading2"]))
                for error in self.verification_errors:
                    story.append(Paragraph(f"• {error}", styles["Normal"]))

            doc.build(story)
        except Exception as e:
            raise CoCError(f"PDF generation failed (reportlab): {e}")

    def _generate_html_report(self) -> str:
        """Generate HTML for the PDF report (used by pdfkit)."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Chain of Custody Report - {self.article_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; }}
                h1 {{ color: #333; border-bottom: 2px solid #333; padding-bottom: 10px; }}
                h2 {{ color: #555; margin-top: 20px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .status-valid {{ color: green; }}
                .status-invalid {{ color: red; }}
                .metadata {{ background-color: #f9f9f9; padding: 10px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>Chain of Custody Report</h1>
            <div class="metadata">
                <p><strong>Report ID:</strong> {self.report_id}</p>
                <p><strong>Generated:</strong> {self.generated_at}</p>
                <p><strong>Generated By:</strong> {self.generated_by}</p>
            </div>
            
            <h2>Article Details</h2>
            <p><strong>Article ID:</strong> {self.article_id}</p>
            <p><strong>Article Hash:</strong> {self.article_hash}</p>
            
            <h2>Verification Status</h2>
            <p class="status-{'valid' if self.is_verified else 'invalid'}">
                <strong>Status:</strong> {'✅ Valid' if self.is_verified else '❌ Invalid'}
            </p>
            
            <h2>Chain of Custody Entries</h2>
            <table>
                <tr>
                    <th>#</th>
                    <th>Action</th>
                    <th>Timestamp</th>
                    <th>TSA Timestamp</th>
                    <th>Actor</th>
                    <th>Entry Hash</th>
                </tr>
        """
        for i, entry in enumerate(self.coc_entries, 1):
            actor = entry.actor_id if not self.redact_actor_ids else "REDACTED"
            tsa_ts = entry.tsa_timestamp.isoformat() if entry.tsa_timestamp else "N/A"
            html += f"""
                <tr>
                    <td>{i}</td>
                    <td>{entry.action.value}</td>
                    <td>{entry.timestamp}</td>
                    <td>{tsa_ts}</td>
                    <td>{actor or 'N/A'}</td>
                    <td>{entry.entry_hash[:16]}...</td>
                </tr>
            """
        html += """
            </table>
            
            <h2>Verification Errors</h2>
            <ul>
        """
        for error in self.verification_errors:
            html += f"                <li>{error}</li>\n"
        html += """
            </ul>
        </body>
        </html>
        """
        return html


class ChainOfCustodyLogger:
    """
    Core class for logging, storing, and verifying Chain of Custody entries.
    
    This class manages the **immutable, tamper-evident log** of all actions
    performed on articles in the Open-Omniscience system. It supports:
    - **Cryptographic chaining** of entries (each entry includes the hash of the previous).
    - **Hybrid digital signatures** (Ed25519 + Dilithium3) for non-repudiation and quantum resistance.
    - **RFC 3161 timestamps** for legally admissible time proofs.
    - **SQLite storage** for persistence.
    - **Offline mode** with fallback to local timestamps.
    - **Key rotation and forward secrecy** via KeyManager integration.
    
    Example:
        >>> coc_logger = ChainOfCustodyLogger(db_path="data/coc.db")
        >>> entry = coc_logger.log_action(
        ...     article_id="article_123",
        ...     article_hash="abc123...",
        ...     action=CoCAction.INGEST,
        ...     actor_id="journalist_1",
        ... )
        >>> report = coc_logger.generate_report("article_123")
        >>> report.to_pdf("coc_report.pdf")
    """

    def __init__(
        self,
        db_path: str = "data/coc.db",
        private_key: Optional[bytes] = None,
        tsa_url: Optional[str] = None,
        enable_signing: bool = True,
        enable_tsa: bool = True,
        key_manager: Optional[KeyManager] = None,
        hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512,
    ) -> None:
        """
        Initialize the ChainOfCustodyLogger.
        
        Args:
            db_path: Path to the SQLite database for storing CoC entries.
            private_key: Ed25519 private key (bytes) for signing entries (legacy).
            tsa_url: URL of the RFC 3161 Timestamp Authority (e.g., "http://timestamp.digicert.com").
            enable_signing: Whether to sign entries (requires private_key or key_manager).
            enable_tsa: Whether to request TSA timestamps (requires tsa_url).
            key_manager: KeyManager instance for key rotation and forward secrecy.
            hash_algorithm: Hash algorithm to use (default: SHA3_512).
        """
        self.db_path = db_path
        self.private_key = private_key
        self.tsa_url = tsa_url
        self.enable_signing = enable_signing and (private_key is not None or key_manager is not None)
        self.enable_tsa = enable_tsa and (tsa_url is not None)
        self.key_manager = key_manager
        self.hash_algorithm = hash_algorithm
        self._public_key: Optional[bytes] = None
        self._tsa_client: Optional["RFC3161Client"] = None
        self._use_legacy_signing = private_key is not None and key_manager is None

        # Initialize database
        self._initialize_database()

        # Initialize TSA client if enabled
        if self.enable_tsa:
            self._init_tsa_client()

        # Derive public key if using legacy signing
        if self._use_legacy_signing and self.enable_signing:
            self._public_key = self._derive_public_key()

    def _init_tsa_client(self) -> None:
        """Initialize the RFC 3161 TSA client."""
        try:
            from .tsa import RFC3161Client
            self._tsa_client = RFC3161Client(self.tsa_url)
        except ImportError:
            # Fallback: Implement a basic TSA client here if needed
            self._tsa_client = None

    def _derive_public_key(self) -> bytes:
        """
        Derive the public key from the private key.
        
        Returns:
            Ed25519 public key (bytes in PEM format).
        """
        if not HAS_CRYPTOGRAPHY:
            raise CoCError("Signing requires 'cryptography' library. Install with: pip install cryptography")
        try:
            private_key_obj = serialization.load_pem_private_key(self.private_key, password=None)
            if not isinstance(private_key_obj, Ed25519PrivateKey):
                raise CoCError("Private key must be Ed25519")
            return private_key_obj.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as e:
            raise CoCError(f"Failed to derive public key: {e}")

    def _initialize_database(self) -> None:
        """Initialize the SQLite database for CoC entries."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS coc_entries (
                    entry_id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL,
                    article_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tsa_timestamp TEXT,
                    tsa_token BLOB,
                    tsa_algorithm TEXT,
                    actor_id TEXT,
                    actor_signature TEXT,  -- JSON-serialized HybridSignature
                    previous_entry_hash TEXT,
                    entry_hash TEXT NOT NULL,
                    metadata TEXT,
                    key_id TEXT,
                    hash_algorithm TEXT DEFAULT 'sha3_512',
                    FOREIGN KEY (article_id) REFERENCES articles(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_coc_article_id 
                ON coc_entries (article_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_coc_timestamp 
                ON coc_entries (timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_coc_key_id 
                ON coc_entries (key_id)
            """)

    def log_action(
        self,
        article_id: str,
        article_hash: str,
        action: CoCAction,
        actor_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        key_id: Optional[str] = None,
    ) -> CoCEntry:
        """
        Log a new action to the Chain of Custody.
        
        This method:
        1. Creates a new CoCEntry with the provided details.
        2. Requests a TSA timestamp (if enabled and online).
        3. Signs the entry with hybrid signature (Ed25519 + Dilithium3) (if enabled).
        4. Stores the entry in the database.
        
        Args:
            article_id: Unique identifier for the article.
            article_hash: SHA-3-512 hash of the article content at the time of action.
            action: The type of action being logged (from CoCAction enum).
            actor_id: Identifier of the actor (user, system, etc.).
            metadata: Additional context (e.g., modification details).
            key_id: Optional key ID to use for signing (default: current key from KeyManager).
            
        Returns:
            The created CoCEntry.
        """
        # Get the last entry for this article (for chaining)
        previous_entry = self._get_last_entry(article_id)
        previous_entry_hash = previous_entry.entry_hash if previous_entry else None

        # Create new entry
        entry = CoCEntry(
            entry_id=str(uuid.uuid4()),
            article_id=article_id,
            article_hash=article_hash,
            action=action,
            timestamp=datetime.utcnow(),
            actor_id=actor_id,
            previous_entry_hash=previous_entry_hash,
            metadata=metadata or {},
            hash_algorithm=self.hash_algorithm,
        )

        # Request TSA timestamp (if enabled)
        if self.enable_tsa and self._tsa_client:
            try:
                tsa_timestamp, tsa_token, tsa_algorithm = self._tsa_client.get_timestamp(
                    entry.entry_hash.encode(),
                    hash_algorithm=self.hash_algorithm,
                )
                entry.tsa_timestamp = tsa_timestamp
                entry.tsa_token = tsa_token
                entry.tsa_algorithm = tsa_algorithm
            except Exception as e:
                # Log warning but continue (fallback to local timestamp)
                logger.warning(f"TSA timestamp failed: {e}")

        # Sign the entry (if enabled)
        if self.enable_signing:
            entry.actor_signature, entry.key_id = self._sign_entry(entry, key_id)

        # Store in database
        self._store_entry(entry)

        return entry

    def _get_last_entry(self, article_id: str) -> Optional[CoCEntry]:
        """
        Retrieve the most recent CoC entry for an article.
        
        Args:
            article_id: Unique identifier for the article.
            
        Returns:
            The last CoCEntry for the article, or None if none exists.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM coc_entries 
                WHERE article_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (article_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_entry(row)
            return None

    def _sign_entry(
        self,
        entry: CoCEntry,
        key_id: Optional[str] = None,
    ) -> Tuple[Optional[HybridSignature], Optional[str]]:
        """
        Sign the entry with a hybrid signature (Ed25519 + Dilithium3).
        
        Args:
            entry: The CoCEntry to sign.
            key_id: Optional key ID to use (default: current key from KeyManager).
            
        Returns:
            Tuple of (HybridSignature, key_id) or (None, None) if signing fails.
        """
        if not self.enable_signing:
            return None, None
        
        try:
            # Use KeyManager if available
            if self.key_manager is not None:
                hybrid_key = self.key_manager.get_key(key_id) if key_id else self.key_manager.get_current_key()
                data = entry._compute_hash().encode()
                signature = sign_hybrid(hybrid_key, data, entry.hash_algorithm)
                return signature, hybrid_key.key_id
            
            # Fallback to legacy Ed25519 signing
            elif self._use_legacy_signing and HAS_CRYPTOGRAPHY:
                private_key_obj = serialization.load_pem_private_key(self.private_key, password=None)
                data = entry._compute_hash().encode()
                ed25519_sig = private_key_obj.sign(data)
                # Convert to HybridSignature for compatibility
                signature = HybridSignature(
                    ed25519_signature=ed25519_sig,
                    algorithm=SignatureAlgorithm.ED25519,
                )
                return signature, None
            else:
                logger.warning("Signing disabled: no key_manager or private_key")
                return None, None
        except Exception as e:
            logger.error(f"Failed to sign entry: {e}")
            raise CoCSignatureError(f"Failed to sign entry: {e}")

    def _store_entry(self, entry: CoCEntry) -> None:
        """
        Store the entry in the SQLite database.
        
        Args:
            entry: The CoCEntry to store.
        """
        # Serialize actor_signature (HybridSignature) to JSON
        actor_signature_json = None
        if entry.actor_signature:
            actor_signature_json = json.dumps(entry.actor_signature.to_dict())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO coc_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.entry_id,
                entry.article_id,
                entry.article_hash,
                entry.action.value,
                entry.timestamp.isoformat(),
                entry.tsa_timestamp.isoformat() if entry.tsa_timestamp else None,
                entry.tsa_token,
                entry.tsa_algorithm,
                entry.actor_id,
                actor_signature_json,
                entry.previous_entry_hash,
                entry.entry_hash,
                json.dumps(entry.metadata),
                entry.key_id,
                entry.hash_algorithm.value,
            ))

    def _row_to_entry(self, row: sqlite3.Row) -> CoCEntry:
        """
        Convert a SQLite row to a CoCEntry.
        
        Args:
            row: SQLite row from coc_entries table.
            
        Returns:
            CoCEntry instance.
        """
        # Create the entry without triggering __post_init__ (which would recompute entry_hash)
        entry = CoCEntry.__new__(CoCEntry)
        entry.entry_id = row[0]
        entry.article_id = row[1]
        entry.article_hash = row[2]
        entry.action = CoCAction(row[3])
        entry.timestamp = datetime.fromisoformat(row[4])
        entry.tsa_timestamp = datetime.fromisoformat(row[5]) if row[5] else None
        entry.tsa_token = row[6]
        entry.tsa_algorithm = row[7]
        entry.actor_id = row[8]
        
        # Deserialize actor_signature (HybridSignature)
        if row[9]:
            try:
                sig_dict = json.loads(row[9])
                entry.actor_signature = HybridSignature.from_dict(sig_dict)
            except (json.JSONDecodeError, KeyError):
                # Legacy: assume it's a hex-encoded Ed25519 signature
                if isinstance(row[9], str):
                    entry.actor_signature = HybridSignature(
                        ed25519_signature=bytes.fromhex(row[9]),
                        algorithm=SignatureAlgorithm.ED25519,
                    )
                elif isinstance(row[9], bytes):
                    entry.actor_signature = HybridSignature(
                        ed25519_signature=row[9],
                        algorithm=SignatureAlgorithm.ED25519,
                    )
                else:
                    entry.actor_signature = None
        else:
            entry.actor_signature = None
        
        entry.previous_entry_hash = row[10]
        entry.entry_hash = row[11]  # Load the stored hash (do NOT recompute)
        entry.metadata = json.loads(row[12]) if row[12] else {}
        entry.key_id = row[13]
        entry.hash_algorithm = HashAlgorithm(row[14]) if row[14] else HashAlgorithm.SHA3_512
        return entry

    def get_coc_for_article(self, article_id: str) -> List[CoCEntry]:
        """
        Retrieve all CoC entries for an article.
        
        Args:
            article_id: Unique identifier for the article.
            
        Returns:
            List of CoCEntry objects, ordered by timestamp.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM coc_entries 
                WHERE article_id = ? 
                ORDER BY timestamp ASC
            """, (article_id,))
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_entries_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        article_id: Optional[str] = None,
    ) -> List[CoCEntry]:
        """
        Retrieve CoC entries within a time range.
        
        Args:
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
            article_id: Optional filter for a specific article.
            
        Returns:
            List of CoCEntry objects in the time range.
        """
        # Convert datetimes to Unix timestamps for comparison
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        with sqlite3.connect(self.db_path) as conn:
            if article_id:
                cursor = conn.execute("""
                    SELECT * FROM coc_entries 
                    WHERE article_id = ? 
                    AND strftime('%s', timestamp) BETWEEN ? AND ? 
                    ORDER BY timestamp ASC
                """, (article_id, str(start_ts), str(end_ts)))
            else:
                cursor = conn.execute("""
                    SELECT * FROM coc_entries 
                    WHERE strftime('%s', timestamp) BETWEEN ? AND ? 
                    ORDER BY timestamp ASC
                """, (str(start_ts), str(end_ts)))
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def verify_coc(self, article_id: str) -> Tuple[bool, List[str]]:
        """
        Verify the integrity of the Chain of Custody for an article.
        
        This method checks:
        1. **Hash chain**: Each entry's previous_entry_hash matches the previous entry's entry_hash.
        2. **Signatures**: Each entry's signature is valid (if signing is enabled).
        3. **TSA tokens**: Each TSA token is valid (if TSA is enabled).
        4. **Entry hashes**: Each entry's entry_hash matches its computed hash.
        
        Args:
            article_id: Unique identifier for the article.
            
        Returns:
            Tuple of (is_valid, errors), where:
            - is_valid: True if all checks pass, False otherwise.
            - errors: List of error messages (empty if valid).
        """
        entries = self.get_coc_for_article(article_id)
        if not entries:
            return True, []  # Empty chain is valid

        errors: List[str] = []

        for i, entry in enumerate(entries):
            # Check entry hash (recompute and compare)
            computed_hash = entry._compute_hash()
            if entry.entry_hash != computed_hash:
                errors.append(f"Entry {entry.entry_id}: Entry hash mismatch")

            # Check hash chain (except for the first entry)
            if i > 0:
                expected_prev_hash = entries[i-1].entry_hash
                if entry.previous_entry_hash != expected_prev_hash:
                    errors.append(
                        f"Entry {entry.entry_id}: Previous hash mismatch "
                        f"(expected {expected_prev_hash}, got {entry.previous_entry_hash})"
                    )

            # Check signature (if signing is enabled and signature exists)
            if self.enable_signing and entry.actor_signature:
                if not self._verify_signature(entry):
                    errors.append(f"Entry {entry.entry_id}: Invalid signature")

            # Check TSA token (if TSA is enabled and token exists)
            if self.enable_tsa and entry.tsa_token and self._tsa_client:
                if not self._verify_tsa_token(entry):
                    errors.append(f"Entry {entry.entry_id}: Invalid TSA token")

        return len(errors) == 0, errors

    def _verify_signature(self, entry: CoCEntry) -> bool:
        """
        Verify the entry's hybrid signature.
        
        Args:
            entry: The CoCEntry to verify.
            
        Returns:
            True if the signature is valid, False otherwise.
        """
        if not entry.actor_signature or not entry.key_id:
            # Fallback to legacy verification if no key_id
            if self._use_legacy_signing and HAS_CRYPTOGRAPHY and self._public_key:
                try:
                    public_key_obj = serialization.load_pem_public_key(self._public_key)
                    data = entry._compute_hash().encode()
                    # Handle legacy signature (bytes)
                    if isinstance(entry.actor_signature, bytes):
                        public_key_obj.verify(entry.actor_signature, data)
                        return True
                    elif entry.actor_signature.ed25519_signature:
                        public_key_obj.verify(entry.actor_signature.ed25519_signature, data)
                        return True
                except Exception:
                    pass
            return False
        
        # Use KeyManager for verification
        if self.key_manager is not None:
            try:
                # Get the key used for signing
                hybrid_key = self.key_manager.get_key(entry.key_id)
                data = entry._compute_hash().encode()
                return verify_hybrid(hybrid_key, entry.actor_signature, data, entry.hash_algorithm)
            except (KeyNotFoundError, KeyRevokedError, KeyExpiredError):
                return False
            except Exception as e:
                logger.error(f"Failed to verify signature for entry {entry.entry_id}: {e}")
                return False
        
        return False

    def _verify_tsa_token(self, entry: CoCEntry) -> bool:
        """
        Verify the entry's TSA token.
        
        Args:
            entry: The CoCEntry to verify.
            
        Returns:
            True if the TSA token is valid, False otherwise.
        """
        if not self._tsa_client:
            return False
        try:
            return self._tsa_client.verify_token(
                entry.entry_hash.encode(),
                entry.tsa_token,
            )
        except Exception:
            return False

    def generate_report(
        self,
        article_id: str,
        redact_actor_ids: bool = False,
        redact_metadata: bool = False,
    ) -> CoCReport:
        """
        Generate a Chain of Custody report for an article.
        
        Args:
            article_id: Unique identifier for the article.
            redact_actor_ids: Whether to redact actor IDs in the report.
            redact_metadata: Whether to redact metadata in the report.
            
        Returns:
            CoCReport instance.
        """
        entries = self.get_coc_for_article(article_id)
        is_verified, errors = self.verify_coc(article_id)

        # Get article metadata (from main_pipeline or hash_chain)
        article_metadata = self._get_article_metadata(article_id)

        return CoCReport(
            report_id=str(uuid.uuid4()),
            generated_at=datetime.utcnow(),
            generated_by="Open-Omniscience CoC Logger",
            article_id=article_id,
            article_hash=entries[0].article_hash if entries else "",
            article_metadata=article_metadata,
            coc_entries=entries,
            is_verified=is_verified,
            verification_errors=errors,
            redact_actor_ids=redact_actor_ids,
            redact_metadata=redact_metadata,
        )

    def _get_article_metadata(self, article_id: str) -> Dict[str, Any]:
        """
        Retrieve article metadata from the main pipeline or hash chain.
        
        Args:
            article_id: Unique identifier for the article.
            
        Returns:
            Dictionary of article metadata.
        """
        # Try to get metadata from hash_chain first
        try:
            from .hash_chain import get_hash_chain
            hash_chain = get_hash_chain()
            if hash_chain:
                # Assuming hash_chain has a method to get article metadata
                return getattr(hash_chain, "get_article_metadata", lambda x: {})(article_id)
        except Exception:
            pass

        # Fallback: Return empty dict
        return {}

    def export_report_json(
        self,
        article_id: str,
        output_path: str,
        redact_actor_ids: bool = False,
        redact_metadata: bool = False,
    ) -> None:
        """
        Export the CoC report as JSON.
        
        Args:
            article_id: Unique identifier for the article.
            output_path: Path to save the JSON file.
            redact_actor_ids: Whether to redact actor IDs.
            redact_metadata: Whether to redact metadata.
        """
        report = self.generate_report(
            article_id,
            redact_actor_ids=redact_actor_ids,
            redact_metadata=redact_metadata,
        )
        with open(output_path, "w") as f:
            f.write(report.to_json())

    def export_report_pdf(
        self,
        article_id: str,
        output_path: str,
        redact_actor_ids: bool = False,
        redact_metadata: bool = False,
    ) -> None:
        """
        Export the CoC report as PDF.
        
        Args:
            article_id: Unique identifier for the article.
            output_path: Path to save the PDF file.
            redact_actor_ids: Whether to redact actor IDs.
            redact_metadata: Whether to redact metadata.
        """
        report = self.generate_report(
            article_id,
            redact_actor_ids=redact_actor_ids,
            redact_metadata=redact_metadata,
        )
        report.to_pdf(output_path)

    def get_all_articles(self) -> List[str]:
        """
        Get a list of all article IDs with CoC entries.
        
        Returns:
            List of unique article IDs.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT DISTINCT article_id FROM coc_entries
                ORDER BY article_id
            """)
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the CoC database.
        
        Returns:
            Dictionary with statistics (e.g., total entries, articles, etc.).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM coc_entries")
            total_entries = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(DISTINCT article_id) FROM coc_entries")
            total_articles = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM coc_entries WHERE tsa_timestamp IS NOT NULL")
            tsa_entries = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM coc_entries WHERE actor_signature IS NOT NULL")
            signed_entries = cursor.fetchone()[0]

            return {
                "total_entries": total_entries,
                "total_articles": total_articles,
                "tsa_entries": tsa_entries,
                "signed_entries": signed_entries,
                "db_path": self.db_path,
                "enable_signing": self.enable_signing,
                "enable_tsa": self.enable_tsa,
            }


# Singleton instance for global access
_coc_logger: Optional[ChainOfCustodyLogger] = None


def get_coc_logger() -> ChainOfCustodyLogger:
    """
    Get the global ChainOfCustodyLogger instance.
    
    Returns:
        The singleton ChainOfCustodyLogger instance.
        
    Raises:
        CoCError: If the logger has not been initialized.
    """
    global _coc_logger
    if _coc_logger is None:
        raise CoCError("CoC logger not initialized. Call initialize_coc_logger() first.")
    return _coc_logger


def initialize_coc_logger(
    db_path: str = "data/coc.db",
    private_key: Optional[bytes] = None,
    tsa_url: Optional[str] = None,
    enable_signing: bool = True,
    enable_tsa: bool = True,
) -> ChainOfCustodyLogger:
    """
    Initialize the global ChainOfCustodyLogger instance.
    
    Args:
        db_path: Path to the SQLite database.
        private_key: Ed25519 private key (bytes) for signing.
        tsa_url: URL of the RFC 3161 Timestamp Authority.
        enable_signing: Whether to enable signing.
        enable_tsa: Whether to enable TSA timestamps.
        
    Returns:
        The initialized ChainOfCustodyLogger instance.
    """
    global _coc_logger
    _coc_logger = ChainOfCustodyLogger(
        db_path=db_path,
        private_key=private_key,
        tsa_url=tsa_url,
        enable_signing=enable_signing,
        enable_tsa=enable_tsa,
    )
    return _coc_logger


def reset_coc_logger() -> None:
    """Reset the global ChainOfCustodyLogger instance."""
    global _coc_logger
    if _coc_logger:
        _coc_logger = None
