"""
Email Parser for Email Intelligence

Handles parsing of raw email data into structured format.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import email
from email.header import decode_header
import re
import logging

logger = logging.getLogger(__name__)


class EmailParser:
    """
    Parses raw email data into structured format.
    
    This class handles:
    - Parsing email headers (From, To, Subject, Date, etc.)
    - Extracting plain text and HTML content
    - Handling multipart messages
    - Extracting attachments
    - Normalizing encoding
    """
    
    def parse_email(self, raw_email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse raw email data into structured format.
        
        Args:
            raw_email_data: Dictionary with raw email data
            
        Returns:
            Dictionary with parsed email data
        """
        try:
            # If we have raw email bytes, parse them
            if 'raw_email' in raw_email_data:
                return self._parse_raw_email(raw_email_data['raw_email'])
            
            # Otherwise, use the provided structured data
            return self._normalize_parsed_data(raw_email_data)
            
        except Exception as e:
            logger.error(f"Failed to parse email: {str(e)}")
            # Return minimal data
            return {
                'subject': raw_email_data.get('subject', 'No Subject'),
                'from_address': raw_email_data.get('from_address', 'unknown'),
                'plain_text': raw_email_data.get('plain_text', ''),
                'html_content': raw_email_data.get('html_content', ''),
                'content_hash': self._calculate_hash(raw_email_data)
            }
    
    def _parse_raw_email(self, raw_email: bytes) -> Dict[str, Any]:
        """
        Parse raw email bytes into structured format.
        
        Args:
            raw_email: Raw email bytes
            
        Returns:
            Dictionary with parsed email data
        """
        try:
            # Parse the email message
            email_message = email.message_from_bytes(raw_email, policy=email.policy.default)
            
            # Extract basic headers
            parsed_data = {
                'message_id': self._decode_header(email_message.get('Message-ID')),
                'thread_id': self._decode_header(email_message.get('Thread-Index') or 
                                               email_message.get('References')),
                'in_reply_to': self._decode_header(email_message.get('In-Reply-To')),
                'from_address': self._decode_header(email_message.get('From')),
                'to_addresses': self._parse_address_list(email_message.get('To')),
                'cc_addresses': self._parse_address_list(email_message.get('Cc')),
                'bcc_addresses': self._parse_address_list(email_message.get('Bcc')),
                'subject': self._decode_header(email_message.get('Subject')),
                'date_sent': self._parse_date(email_message.get('Date')),
                'content_type': email_message.get_content_type(),
                'charset': email_message.get_content_charset() or 'utf-8',
                'plain_text': '',
                'html_content': '',
                'attachments': [],
            }
            
            # Process email parts
            self._process_email_parts(email_message, parsed_data)
            
            # Calculate content hash
            parsed_data['content_hash'] = self._calculate_hash(parsed_data)
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"Failed to parse raw email: {str(e)}")
            return {
                'subject': 'Parsing Error',
                'from_address': 'unknown',
                'plain_text': str(e),
                'html_content': '',
                'content_hash': self._calculate_hash({'error': str(e)})
            }
    
    def _process_email_parts(self, msg: email.message.Message, parsed_data: Dict[str, Any]):
        """
        Process email parts (recursively for multipart messages).
        
        Args:
            msg: email.message.Message instance
            parsed_data: Dictionary to store parsed data
        """
        content_disposition = msg.get('Content-Disposition', '')
        
        # Check if this is an attachment
        if 'attachment' in content_disposition:
            attachment = self._process_attachment(msg, parsed_data)
            if attachment:
                parsed_data['attachments'].append(attachment)
            return
        
        # Process content based on type
        content_type = msg.get_content_type()
        
        if content_type == 'text/plain':
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    parsed_data['plain_text'] += payload.decode(parsed_data['charset'], errors='replace') + '\n'
                except:
                    parsed_data['plain_text'] += payload.decode('utf-8', errors='replace') + '\n'
        
        elif content_type == 'text/html':
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    parsed_data['html_content'] += payload.decode(parsed_data['charset'], errors='replace')
                except:
                    parsed_data['html_content'] += payload.decode('utf-8', errors='replace')
        
        elif content_type.startswith('multipart/'):
            # Recursively process multipart parts
            for part in msg.get_payload():
                self._process_email_parts(part, parsed_data)
        
        else:
            # Treat as attachment
            attachment = self._process_attachment(msg, parsed_data)
            if attachment:
                parsed_data['attachments'].append(attachment)
    
    def _process_attachment(self, msg: email.message.Message, parsed_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an email attachment.
        
        Args:
            msg: email.message.Message instance
            
        Returns:
            Dictionary with attachment data, or None if error
        """
        try:
            filename = msg.get_filename()
            if not filename:
                # Try to get from Content-Disposition
                content_disposition = msg.get('Content-Disposition', '')
                if 'filename=' in content_disposition:
                    filename = content_disposition.split('filename=')[1].strip('"')
            
            if not filename:
                filename = f"attachment_{len(parsed_data.get('attachments', [])) + 1}"
            
            payload = msg.get_payload(decode=True)
            if not payload:
                return None
            
            attachment = {
                'filename': filename,
                'content_type': msg.get_content_type(),
                'file_size': len(payload),
                'file_hash': self._calculate_hash(payload),
                'payload': payload,
            }
            
            return attachment
            
        except Exception as e:
            logger.error(f"Error processing attachment: {str(e)}")
            return None
    
    def _normalize_parsed_data(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize already parsed email data.
        
        Args:
            parsed_data: Dictionary with parsed email data
            
        Returns:
            Dictionary with normalized data
        """
        try:
            normalized = parsed_data.copy()
            
            # Ensure required fields exist
            normalized.setdefault('subject', 'No Subject')
            normalized.setdefault('from_address', 'unknown')
            normalized.setdefault('plain_text', '')
            normalized.setdefault('html_content', '')
            normalized.setdefault('to_addresses', [])
            normalized.setdefault('cc_addresses', [])
            normalized.setdefault('bcc_addresses', [])
            normalized.setdefault('attachments', [])
            
            # Calculate content hash if not provided
            if 'content_hash' not in normalized:
                normalized['content_hash'] = self._calculate_hash(normalized)
            
            return normalized
            
        except Exception as e:
            logger.error(f"Failed to normalize parsed data: {str(e)}")
            return parsed_data
    
    def _decode_header(self, header: str) -> str:
        """
        Decode MIME encoded header.
        
        Args:
            header: Raw header string
            
        Returns:
            Decoded header string
        """
        if not header:
            return ""
        
        try:
            decoded = decode_header(header)
            return " ".join(
                str(part[0], part[1] or 'utf-8') if isinstance(part[0], bytes) else part[0]
                for part in decoded
            )
        except:
            return header
    
    def _parse_address_list(self, address_header: str) -> List[str]:
        """
        Parse an email address list header.
        
        Args:
            address_header: Raw address header string
            
        Returns:
            List of email addresses
        """
        if not address_header:
            return []
        
        # Use email.utils.parseaddr for proper parsing
        try:
            from email.utils import parseaddr
            addresses = []
            for addr in address_header.split(','):
                addr = addr.strip()
                if addr:
                    # parseaddr returns (name, email) tuple
                    _, email_addr = parseaddr(addr)
                    if email_addr:
                        addresses.append(email_addr)
            return addresses
        except:
            # Fallback to simple parsing
            return [addr.strip() for addr in address_header.split(',') if addr.strip()]
    
    def _parse_date(self, date_header: str) -> Optional[datetime]:
        """
        Parse an email date header.
        
        Args:
            date_header: Raw date header string
            
        Returns:
            datetime object, or None if parsing fails
        """
        if not date_header:
            return None
        
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_header)
        except Exception:
            return None
    
    def _calculate_hash(self, data) -> str:
        """
        Calculate SHA-256 hash of data.
        
        Args:
            data: Data to hash (bytes, string, or dict)
            
        Returns:
            Hexadecimal hash string
        """
        import hashlib
        
        if isinstance(data, bytes):
            content = data
        elif isinstance(data, dict):
            # Convert dict to string representation
            content = str(data).encode('utf-8')
        else:
            content = str(data).encode('utf-8')
        
        return hashlib.sha256(content).hexdigest()
