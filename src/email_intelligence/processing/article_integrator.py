"""
Article Integrator for Email Intelligence

Handles the integration of email messages with the existing article database.
This ensures that emails are treated as articles with full compatibility for
search, analysis, and exploration.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from sqlalchemy.orm import Session

from ..models import EmailMessage, EmailSource, EmailAttachment
from ..exceptions import EmailProcessingError, EmailStorageError

logger = logging.getLogger(__name__)


class ArticleIntegrator:
    """
    Integrates email messages with the article database.
    
    This class handles:
    - Creating linked Article records for emails
    - Updating existing articles with email metadata
    - Managing relationships between emails and articles
    - Ensuring data consistency between email and article databases
    """
    
    def __init__(self, session: Optional[Session] = None):
        """
        Initialize the ArticleIntegrator.
        
        Args:
            session: SQLAlchemy session (optional, will create new if not provided)
        """
        self.session = session
    
    def integrate_email(self, email_message: EmailMessage) -> Optional[Dict[str, Any]]:
        """
        Integrate an email message with the article database.
        
        This method:
        1. Creates a linked Source if the email source doesn't have one
        2. Creates a linked Article record for the email
        3. Links the email to the article
        4. Creates article links for any URLs in the email
        5. Creates article keywords for email keywords
        
        Args:
            email_message: EmailMessage instance to integrate
            
        Returns:
            Dictionary with integration results, or None if failed
        """
        try:
            # Ensure we have a database session
            if not self.session:
                from src.database.models import get_session
                self.session = get_session()
            
            # Step 1: Ensure the email source has a linked Source
            if email_message.email_source and not email_message.email_source.linked_source_id:
                self._create_linked_source(email_message.email_source)
                self.session.commit()
            
            # Step 2: Create a linked Article for the email
            article = self._create_linked_article(email_message)
            if not article:
                logger.warning(f"Failed to create linked article for email {email_message.id}")
                return None
            
            # Link the email to the article
            email_message.linked_article = article
            email_message.linked_article_id = article.id
            
            # Step 3: Create article links for URLs in the email
            self._create_article_links(article, email_message)
            
            # Step 4: Create article keywords for email keywords
            self._create_article_keywords(article, email_message)
            
            # Step 5: Process attachments and create links if they reference external content
            self._process_attachments(article, email_message)
            
            # Save changes
            self.session.add(article)
            self.session.add(email_message)
            self.session.commit()
            
            logger.info(f"Successfully integrated email {email_message.id} with article {article.id}")
            
            return {
                'email_id': email_message.id,
                'article_id': article.id,
                'success': True,
                'message': 'Email successfully integrated with article database'
            }
            
        except Exception as e:
            if self.session:
                self.session.rollback()
            logger.error(f"Failed to integrate email {email_message.id}: {str(e)}")
            raise EmailProcessingError(f"Article integration failed: {str(e)}")
    
    def _create_linked_source(self, email_source: EmailSource) -> Optional[Any]:
        """
        Create a linked Source in the main database for an email source.
        
        Args:
            email_source: EmailSource instance
            
        Returns:
            Created Source instance, or None if failed
        """
        try:
            from src.database.models import Source
            
            # Check if a source with this domain already exists
            domain = f"email-{email_source.source_type}-{email_source.id}"
            existing_source = self.session.query(Source).filter_by(domain=domain).first()
            
            if existing_source:
                email_source.linked_source_id = existing_source.id
                return existing_source
            
            # Create a new source
            source = Source(
                name=email_source.name,
                domain=domain,
                rss_url=email_source.config.get('rss_url') if email_source.source_type == 'rss' else None,
                rate_limit_ms=60000,  # 1 minute rate limit for email sources
                enabled=email_source.enabled,
                priority=2,
                tags=f"email,{email_source.source_type},newsletter",
                reliability_score=7,  # Default reliability for email sources
                language="en",  # Default language
                region="global",
                country="US",
                source_type="email",
                update_frequency=email_source.interval_minutes,
                cacheability=False
            )
            
            self.session.add(source)
            self.session.flush()  # Get the ID
            
            # Link the email source to the new source
            email_source.linked_source_id = source.id
            
            logger.info(f"Created linked source {source.id} for email source {email_source.id}")
            return source
            
        except Exception as e:
            logger.error(f"Failed to create linked source for email source {email_source.id}: {str(e)}")
            return None
    
    def _create_linked_article(self, email_message: EmailMessage) -> Optional[Any]:
        """
        Create a linked Article in the main database for an email message.
        
        Args:
            email_message: EmailMessage instance
            
        Returns:
            Created Article instance, or None if failed
        """
        try:
            from src.database.models import Article
            from src.utils.security import canonicalize_url
            
            # Generate a unique URL for this email
            email_url = f"email://{email_message.email_source.source_type}/{email_message.email_source_id}/{email_message.id}"
            canonical_url = canonicalize_url(email_url)
            
            # Check if an article with this URL already exists
            existing_article = self.session.query(Article).filter_by(url=email_url).first()
            if existing_article:
                return existing_article
            
            # Create the article
            article = Article(
                url=email_url,
                canonical_url=canonical_url,
                source_id=email_message.email_source.linked_source_id if email_message.email_source and email_message.email_source.linked_source_id else None,
                title=email_message.subject or "No Subject",
                content=email_message.plain_text or email_message.html_content or "",
                published_at=email_message.date_sent or datetime.utcnow(),
                language=email_message.language or "en",
                hash=email_message.content_hash or email_message.calculate_content_hash(),
                region="global",  # Can be updated based on analysis
                country="US",    # Can be updated based on analysis
                author=email_message.from_address,
            )
            
            self.session.add(article)
            self.session.flush()  # Get the ID
            
            logger.info(f"Created linked article {article.id} for email {email_message.id}")
            return article
            
        except Exception as e:
            logger.error(f"Failed to create linked article for email {email_message.id}: {str(e)}")
            return None
    
    def _create_article_links(self, article: Any, email_message: EmailMessage):
        """
        Create ArticleLink records for URLs found in the email content.
        
        Args:
            article: Article instance
            email_message: EmailMessage instance
        """
        try:
            from src.database.models import ArticleLink
            from src.utils.security import canonicalize_url
            import re
            
            # Find all URLs in the email content
            content = email_message.plain_text or email_message.html_content or ""
            urls = re.findall(r'https?://[^\s"\'<>)\]+', content)
            
            for url in urls:
                try:
                    # Check if this URL already exists for this article
                    existing_link = self.session.query(ArticleLink).filter_by(
                        article_id=article.id, 
                        url=url
                    ).first()
                    
                    if existing_link:
                        continue
                    
                    # Create normalized URL
                    normalized_url = canonicalize_url(url)
                    
                    # Create the article link
                    link = ArticleLink(
                        article_id=article.id,
                        url=url,
                        normalized_url=normalized_url,
                        link_text="",  # Can be extracted from HTML if available
                        position=content.find(url),  # Character position
                        link_type="external",
                        classification="reference",  # Default classification
                        is_followable=True,
                        is_working=True,  # Assume working until checked
                    )
                    
                    self.session.add(link)
                    
                except Exception as e:
                    logger.warning(f"Failed to create article link for URL {url}: {str(e)}")
                    continue
            
            logger.debug(f"Created {len(urls)} article links for article {article.id}")
            
        except Exception as e:
            logger.error(f"Failed to create article links for article {article.id}: {str(e)}")
    
    def _create_article_keywords(self, article: Any, email_message: EmailMessage):
        """
        Create keyword associations for the article based on email keywords.
        
        Args:
            article: Article instance
            email_message: EmailMessage instance
        """
        try:
            from src.database.models import Keyword, ArticleKeyword
            
            if not email_message.keywords:
                return
            
            for keyword_text in email_message.keywords:
                try:
                    # Normalize the keyword
                    normalized_keyword = keyword_text.lower().strip()
                    
                    # Find or create the keyword
                    keyword = self.session.query(Keyword).filter_by(
                        normalized_term=normalized_keyword
                    ).first()
                    
                    if not keyword:
                        keyword = Keyword(
                            term=keyword_text,
                            normalized_term=normalized_keyword,
                            language=email_message.language or "en",
                            frequency=0,
                            is_entity=False,  # Can be updated based on analysis
                            entity_type=None,
                        )
                        self.session.add(keyword)
                        self.session.flush()
                    
                    # Check if this keyword is already associated with the article
                    existing_assoc = self.session.query(ArticleKeyword).filter_by(
                        article_id=article.id,
                        keyword_id=keyword.id
                    ).first()
                    
                    if existing_assoc:
                        # Update frequency
                        existing_assoc.frequency += 1
                        existing_assoc.updated_at = datetime.utcnow()
                    else:
                        # Create new association
                        assoc = ArticleKeyword(
                            article_id=article.id,
                            keyword_id=keyword.id,
                            frequency=1,
                            first_position=0,  # Can be calculated from content
                            last_position=0,
                            relevance_score=0.5,  # Default relevance
                        )
                        self.session.add(assoc)
                    
                    # Update keyword frequency
                    keyword.frequency += 1
                    keyword.updated_at = datetime.utcnow()
                    
                except Exception as e:
                    logger.warning(f"Failed to process keyword {keyword_text}: {str(e)}")
                    continue
            
            logger.debug(f"Processed {len(email_message.keywords)} keywords for article {article.id}")
            
        except Exception as e:
            logger.error(f"Failed to create article keywords for article {article.id}: {str(e)}")
    
    def _process_attachments(self, article: Any, email_message: EmailMessage):
        """
        Process email attachments and create links if they reference external content.
        
        Args:
            article: Article instance
            email_message: EmailMessage instance
        """
        try:
            from src.database.models import ArticleLink, ExternalSource, SourceArticle
            from src.utils.security import canonicalize_url
            import re
            
            for attachment in email_message.attachments:
                try:
                    # Check if the attachment contains URLs
                    if attachment.extracted_text:
                        urls = re.findall(r'https?://[^\s"\'<>)\]+', attachment.extracted_text)
                        
                        for url in urls:
                            try:
                                # Check if this URL already exists for this article
                                existing_link = self.session.query(ArticleLink).filter_by(
                                    article_id=article.id,
                                    url=url
                                ).first()
                                
                                if existing_link:
                                    continue
                                
                                # Create normalized URL
                                normalized_url = canonicalize_url(url)
                                
                                # Create the article link
                                link = ArticleLink(
                                    article_id=article.id,
                                    url=url,
                                    normalized_url=normalized_url,
                                    link_text=attachment.filename,
                                    position=0,  # Position within attachment
                                    link_type="external",
                                    classification="source",  # Attachments often reference sources
                                    is_followable=True,
                                    is_working=True,
                                )
                                
                                self.session.add(link)
                                
                            except Exception as e:
                                logger.warning(f"Failed to create attachment link for URL {url}: {str(e)}")
                                continue
                    
                    # Link the attachment to the article (optional)
                    # This can be used for tracking which attachments belong to which articles
                    
                except Exception as e:
                    logger.warning(f"Failed to process attachment {attachment.id}: {str(e)}")
                    continue
            
            logger.debug(f"Processed {len(email_message.attachments)} attachments for article {article.id}")
            
        except Exception as e:
            logger.error(f"Failed to process attachments for article {article.id}: {str(e)}")
    
    def update_article_metadata(self, email_message: EmailMessage) -> bool:
        """
        Update the linked article with metadata from the email message.
        
        This method updates the article with analysis results from the email,
        such as entities, sentiment, language, etc.
        
        Args:
            email_message: EmailMessage instance with updated analysis
            
        Returns:
            bool: True if update successful
        """
        try:
            if not email_message.linked_article_id:
                logger.warning(f"Email {email_message.id} has no linked article to update")
                return False
            
            # Get the linked article
            from src.database.models import Article
            article = self.session.query(Article).get(email_message.linked_article_id)
            
            if not article:
                logger.warning(f"Linked article {email_message.linked_article_id} not found")
                return False
            
            # Update article with email metadata
            if email_message.language:
                article.language = email_message.language
            
            # Note: Other metadata like entities, keywords, etc. are handled separately
            # through the keyword and link systems
            
            article.updated_at = datetime.utcnow()
            self.session.commit()
            
            logger.info(f"Updated article {article.id} with email metadata")
            return True
            
        except Exception as e:
            if self.session:
                self.session.rollback()
            logger.error(f"Failed to update article metadata for email {email_message.id}: {str(e)}")
            return False
    
    def get_article_from_email(self, email_id: str) -> Optional[Any]:
        """
        Get the linked Article for an email message.
        
        Args:
            email_id: ID of the email message
            
        Returns:
            Article instance, or None if not found
        """
        try:
            # Get the email message
            email_message = self.session.query(EmailMessage).get(email_id)
            
            if not email_message or not email_message.linked_article_id:
                return None
            
            from src.database.models import Article
            return self.session.query(Article).get(email_message.linked_article_id)
            
        except Exception as e:
            logger.error(f"Failed to get article for email {email_id}: {str(e)}")
            return None
    
    def search_emails_by_article_criteria(self, **kwargs) -> List[EmailMessage]:
        """
        Search emails using article-compatible criteria.
        
        This method allows searching emails using the same criteria as articles,
        such as language, date range, keywords, etc.
        
        Args:
            **kwargs: Search criteria (language, date_from, date_to, keywords, etc.)
            
        Returns:
            List of EmailMessage instances matching the criteria
        """
        try:
            query = self.session.query(EmailMessage)
            
            # Apply filters based on kwargs
            if 'language' in kwargs and kwargs['language']:
                query = query.filter(EmailMessage.language == kwargs['language'])
            
            if 'date_from' in kwargs and kwargs['date_from']:
                query = query.filter(EmailMessage.date_sent >= kwargs['date_from'])
            
            if 'date_to' in kwargs and kwargs['date_to']:
                query = query.filter(EmailMessage.date_sent <= kwargs['date_to'])
            
            if 'keywords' in kwargs and kwargs['keywords']:
                # Filter by any of the keywords
                for keyword in kwargs['keywords']:
                    query = query.filter(EmailMessage.keywords.any(keyword))
            
            if 'source_id' in kwargs and kwargs['source_id']:
                query = query.filter(EmailMessage.email_source_id == kwargs['source_id'])
            
            if 'is_newsletter' in kwargs:
                query = query.filter(EmailMessage.is_newsletter == kwargs['is_newsletter'])
            
            if 'is_processed' in kwargs:
                query = query.filter(EmailMessage.is_processed == kwargs['is_processed'])
            
            return query.all()
            
        except Exception as e:
            logger.error(f"Failed to search emails: {str(e)}")
            return []
    
    def get_email_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about integrated emails.
        
        Returns:
            Dictionary with email integration statistics
        """
        try:
            # Count total emails
            total_emails = self.session.query(EmailMessage).count()
            
            # Count processed emails
            processed_emails = self.session.query(EmailMessage).filter(
                EmailMessage.is_processed == True
            ).count()
            
            # Count emails with linked articles
            linked_emails = self.session.query(EmailMessage).filter(
                EmailMessage.linked_article_id.isnot(None)
            ).count()
            
            # Count by source type
            from sqlalchemy import func
            source_type_counts = self.session.query(
                EmailSource.source_type,
                func.count(EmailMessage.id).label('count')
            ).join(
                EmailMessage, EmailSource.id == EmailMessage.email_source_id
            ).group_by(EmailSource.source_type).all()
            
            # Count by language
            language_counts = self.session.query(
                EmailMessage.language,
                func.count(EmailMessage.id).label('count')
            ).filter(
                EmailMessage.language.isnot(None)
            ).group_by(EmailMessage.language).all()
            
            return {
                'total_emails': total_emails,
                'processed_emails': processed_emails,
                'linked_emails': linked_emails,
                'source_type_counts': {row.source_type: row.count for row in source_type_counts},
                'language_counts': {row.language: row.count for row in language_counts},
            }
            
        except Exception as e:
            logger.error(f"Failed to get email statistics: {str(e)}")
            return {}
