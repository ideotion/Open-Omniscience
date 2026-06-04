"""
IMAP Client for Email Retrieval

Handles connecting to IMAP servers and fetching emails.
"""

import imaplib
import email
import email.policy
from email.header import decode_header
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import ssl
import socket
import logging

from ..config import EmailSourceConfig
from ..models import EmailSource, EmailMessage, EmailAttachment
from ..exceptions import (
    EmailConnectionError, 
    EmailAuthenticationError, 
    EmailRetrievalError,
    EmailSourceError
)

logger = logging.getLogger(__name__)


class IMAPClient:
    """
    IMAP client for retrieving emails from IMAP servers.
    
    Supports SSL/TLS connections, authentication, and email fetching.
    """
    
    def __init__(self, source: EmailSource):
        """
        Initialize IMAP client with email source configuration.
        
        Args:
            source: EmailSource database model instance
        """
        self.source = source
        self.server = source.get_server()
        self.port = source.get_port()
        self.username = source.get_username()
        self.password = self._get_password()
        self.is_secure = source.is_secure
        self.folders = source.folders or ['INBOX']
        self.max_emails = source.max_emails_per_fetch or 50
        
        self.connection = None
        self._connected = False
    
    def _get_password(self) -> Optional[str]:
        """Get password from configuration"""
        config = self.source.config or {}
        password = config.get('password')
        
        # If password starts with ${ and ends with }, try to get from environment
        if password and password.startswith('${') and password.endswith('}'):
            import os
            env_var = password[2:-1]
            return os.environ.get(env_var)
        
        return password
    
    def connect(self) -> bool:
        """
        Connect to the IMAP server.
        
        Returns:
            bool: True if connection successful, False otherwise
        
        Raises:
            EmailConnectionError: If connection fails
            EmailAuthenticationError: If authentication fails
        """
        if self._connected and self.connection:
            return True
        
        try:
            # Create SSL context if secure
            if self.is_secure:
                context = ssl.create_default_context()
                self.connection = imaplib.IMAP4_SSL(
                    self.server, 
                    self.port, 
                    ssl_context=context
                )
            else:
                self.connection = imaplib.IMAP4(self.server, self.port)
            
            # Login
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            elif self.username:
                # Try anonymous login
                self.connection.login(self.username)
            else:
                raise EmailAuthenticationError("No username provided")
            
            self._connected = True
            logger.info(f"Connected to IMAP server: {self.server}:{self.port}")
            return True
            
        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            if 'authentication' in error_msg.lower() or 'login' in error_msg.lower():
                raise EmailAuthenticationError(f"IMAP authentication failed: {error_msg}")
            else:
                raise EmailConnectionError(f"IMAP connection error: {error_msg}")
        except socket.timeout:
            raise EmailConnectionError(f"Connection timeout to {self.server}:{self.port}")
        except socket.gaierror:
            raise EmailConnectionError(f"Could not resolve hostname: {self.server}")
        except Exception as e:
            raise EmailConnectionError(f"Unexpected connection error: {str(e)}")
    
    def disconnect(self):
        """Disconnect from the IMAP server"""
        if self.connection and self._connected:
            try:
                self.connection.logout()
                self._connected = False
                logger.info(f"Disconnected from IMAP server: {self.server}")
            except Exception as e:
                logger.warning(f"Error disconnecting from IMAP: {str(e)}")
        
        self.connection = None
        self._connected = False
    
    def list_folders(self) -> List[str]:
        """
        List all available folders on the server.
        
        Returns:
            List of folder names
        """
        self._ensure_connected()
        
        try:
            status, folders = self.connection.list()
            if status != 'OK':
                raise EmailRetrievalError(f"Failed to list folders: {folders}")
            
            folder_list = []
            for folder in folders:
                # Parse folder line: b'(\HasNoChildren) "/" "INBOX"'
                if isinstance(folder, bytes):
                    folder = folder.decode('utf-8')
                if isinstance(folder, str):
                    # Extract folder name from the response
                    parts = folder.split('"')
                    if len(parts) >= 2:
                        folder_name = parts[-2]
                        folder_list.append(folder_name)
            
            return folder_list
            
        except Exception as e:
            raise EmailRetrievalError(f"Error listing folders: {str(e)}")
    
    def select_folder(self, folder: str) -> bool:
        """
        Select a specific folder.
        
        Args:
            folder: Name of the folder to select
            
        Returns:
            bool: True if selection successful
        """
        self._ensure_connected()
        
        try:
            status, response = self.connection.select(folder)
            if status != 'OK':
                raise EmailRetrievalError(f"Failed to select folder {folder}: {response}")
            
            logger.debug(f"Selected folder: {folder}")
            return True
            
        except Exception as e:
            raise EmailRetrievalError(f"Error selecting folder {folder}: {str(e)}")
    
    def fetch_emails(self, folder: str, since_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Fetch emails from a specific folder.
        
        Args:
            folder: Name of the folder to fetch from
            since_date: Only fetch emails received after this date
            
        Returns:
            List of email data dictionaries
        """
        self._ensure_connected()
        
        try:
            # Select the folder
            self.select_folder(folder)
            
            # Build search criteria
            search_criteria = 'ALL'
            if since_date:
                # Format date for IMAP search (e.g., "01-Jan-2024")
                imap_date = since_date.strftime('%d-%b-%Y')
                search_criteria = f'(SINCE "{imap_date}")'
            
            # Search for emails
            status, message_ids = self.connection.search(None, search_criteria)
            if status != 'OK':
                raise EmailRetrievalError(f"Search failed: {message_ids}")
            
            email_list = []
            message_id_list = message_ids[0].split()
            
            # Limit the number of emails to fetch
            message_id_list = message_id_list[:self.max_emails]
            
            for msg_id in message_id_list:
                try:
                    email_data = self._fetch_single_email(msg_id)
                    if email_data:
                        email_list.append(email_data)
                except Exception as e:
                    logger.error(f"Error fetching email {msg_id}: {str(e)}")
                    continue
            
            return email_list
            
        except Exception as e:
            raise EmailRetrievalError(f"Error fetching emails from {folder}: {str(e)}")
    
    def _fetch_single_email(self, msg_id: bytes) -> Optional[Dict[str, Any]]:
        """
        Fetch a single email by its message ID.
        
        Args:
            msg_id: IMAP message ID
            
        Returns:
            Dictionary containing email data, or None if error
        """
        try:
            # Fetch the email (RFC822 format includes headers and body)
            status, msg_data = self.connection.fetch(msg_id, '(RFC822)')
            if status != 'OK':
                logger.error(f"Failed to fetch message {msg_id}: {msg_data}")
                return None
            
            # Parse the email
            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email, policy=email.policy.default)
            
            # Extract email data
            email_data = self._parse_email_message(email_message)
            email_data['imap_msg_id'] = msg_id.decode('utf-8')
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error parsing email {msg_id}: {str(e)}")
            return None
    
    def _parse_email_message(self, email_message: email.message.Message) -> Dict[str, Any]:
        """
        Parse an email message into a structured dictionary.
        
        Args:
            email_message: email.message.Message instance
            
        Returns:
            Dictionary with parsed email data
        """
        def decode_mime_header(header):
            """Decode MIME encoded header"""
            if not header:
                return ""
            decoded = decode_header(header)
            return " ".join(
                str(part[0], part[1] or 'utf-8') if isinstance(part[0], bytes) else part[0]
                for part in decoded
            )
        
        email_data = {
            'message_id': decode_mime_header(email_message.get('Message-ID')),
            'thread_id': decode_mime_header(email_message.get('Thread-Index') or email_message.get('References')),
            'in_reply_to': decode_mime_header(email_message.get('In-Reply-To')),
            'from_address': decode_mime_header(email_message.get('From')),
            'to_addresses': self._parse_address_list(email_message.get('To')),
            'cc_addresses': self._parse_address_list(email_message.get('Cc')),
            'bcc_addresses': self._parse_address_list(email_message.get('Bcc')),
            'subject': decode_mime_header(email_message.get('Subject')),
            'date_sent': self._parse_date(email_message.get('Date')),
            'date_received': datetime.utcnow(),
            'content_type': email_message.get_content_type(),
            'charset': email_message.get_content_charset() or 'utf-8',
            'plain_text': '',
            'html_content': '',
            'attachments': [],
        }
        
        # Process email parts
        self._process_email_parts(email_message, email_data)
        
        # Calculate content hash
        content = f"{email_data['from_address']}{email_data['subject']}{email_data['plain_text']}{email_data['html_content']}"
        email_data['content_hash'] = self._calculate_hash(content)
        
        return email_data
    
    def _process_email_parts(self, msg: email.message.Message, email_data: Dict[str, Any], is_attachment: bool = False):
        """
        Process email parts (recursively for multipart messages).
        
        Args:
            msg: email.message.Message instance
            email_data: Dictionary to store parsed data
            is_attachment: Whether this part is an attachment
        """
        content_disposition = msg.get('Content-Disposition', '')
        
        # Check if this is an attachment
        if 'attachment' in content_disposition or is_attachment:
            attachment = self._process_attachment(msg, email_data)
            if attachment:
                email_data['attachments'].append(attachment)
            return
        
        # Process content based on type
        content_type = msg.get_content_type()
        
        if content_type == 'text/plain':
            payload = msg.get_payload(decode=True)
            if payload:
                email_data['plain_text'] += payload.decode(email_data['charset'], errors='replace') + '\n'
        
        elif content_type == 'text/html':
            payload = msg.get_payload(decode=True)
            if payload:
                email_data['html_content'] += payload.decode(email_data['charset'], errors='replace')
        
        elif content_type.startswith('multipart/'):
            # Recursively process multipart parts
            for part in msg.get_payload():
                self._process_email_parts(part, email_data)
        
        else:
            # Treat as attachment
            attachment = self._process_attachment(msg, email_data)
            if attachment:
                email_data['attachments'].append(attachment)
    
    def _process_attachment(self, msg: email.message.Message, email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an email attachment.
        
        Args:
            msg: email.message.Message instance
            email_data: Parent email data
            
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
                filename = f"attachment_{len(email_data['attachments']) + 1}"
            
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
        
        # Simple parsing - for more complex cases, use email.utils.parseaddr
        addresses = []
        for addr in address_header.split(','):
            addr = addr.strip()
            if addr:
                addresses.append(addr)
        
        return addresses
    
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
            # Use email.utils.parsedate_to_datetime for standard email dates
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_header)
        except Exception:
            return None
    
    def _calculate_hash(self, data) -> str:
        """
        Calculate SHA-256 hash of data.
        
        Args:
            data: Data to hash (bytes or string)
            
        Returns:
            Hexadecimal hash string
        """
        import hashlib
        
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        return hashlib.sha256(data).hexdigest()
    
    def _ensure_connected(self):
        """Ensure we are connected to the server"""
        if not self._connected:
            self.connect()
    
    def test_connection(self) -> bool:
        """
        Test the connection to the IMAP server.
        
        Returns:
            bool: True if connection test successful
        """
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False
    
    def get_folder_stats(self, folder: str) -> Dict[str, Any]:
        """
        Get statistics for a folder.
        
        Args:
            folder: Name of the folder
            
        Returns:
            Dictionary with folder statistics
        """
        self._ensure_connected()
        
        try:
            self.select_folder(folder)
            
            # Get folder status
            status, data = self.connection.status(folder, '(MESSAGES UNSEEN RECENT)')
            if status != 'OK':
                return {'error': str(data)}
            
            # Parse the response
            stats = {}
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            # Extract values from response like: b'INBOX (MESSAGES 123 UNSEEN 45 RECENT 5)'
            parts = data.split()
            for i, part in enumerate(parts):
                if part == 'MESSAGES':
                    stats['total_messages'] = int(parts[i+1])
                elif part == 'UNSEEN':
                    stats['unseen_messages'] = int(parts[i+1])
                elif part == 'RECENT':
                    stats['recent_messages'] = int(parts[i+1])
            
            stats['folder'] = folder
            return stats
            
        except Exception as e:
            return {'error': str(e)}
