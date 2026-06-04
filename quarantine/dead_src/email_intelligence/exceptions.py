"""
Custom exceptions for Email Intelligence Module
"""


class EmailIntelligenceError(Exception):
    """Base exception for Email Intelligence Module"""
    pass


class EmailConfigError(EmailIntelligenceError):
    """Configuration-related errors"""
    pass


class EmailSourceError(EmailIntelligenceError):
    """Email source-related errors"""
    pass


class EmailConnectionError(EmailSourceError):
    """Connection errors for email sources"""
    pass


class EmailAuthenticationError(EmailConnectionError):
    """Authentication errors for email sources"""
    pass


class EmailRetrievalError(EmailSourceError):
    """Errors during email retrieval"""
    pass


class EmailProcessingError(EmailIntelligenceError):
    """Errors during email processing"""
    pass


class EmailParsingError(EmailProcessingError):
    """Errors during email parsing"""
    pass


class AttachmentError(EmailProcessingError):
    """Errors related to email attachments"""
    pass


class AttachmentSizeError(AttachmentError):
    """Attachment exceeds size limits"""
    pass


class AttachmentTypeError(AttachmentError):
    """Unsupported attachment type"""
    pass


class EmailAnalysisError(EmailIntelligenceError):
    """Errors during email analysis"""
    pass


class EmailStorageError(EmailIntelligenceError):
    """Errors during email storage"""
    pass


class EmailNotFoundError(EmailStorageError):
    """Email not found in storage"""
    pass


class DuplicateEmailError(EmailStorageError):
    """Duplicate email detected"""
    pass


class SchedulerError(EmailIntelligenceError):
    """Scheduler-related errors"""
    pass


class SecurityError(EmailIntelligenceError):
    """Security-related errors"""
    pass


class EncryptionError(SecurityError):
    """Encryption/decryption errors"""
    pass


class AccessDeniedError(SecurityError):
    """Access denied errors"""
    pass
