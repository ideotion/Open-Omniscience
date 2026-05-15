"""
Email Processing Pipeline

Main pipeline for processing retrieved emails, including:
- Parsing and cleaning
- Duplicate detection
- Article integration
- Analysis coordination
- Storage management
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from sqlalchemy.orm import Session

from ..models import EmailMessage, EmailSource, EmailAttachment, EmailMessageStatus
from ..exceptions import EmailProcessingError, EmailStorageError, DuplicateEmailError
from .article_integrator import ArticleIntegrator
from .duplicate_detector import DuplicateDetector
from .parser import EmailParser
from .cleaner import EmailCleaner
from .attachment_handler import AttachmentHandler

logger = logging.getLogger(__name__)


class EmailProcessingPipeline:
    """
    Main pipeline for processing email messages.
    
    This pipeline coordinates all processing steps:
    1. Parse raw email data
    2. Clean and normalize content
    3. Check for duplicates
    4. Handle attachments
    5. Integrate with article database
    6. Store processed data
    
    The pipeline ensures that emails are treated as articles with full compatibility
    for search, analysis, and exploration.
    """
    
    def __init__(self, session: Optional[Session] = None):
        """
        Initialize the processing pipeline.
        
        Args:
            session: SQLAlchemy session (optional)
        """
        self.session = session
        self.article_integrator = ArticleIntegrator(session)
        self.duplicate_detector = DuplicateDetector(session)
        self.parser = EmailParser()
        self.cleaner = EmailCleaner()
        self.attachment_handler = AttachmentHandler(session)
    
    def process_email(self, raw_email_data: Dict[str, Any], source: EmailSource) -> Optional[EmailMessage]:
        """
        Process a raw email through the full pipeline.
        
        Args:
            raw_email_data: Dictionary with raw email data from retrieval
            source: EmailSource instance that provided the email
            
        Returns:
            Processed EmailMessage instance, or None if processing failed
        """
        try:
            # Ensure we have a database session
            if not self.session:
                from src.database.models import get_session
                self.session = get_session()
                self.article_integrator.session = self.session
                self.duplicate_detector.session = self.session
                self.attachment_handler.session = self.session
            
            logger.info(f"Starting processing of email from source {source.name}")
            
            # Step 1: Parse the raw email data
            email_message = self._parse_email(raw_email_data, source)
            if not email_message:
                logger.warning("Failed to parse email")
                return None
            
            # Step 2: Check for duplicates
            if self._is_duplicate(email_message):
                logger.info(f"Duplicate email detected: {email_message.content_hash}")
                return None
            
            # Step 3: Clean and normalize content
            self._clean_email(email_message)
            
            # Step 4: Handle attachments
            self._process_attachments(email_message, raw_email_data)
            
            # Step 5: Save the email message
            self.session.add(email_message)
            self.session.flush()  # Get the ID
            
            # Step 6: Integrate with article database
            integration_result = self.article_integrator.integrate_email(email_message)
            if not integration_result or not integration_result.get('success'):
                logger.warning(f"Failed to integrate email {email_message.id} with article database")
            
            # Step 7: Mark as processed
            email_message.mark_as_processed()
            
            # Save all changes
            self.session.commit()
            
            logger.info(f"Successfully processed email {email_message.id}")
            return email_message
            
        except DuplicateEmailError as e:
            logger.info(f"Duplicate email skipped: {str(e)}")
            return None
        except Exception as e:
            if self.session:
                self.session.rollback()
            logger.error(f"Failed to process email: {str(e)}")
            raise EmailProcessingError(f"Processing pipeline failed: {str(e)}")
    
    def process_batch(self, raw_emails: List[Dict[str, Any]], source: EmailSource) -> Dict[str, Any]:
        """
        Process a batch of raw emails through the pipeline.
        
        Args:
            raw_emails: List of raw email data dictionaries
            source: EmailSource instance
            
        Returns:
            Dictionary with processing statistics
        """
        results = {
            'total': len(raw_emails),
            'successful': 0,
            'duplicates': 0,
            'failed': 0,
            'processed_emails': [],
            'errors': []
        }
        
        try:
            for i, raw_email in enumerate(raw_emails):
                try:
                    email_message = self.process_email(raw_email, source)
                    
                    if email_message:
                        results['successful'] += 1
                        results['processed_emails'].append(email_message.id)
                    else:
                        # Check if it was a duplicate
                        try:
                            content_hash = self._calculate_content_hash(raw_email)
                            if self.duplicate_detector.is_duplicate(content_hash):
                                results['duplicates'] += 1
                            else:
                                results['failed'] += 1
                        except:
                            results['failed'] += 1
                    
                    # Log progress
                    if (i + 1) % 10 == 0:
                        logger.info(f"Processed {i + 1}/{len(raw_emails)} emails")
                        
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append({
                        'index': i,
                        'error': str(e),
                        'email_data': raw_email.get('subject', 'Unknown')
                    })
                    logger.error(f"Failed to process email {i}: {str(e)}")
            
            logger.info(f"Batch processing complete: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Batch processing failed: {str(e)}")
            return results
    
    def _parse_email(self, raw_email_data: Dict[str, Any], source: EmailSource) -> Optional[EmailMessage]:
        """
        Parse raw email data into an EmailMessage instance.
        
        Args:
            raw_email_data: Dictionary with raw email data
            source: EmailSource instance
            
        Returns:
            EmailMessage instance, or None if parsing failed
        """
        try:
            # Use the parser to extract structured data
            parsed_data = self.parser.parse_email(raw_email_data)
            
            # Create EmailMessage instance
            email_message = EmailMessage(
                email_source_id=source.id,
                message_id=parsed_data.get('message_id'),
                thread_id=parsed_data.get('thread_id'),
                in_reply_to=parsed_data.get('in_reply_to'),
                from_address=parsed_data.get('from_address'),
                to_addresses=parsed_data.get('to_addresses', []),
                cc_addresses=parsed_data.get('cc_addresses', []),
                bcc_addresses=parsed_data.get('bcc_addresses', []),
                subject=parsed_data.get('subject'),
                date_sent=parsed_data.get('date_sent'),
                date_received=datetime.utcnow(),
                plain_text=parsed_data.get('plain_text', ''),
                html_content=parsed_data.get('html_content', ''),
                content_type=parsed_data.get('content_type'),
                charset=parsed_data.get('charset'),
                content_length=len(parsed_data.get('plain_text', '') + parsed_data.get('html_content', '')),
                content_hash=parsed_data.get('content_hash'),
                status=EmailMessageStatus.PROCESSING,
                is_newsletter=self._detect_newsletter(parsed_data),
            )
            
            return email_message
            
        except Exception as e:
            logger.error(f"Failed to parse email: {str(e)}")
            return None
    
    def _is_duplicate(self, email_message: EmailMessage) -> bool:
        """
        Check if an email is a duplicate.
        
        Args:
            email_message: EmailMessage instance
            
        Returns:
            bool: True if the email is a duplicate
        """
        try:
            if not email_message.content_hash:
                email_message.content_hash = email_message.calculate_content_hash()
            
            return self.duplicate_detector.is_duplicate(email_message.content_hash)
            
        except Exception as e:
            logger.error(f"Failed to check for duplicates: {str(e)}")
            return False
    
    def _clean_email(self, email_message: EmailMessage):
        """
        Clean and normalize email content.
        
        Args:
            email_message: EmailMessage instance to clean
        """
        try:
            # Clean the plain text content
            if email_message.plain_text:
                cleaned_text = self.cleaner.clean_text(email_message.plain_text)
                email_message.plain_text = cleaned_text
            
            # Clean the HTML content
            if email_message.html_content:
                cleaned_html = self.cleaner.clean_html(email_message.html_content)
                email_message.html_content = cleaned_html
            
            # Recalculate content hash after cleaning
            email_message.content_hash = email_message.calculate_content_hash()
            
            # Update content length
            email_message.content_length = len(
                (email_message.plain_text or '') + 
                (email_message.html_content or '')
            )
            
        except Exception as e:
            logger.error(f"Failed to clean email: {str(e)}")
    
    def _process_attachments(self, email_message: EmailMessage, raw_email_data: Dict[str, Any]):
        """
        Process email attachments.
        
        Args:
            email_message: EmailMessage instance
            raw_email_data: Raw email data containing attachments
        """
        try:
            # Get attachments from raw data
            raw_attachments = raw_email_data.get('attachments', [])
            
            for raw_attachment in raw_attachments:
                try:
                    # Process the attachment
                    attachment = self.attachment_handler.process_attachment(
                        raw_attachment, 
                        email_message
                    )
                    
                    if attachment:
                        email_message.attachments.append(attachment)
                        
                except Exception as e:
                    logger.warning(f"Failed to process attachment {raw_attachment.get('filename', 'unknown')}: {str(e)}")
                    continue
            
        except Exception as e:
            logger.error(f"Failed to process attachments: {str(e)}")
    
    def _detect_newsletter(self, parsed_data: Dict[str, Any]) -> bool:
        """
        Detect if an email is a newsletter.
        
        Args:
            parsed_data: Parsed email data
            
        Returns:
            bool: True if the email appears to be a newsletter
        """
        try:
            # Check for common newsletter indicators
            subject = parsed_data.get('subject', '').lower()
            from_address = parsed_data.get('from_address', '').lower()
            content = parsed_data.get('plain_text', '').lower()
            
            # Newsletter keywords in subject
            newsletter_keywords = [
                'newsletter', 'update', 'digest', 'bulletin', 'briefing',
                'weekly', 'daily', 'monthly', 'roundup', 'summary'
            ]
            
            # Newsletter domains
            newsletter_domains = [
                'substack.com', 'mailchimp.com', 'revue.com', 'convertkit.com',
                'tinyletter.com', 'campaign-monitor.com', 'sendgrid.net'
            ]
            
            # Check subject for newsletter keywords
            if any(keyword in subject for keyword in newsletter_keywords):
                return True
            
            # Check from address for newsletter domains
            if any(domain in from_address for domain in newsletter_domains):
                return True
            
            # Check content for unsubscribe links
            if 'unsubscribe' in content or 'manage preferences' in content:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to detect newsletter: {str(e)}")
            return False
    
    def _calculate_content_hash(self, raw_email_data: Dict[str, Any]) -> str:
        """
        Calculate content hash from raw email data.
        
        Args:
            raw_email_data: Raw email data
            
        Returns:
            str: SHA-256 hash of the content
        """
        import hashlib
        
        content = f"{raw_email_data.get('from_address', '')}"
        content += f"{raw_email_data.get('subject', '')}"
        content += f"{raw_email_data.get('plain_text', '')}"
        content += f"{raw_email_data.get('html_content', '')}"
        
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def reprocess_email(self, email_id: str) -> bool:
        """
        Reprocess an existing email.
        
        This can be used to re-analyze emails with updated analysis algorithms
        or to fix processing errors.
        
        Args:
            email_id: ID of the email to reprocess
            
        Returns:
            bool: True if reprocessing successful
        """
        try:
            # Get the email message
            email_message = self.session.query(EmailMessage).get(email_id)
            if not email_message:
                logger.warning(f"Email {email_id} not found")
                return False
            
            # Reset processing status
            email_message.status = EmailMessageStatus.PROCESSING
            email_message.is_processed = False
            email_message.processing_error = None
            email_message.processing_attempts = 0
            
            # Re-run analysis (if implemented)
            # This would include entity extraction, keyword extraction, etc.
            # For now, we'll just re-integrate with the article database
            
            # Update the linked article if it exists
            if email_message.linked_article_id:
                self.article_integrator.update_article_metadata(email_message)
            else:
                # Create a new linked article
                self.article_integrator.integrate_email(email_message)
            
            # Mark as processed
            email_message.mark_as_processed()
            
            self.session.commit()
            
            logger.info(f"Reprocessed email {email_id}")
            return True
            
        except Exception as e:
            if self.session:
                self.session.rollback()
            logger.error(f"Failed to reprocess email {email_id}: {str(e)}")
            return False
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about email processing.
        
        Returns:
            Dictionary with processing statistics
        """
        try:
            # Get counts by status
            from sqlalchemy import func
            
            status_counts = self.session.query(
                EmailMessage.status,
                func.count(EmailMessage.id).label('count')
            ).group_by(EmailMessage.status).all()
            
            # Get processing times
            processed_emails = self.session.query(EmailMessage).filter(
                EmailMessage.status == EmailMessageStatus.PROCESSED,
                EmailMessage.processed_at.isnot(None),
                EmailMessage.created_at.isnot(None)
            ).all()
            
            processing_times = []
            for email in processed_emails:
                if email.processed_at and email.created_at:
                    time_diff = (email.processed_at - email.created_at).total_seconds()
                    processing_times.append(time_diff)
            
            avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
            
            return {
                'status_counts': {row.status: row.count for row in status_counts},
                'total_emails': sum(row.count for row in status_counts),
                'average_processing_time_seconds': avg_processing_time,
                'integration_stats': self.article_integrator.get_email_statistics()
            }
            
        except Exception as e:
            logger.error(f"Failed to get processing statistics: {str(e)}")
            return {}
