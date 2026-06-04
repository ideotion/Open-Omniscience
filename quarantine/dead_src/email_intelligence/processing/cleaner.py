"""
Email Cleaner for Email Intelligence

Handles cleaning and normalizing email content.
"""

from typing import Optional, List
import re
import logging

logger = logging.getLogger(__name__)


class EmailCleaner:
    """
    Cleans and normalizes email content.
    
    This class handles:
    - Removing boilerplate (signatures, disclaimers)
    - Stripping HTML (optional)
    - Normalizing whitespace
    - Detecting and handling forwarded messages
    - Extracting quoted text
    - Removing tracking pixels and analytics
    """
    
    def __init__(self):
        """Initialize the email cleaner"""
        # Patterns for detecting and removing common email boilerplate
        self.signature_patterns = [
            # Common signature separators
            r'--\s*$',
            r'--\s*\n',
            r'\n--\s*\n',
            r'\n\s*--\s*\n',
            # "Sent from my iPhone" etc.
            r'\n\s*Sent from my \w+\s*\n',
            r'\n\s*Sent from my \w+\s*$',
            # "On [date], [name] wrote:"
            r'\n\s*On .+? wrote:\s*\n',
            # "From: [email]"
            r'\n\s*From: .+?\n',
            # "To: [email]"
            r'\n\s*To: .+?\n',
            # "Subject: [subject]"
            r'\n\s*Subject: .+?\n',
            # "Date: [date]"
            r'\n\s*Date: .+?\n',
        ]
        
        # Patterns for detecting forwarded messages
        self.forward_patterns = [
            r'\n\s*---------- Forwarded message ----------\s*\n',
            r'\n\s*Begin forwarded message:\s*\n',
            r'\n\s*From: .+?\n\s*Date: .+?\n\s*Subject: .+?\n\s*To: .+?\n',
            r'\n\s*--- Original Message ---\s*\n',
            r'\n\s*Original Message:\s*\n',
        ]
        
        # Patterns for detecting quoted text
        self.quote_patterns = [
            r'\n> .+?\n',  # > quoted text
            r'\nOn .+? wrote:\s*\n> .+?\n',
        ]
        
        # Patterns for tracking pixels and analytics
        self.tracking_patterns = [
            r'<img[^>]*src=["\']?[^"\']*\.(gif|png|jpg|jpeg|webp)["\']?[^>]*>',
            r'<img[^>]*width=["\']?1["\']?[^>]*height=["\']?1["\']?[^>]*>',
            r'<img[^>]*style=["\']?display:\s*none["\']?[^>]*>',
            r'<img[^>]*alt=["\']?["\']?[^>]*>',
        ]
    
    def clean_text(self, text: str) -> str:
        """
        Clean plain text email content.
        
        Args:
            text: Raw plain text content
            
        Returns:
            Cleaned text content
        """
        if not text:
            return ""
        
        try:
            cleaned = text
            
            # Remove tracking pixels and analytics (text versions)
            cleaned = self._remove_tracking_text(cleaned)
            
            # Remove common email signatures
            cleaned = self._remove_signatures(cleaned)
            
            # Handle forwarded messages
            cleaned = self._handle_forwarded_messages(cleaned)
            
            # Normalize whitespace
            cleaned = self._normalize_whitespace(cleaned)
            
            # Remove excessive newlines
            cleaned = self._remove_excessive_newlines(cleaned)
            
            return cleaned.strip()
            
        except Exception as e:
            logger.error(f"Failed to clean text: {str(e)}")
            return text
    
    def clean_html(self, html: str) -> str:
        """
        Clean HTML email content.
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML content
        """
        if not html:
            return ""
        
        try:
            cleaned = html
            
            # Remove tracking pixels and analytics
            cleaned = self._remove_tracking_html(cleaned)
            
            # Remove style tags and attributes
            cleaned = self._remove_styles(cleaned)
            
            # Remove script tags
            cleaned = re.sub(r'<script[^>]*>.*?</script>', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove comments
            cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)
            
            # Remove empty tags
            cleaned = re.sub(r'<[^>]+>\s*</[^>]+>', '', cleaned)
            
            # Remove excessive whitespace in HTML
            cleaned = re.sub(r'>\s+<', '><', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned)
            
            return cleaned.strip()
            
        except Exception as e:
            logger.error(f"Failed to clean HTML: {str(e)}")
            return html
    
    def extract_main_content(self, text: str, html: Optional[str] = None) -> str:
        """
        Extract the main content from email, removing boilerplate.
        
        Args:
            text: Plain text content
            html: Optional HTML content (used if available)
            
        Returns:
            Main content with boilerplate removed
        """
        if html:
            # If we have HTML, try to extract main content from it
            main_content = self._extract_main_content_from_html(html)
            if main_content:
                return main_content
        
        # Otherwise, use text content
        return self.clean_text(text)
    
    def _remove_signatures(self, text: str) -> str:
        """Remove email signatures from text"""
        try:
            lines = text.split('\n')
            cleaned_lines = []
            in_signature = False
            
            for line in lines:
                # Check for signature separators
                if re.match(r'--\s*$', line.strip()):
                    in_signature = True
                    continue
                
                # If we're in a signature, check if this line looks like a signature
                if in_signature:
                    # Common signature patterns
                    if (re.match(r'\s*$', line) or  # Empty line
                        re.match(r'\s*[-=]+\s*$', line) or  # Horizontal rule
                        re.match(r'\s*[A-Za-z]+ [A-Za-z]+\s*$', line) or  # Name only
                        re.match(r'\s*[A-Za-z]+ [A-Za-z]+\s*\n\s*[^@]+@[^@]+\s*$', line) or  # Name and email
                        re.match(r'\s*[^@]+@[^@]+\s*$', line) or  # Email only
                        re.match(r'\s*Sent from my \w+\s*$', line) or  # "Sent from my iPhone"
                        re.match(r'\s*Please consider the environment\s*$', line)):  # Common disclaimer
                        continue
                    else:
                        # End of signature
                        in_signature = False
                        cleaned_lines.append(line)
                else:
                    cleaned_lines.append(line)
            
            return '\n'.join(cleaned_lines)
            
        except Exception as e:
            logger.error(f"Failed to remove signatures: {str(e)}")
            return text
    
    def _handle_forwarded_messages(self, text: str) -> str:
        """Handle forwarded messages in text"""
        try:
            # Check for forwarded message patterns
            for pattern in self.forward_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    # Extract the original message (after the forward header)
                    parts = re.split(pattern, text, flags=re.IGNORECASE)
                    if len(parts) > 1:
                        # Return the last part (the original message)
                        return parts[-1].strip()
            
            return text
            
        except Exception as e:
            logger.error(f"Failed to handle forwarded messages: {str(e)}")
            return text
    
    def _remove_tracking_text(self, text: str) -> str:
        """Remove tracking text from content"""
        try:
            # Remove common tracking patterns
            cleaned = text
            
            # Remove single-pixel tracking (text versions)
            cleaned = re.sub(r'\[?1x1\]?', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\[?pixel\]?', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\[?tracking\]?', '', cleaned, flags=re.IGNORECASE)
            
            # Remove tracking URLs
            cleaned = re.sub(r'https?://[^/]+/pixel\.gif', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'https?://[^/]+/tracking\.gif', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'https?://[^/]+/1x1\.png', '', cleaned, flags=re.IGNORECASE)
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to remove tracking text: {str(e)}")
            return text
    
    def _remove_tracking_html(self, html: str) -> str:
        """Remove tracking elements from HTML"""
        try:
            cleaned = html
            
            # Remove tracking pixels
            for pattern in self.tracking_patterns:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            
            # Remove common tracking services
            tracking_services = [
                'google-analytics', 'googlesyndication', 'doubleclick',
                'facebook.com/tr', 'twitter.com/i/ads', 'linkedin.com/analytics',
                'mailchimp.com', 'substack.com', 'convertkit.com'
            ]
            
            for service in tracking_services:
                cleaned = re.sub(
                    rf'<img[^>]*src=["\']?[^"\']*{service}[^"\']*["\']?[^>]*>',
                    '',
                    cleaned,
                    flags=re.IGNORECASE
                )
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to remove tracking HTML: {str(e)}")
            return html
    
    def _remove_styles(self, html: str) -> str:
        """Remove style tags and attributes from HTML"""
        try:
            # Remove style tags
            cleaned = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove style attributes
            cleaned = re.sub(r'\s*style=["\'][^"\']*["\']', '', cleaned, flags=re.IGNORECASE)
            
            # Remove class attributes (optional)
            cleaned = re.sub(r'\s*class=["\'][^"\']*["\']', '', cleaned, flags=re.IGNORECASE)
            
            # Remove inline styles
            cleaned = re.sub(r':\s*[^;]+;', '', cleaned)
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to remove styles: {str(e)}")
            return html
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace in text"""
        try:
            # Replace multiple spaces with single space
            cleaned = re.sub(r'[ \t]+', ' ', text)
            
            # Replace multiple newlines with single newline
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            
            # Remove leading/trailing whitespace from each line
            lines = cleaned.split('\n')
            cleaned_lines = [line.strip() for line in lines]
            
            return '\n'.join(cleaned_lines)
            
        except Exception as e:
            logger.error(f"Failed to normalize whitespace: {str(e)}")
            return text
    
    def _remove_excessive_newlines(self, text: str) -> str:
        """Remove excessive newlines from text"""
        try:
            # Replace more than 2 consecutive newlines with 2 newlines
            cleaned = re.sub(r'\n{3,}', '\n\n', text)
            
            # Remove newlines at the start and end
            cleaned = cleaned.strip('\n')
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to remove excessive newlines: {str(e)}")
            return text
    
    def _extract_main_content_from_html(self, html: str) -> Optional[str]:
        """Extract main content from HTML"""
        try:
            # Try to find the main content in common HTML structures
            
            # Look for <body> tag
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
            if body_match:
                html = body_match.group(1)
            
            # Remove common boilerplate elements
            boilerplate_tags = [
                'header', 'footer', 'nav', 'navigation', 'sidebar',
                'menu', 'script', 'style', 'noscript'
            ]
            
            for tag in boilerplate_tags:
                html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove remaining HTML tags
            text = re.sub(r'<[^>]+>', ' ', html)
            
            # Clean the extracted text
            return self.clean_text(text)
            
        except Exception as e:
            logger.error(f"Failed to extract main content from HTML: {str(e)}")
            return None
