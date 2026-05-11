"""
Custom exceptions for LLM module
"""


class LLMError(Exception):
    """Base exception for LLM-related errors"""
    pass


class OllamaNotInstalledError(LLMError):
    """Raised when Ollama is not installed"""
    def __init__(self, message: str = "Ollama is not installed. Please install Ollama first."):
        self.message = message
        super().__init__(self.message)


class OllamaNotRunningError(LLMError):
    """Raised when Ollama server is not running"""
    def __init__(self, message: str = "Ollama server is not running. Please start Ollama."):
        self.message = message
        super().__init__(self.message)


class ModelNotFoundError(LLMError):
    """Raised when a requested model is not available"""
    def __init__(self, model_id: str, message: str = None):
        self.model_id = model_id
        self.message = message or f"Model '{model_id}' not found or not downloaded."
        super().__init__(self.message)


class ModelDownloadError(LLMError):
    """Raised when model download fails"""
    def __init__(self, model_id: str, reason: str = None):
        self.model_id = model_id
        self.reason = reason
        self.message = f"Failed to download model '{model_id}': {reason or 'Unknown error'}"
        super().__init__(self.message)


class LLMTimeoutError(LLMError):
    """Raised when LLM operation times out"""
    def __init__(self, operation: str, timeout: int):
        self.operation = operation
        self.timeout = timeout
        self.message = f"LLM operation '{operation}' timed out after {timeout} seconds."
        super().__init__(self.message)


class LLMRateLimitError(LLMError):
    """Raised when rate limit is exceeded"""
    def __init__(self, message: str = "Rate limit exceeded. Please try again later."):
        self.message = message
        super().__init__(self.message)


class InvalidModelConfigError(LLMError):
    """Raised when model configuration is invalid"""
    def __init__(self, model_id: str, reason: str):
        self.model_id = model_id
        self.reason = reason
        self.message = f"Invalid configuration for model '{model_id}': {reason}"
        super().__init__(self.message)


class LLMProcessingError(LLMError):
    """Raised when LLM processing fails"""
    def __init__(self, operation: str, details: str = None):
        self.operation = operation
        self.details = details
        self.message = f"LLM processing failed for operation '{operation}': {details or 'Unknown error'}"
        super().__init__(self.message)


class InsufficientResourcesError(LLMError):
    """Raised when system resources are insufficient"""
    def __init__(self, required: str, available: str = None):
        self.required = required
        self.available = available
        self.message = f"Insufficient resources. Required: {required}, Available: {available or 'Unknown'}"
        super().__init__(self.message)
