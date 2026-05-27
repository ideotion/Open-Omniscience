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
Core Blockchain Components for Open-Omniscience

Provides the foundational classes for per-article verification:
- LocalBlock: Dataclass representing a block in the hash chain
- LocalHashChain: SQLite-based hash chain for storing article hashes

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from .hash_chain import (
    LocalBlock,
    LocalHashChain,
    EnhancedLocalHashChain,
    create_hash_chain,
    create_enhanced_hash_chain,
)
from .crypto_utils import (
    HashAlgorithm,
    HashResult,
    MultiHash,
    AuditEntry,
    AuditLogger,
    IntegrityError,
    WORMError,
    compute_hash,
    compute_multi_hash,
    compute_article_multi_hash,
    get_audit_logger,
    reset_audit_logger,
)
from .integrity_monitor import (
    IntegrityMonitor,
    IntegrityStatus,
    IntegrityCheckResult,
    BackupInfo,
)
from .coc import (
    CoCAction,
    CoCEntry,
    CoCReport,
    CoCError,
    CoCVerificationError,
    CoCTimestampError,
    CoCSignatureError,
    ChainOfCustodyLogger,
    get_coc_logger,
    initialize_coc_logger,
    reset_coc_logger,
)
from .tsa import (
    TSAError,
    TSARequestError,
    TSAVerificationError,
    RFC3161Client,
    SimpleHTTPTSAClient,
    TSAClient,
)
from .pqc import (
    HybridSignature,
    HybridKeyPair,
    HashAlgorithm as PQCHashAlgorithm,
    SignatureAlgorithm,
    PQCError,
    PQCNotAvailableError,
    SignatureVerificationError,
    generate_hybrid_keypair,
    sign_hybrid,
    verify_hybrid,
    hash_data,
    get_available_algorithms,
    get_global_hybrid_keypair,
    generate_global_hybrid_keypair,
    reset_global_hybrid_keypair,
)
from .key_manager import (
    KeyManager,
    KeyMetadata,
    KeyStatus,
    KeyType,
    KeyRevocationEntry,
    KeyManagerError,
    KeyNotFoundError,
    KeyRevokedError,
    KeyExpiredError,
    get_key_manager,
    reset_key_manager,
)

__all__ = [
    # Hash Chain
    'LocalBlock',
    'LocalHashChain',
    'EnhancedLocalHashChain',
    'create_hash_chain',
    'create_enhanced_hash_chain',
    
    # Crypto Utils
    'HashAlgorithm',
    'HashResult',
    'MultiHash',
    'AuditEntry',
    'AuditLogger',
    'IntegrityError',
    'WORMError',
    'compute_hash',
    'compute_multi_hash',
    'compute_article_multi_hash',
    'get_audit_logger',
    'reset_audit_logger',
    
    # Integrity Monitor
    'IntegrityMonitor',
    'IntegrityStatus',
    'IntegrityCheckResult',
    'BackupInfo',
    
    # Chain of Custody
    'CoCAction',
    'CoCEntry',
    'CoCReport',
    'CoCError',
    'CoCVerificationError',
    'CoCTimestampError',
    'CoCSignatureError',
    'ChainOfCustodyLogger',
    'get_coc_logger',
    'initialize_coc_logger',
    'reset_coc_logger',
    
    # Timestamp Authority
    'TSAError',
    'TSARequestError',
    'TSAVerificationError',
    'RFC3161Client',
    'SimpleHTTPTSAClient',
    'TSAClient',
    
    # Post-Quantum Cryptography (PQC)
    'HybridSignature',
    'HybridKeyPair',
    'PQCHashAlgorithm',
    'SignatureAlgorithm',
    'PQCError',
    'PQCNotAvailableError',
    'SignatureVerificationError',
    'generate_hybrid_keypair',
    'sign_hybrid',
    'verify_hybrid',
    'hash_data',
    'get_available_algorithms',
    'get_global_hybrid_keypair',
    'generate_global_hybrid_keypair',
    'reset_global_hybrid_keypair',
    
    # Key Manager (Forward Secrecy)
    'KeyManager',
    'KeyMetadata',
    'KeyStatus',
    'KeyType',
    'KeyRevocationEntry',
    'KeyManagerError',
    'KeyNotFoundError',
    'KeyRevokedError',
    'KeyExpiredError',
    'get_key_manager',
    'reset_key_manager',
]
