"""
Email Intelligence Module for Open-Omniscience

This module provides email retrieval, archive, and analysis capabilities
for extending Open-Omniscience's capacity to public and private newsletter intelligence.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from .config import EmailConfig
from .models import EmailSource, EmailMessage, EmailAttachment

__version__ = "0.1.0"
__all__ = [
    'EmailConfig',
    'EmailSource', 
    'EmailMessage',
    'EmailAttachment',
]

# Module initialization
print(f"Email Intelligence Module v{__version__} loaded")
