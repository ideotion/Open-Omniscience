#!/usr/bin/env python3
"""
EML File Import Tool for Open Omniscience

This script imports .eml (email) files into the Open Omniscience database,
treating them as articles from newsletters. It supports:
- Single .eml file import
- Batch import of multiple .eml files from a directory
- Automatic detection of newsletter sources
- Duplicate detection
- Integration with existing article database

Usage:
    # Import single file
    python scripts/import_eml.py path/to/email.eml

    # Import directory of files
    python scripts/import_eml.py /path/to/eml/directory/

    # Import with specific source
    python scripts/import_eml.py /path/to/eml/directory/ --source "My Newsletter"

    # Import with custom options
    python scripts/import_eml.py /path/to/eml/ --source "Tech News" --category "Technology" --priority 5

Author: Open Omniscience Team
License: GNU GPLv3
"""

import argparse
import email
import hashlib
import logging
import sys
import traceback
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("import_eml.log")],
)
logger = logging.getLogger(__name__)


def parse_eml_file(file_path: Path) -> dict[str, Any] | None:
    """
    Parse an .eml file and extract structured data.

    Args:
        file_path: Path to the .eml file

    Returns:
        Dictionary with parsed email data, or None if parsing failed
    """
    try:
        logger.info(f"Parsing EML file: {file_path}")

        # Read the file
        with open(file_path, "rb") as f:
            raw_email = f.read()

        # Parse the email
        email_message = email.message_from_bytes(raw_email, policy=email.policy.default)

        # Extract headers
        subject = decode_header(email_message.get("Subject", "No Subject"))
        if isinstance(subject, tuple):
            subject = subject[0]
            if isinstance(subject, bytes):
                subject = subject.decode("utf-8", errors="replace")

        from_header = decode_header(email_message.get("From", "unknown"))
        if isinstance(from_header, tuple):
            from_header = from_header[0]
            if isinstance(from_header, bytes):
                from_header = from_header.decode("utf-8", errors="replace")

        # Extract date
        date_str = email_message.get("Date")
        published_at = None
        if date_str:
            try:
                from email.utils import parsedate_to_datetime

                published_at = parsedate_to_datetime(date_str)
            except Exception as e:
                logger.warning(f"Failed to parse date: {e}")
                published_at = datetime.utcnow()

        if published_at is None:
            published_at = datetime.utcnow()

        # Extract To, Cc, Bcc
        to_addresses = []
        if email_message.get("To"):
            to_addresses = [addr[1] for addr in email.utils.getaddresses([email_message.get("To")])]

        cc_addresses = []
        if email_message.get("Cc"):
            cc_addresses = [addr[1] for addr in email.utils.getaddresses([email_message.get("Cc")])]

        # Extract message ID
        message_id = email_message.get("Message-ID", "")

        # Extract content
        plain_text = ""
        html_content = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue

                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")

                    if content_type == "text/plain":
                        plain_text = text if not plain_text else plain_text + "\n" + text
                    elif content_type == "text/html":
                        html_content = text if not html_content else html_content + "\n" + text

                except Exception as e:
                    logger.warning(f"Failed to decode part: {e}")
                    continue
        else:
            # Simple email
            content_type = email_message.get_content_type()
            payload = email_message.get_payload(decode=True)

            if payload:
                charset = email_message.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")

                if content_type == "text/plain":
                    plain_text = text
                elif content_type == "text/html":
                    html_content = text
                else:
                    plain_text = text

        # Clean up content
        plain_text = plain_text.strip()
        html_content = html_content.strip()

        # If no plain text but we have HTML, extract text from HTML
        if not plain_text and html_content:
            from bs4 import BeautifulSoup

            try:
                soup = BeautifulSoup(html_content, "html.parser")
                plain_text = soup.get_text()
            except Exception:
                plain_text = html_content

        # Calculate content hash for duplicate detection
        content_for_hash = f"{subject}{from_header}{plain_text}".encode()
        content_hash = hashlib.sha256(content_for_hash).hexdigest()

        # Extract sender domain for source identification
        sender_domain = None
        if from_header:
            if "<" in from_header:
                # Format: "Name <email@domain.com>"
                email_part = from_header.split("<")[-1].split(">")[0].strip()
            else:
                email_part = from_header.strip()

            if "@" in email_part:
                sender_domain = email_part.split("@")[-1]

        # Determine if this is a newsletter
        is_newsletter = False
        if subject:
            newsletter_keywords = [
                "newsletter",
                "update",
                "digest",
                "bulletin",
                "brief",
                "weekly",
                "daily",
                "monthly",
            ]
            subject_lower = subject.lower()
            is_newsletter = any(keyword in subject_lower for keyword in newsletter_keywords)

        # Extract links from content
        links = []
        if plain_text:
            import re

            url_pattern = re.compile(
                r"https?://[\w\-]+(\.[\w\-]+)+([\w\-.,@?^=%&:/~+#]*[\w\-@?^=%&/~+#])?"
            )
            links = url_pattern.findall(plain_text)
            links = [f"{match[0]}{match[1]}" for match in links]

        return {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "subject": subject,
            "from_address": from_header,
            "from_domain": sender_domain,
            "to_addresses": to_addresses,
            "cc_addresses": cc_addresses,
            "message_id": message_id,
            "date": published_at,
            "plain_text": plain_text,
            "html_content": html_content,
            "content_hash": content_hash,
            "content_length": len(plain_text.encode("utf-8")),
            "is_newsletter": is_newsletter,
            "links": links,
            "raw_email": raw_email,
        }

    except Exception as e:
        logger.error(f"Failed to parse EML file {file_path}: {e}")
        logger.error(traceback.format_exc())
        return None


def extract_source_name(from_address: str, subject: str) -> str:
    """
    Extract a source name from the email address and subject.

    Args:
        from_address: Sender email address
        subject: Email subject

    Returns:
        Proposed source name
    """
    # Try to extract domain from email
    if "<" in from_address:
        email_part = from_address.split("<")[-1].split(">")[0].strip()
    else:
        email_part = from_address.strip()

    if "@" in email_part:
        domain = email_part.split("@")[-1]
        # Remove common email provider domains
        common_providers = [
            "gmail.com",
            "yahoo.com",
            "outlook.com",
            "hotmail.com",
            "aol.com",
            "protonmail.com",
        ]
        if domain not in common_providers:
            # Use domain as source name
            return domain.split(".")[-2].capitalize() if "." in domain else domain.capitalize()

    # Try to extract from subject
    if subject:
        # Look for common patterns
        patterns = [
            r"\[?([A-Za-z\s]+) Newsletter\]?",
            r"([A-Za-z\s]+) Update",
            r"From: ([A-Za-z\s]+)",
            r"([A-Za-z\s]+) Digest",
        ]
        import re

        for pattern in patterns:
            match = re.search(pattern, subject, re.IGNORECASE)
            if match:
                return match.group(1).strip()

    # Default to a generic name
    return "Newsletter Source"


def create_or_get_source(session, source_name: str, source_type: str = "email", **kwargs) -> Any:
    """
    Create or get a source from the database.

    Args:
        session: SQLAlchemy session
        source_name: Name of the source
        source_type: Type of source
        kwargs: Additional source attributes

    Returns:
        Source object
    """
    try:
        from src.database.models import Source

        # Check if source already exists
        existing_source = session.query(Source).filter_by(name=source_name).first()
        if existing_source:
            return existing_source

        # Create new source
        source = Source(
            name=source_name,
            domain=kwargs.get("domain", source_name.lower().replace(" ", "-")),
            rss_url=kwargs.get("rss_url"),
            rate_limit_ms=60000,  # 1 minute
            enabled=True,
            priority=kwargs.get("priority", 5),
            tags=kwargs.get("tags", "email,newsletter"),
            reliability_score=7,
            language=kwargs.get("language", "en"),
            region=kwargs.get("region", "global"),
            country=kwargs.get("country", "US"),
            source_type=source_type,
            update_frequency=kwargs.get("update_frequency", 1440),  # 24 hours in minutes
            cacheability=False,
        )

        session.add(source)
        session.flush()
        session.refresh(source)

        logger.info(f"Created new source: {source_name} (ID: {source.id})")
        return source

    except Exception as e:
        logger.error(f"Failed to create/get source {source_name}: {e}")
        return None


def create_article_from_email(
    session, email_data: dict[str, Any], source: Any, **kwargs
) -> Any | None:
    """
    Create an article from email data.

    Args:
        session: SQLAlchemy session
        email_data: Parsed email data
        source: Source object
        kwargs: Additional article attributes

    Returns:
        Article object or None
    """
    try:
        from src.database.models import Article, ArticleLink

        # Generate article data
        article_data = {
            "title": email_data.get("subject", "No Subject"),
            "url": kwargs.get("url"),
            "source_id": source.id,
            "content": email_data.get("plain_text", ""),
            "html_content": email_data.get("html_content", ""),
            "published_at": email_data.get("date", datetime.utcnow()),
            "scraped_at": datetime.utcnow(),
            "content_hash": email_data.get("content_hash"),
            "language": kwargs.get("language", "en"),
            "author": email_data.get("from_address"),
            "is_newsletter": email_data.get("is_newsletter", True),
            "metadata": {
                "email_from": email_data.get("from_address"),
                "email_to": email_data.get("to_addresses"),
                "email_subject": email_data.get("subject"),
                "email_message_id": email_data.get("message_id"),
                "email_links": email_data.get("links", []),
                "imported_from_eml": True,
                "eml_file": email_data.get("file_name"),
                "from_domain": email_data.get("from_domain"),
            },
        }

        # Check for duplicate
        existing_article = (
            session.query(Article).filter_by(content_hash=article_data["content_hash"]).first()
        )
        if existing_article:
            logger.info(
                f"Duplicate article detected (hash: {article_data['content_hash']}), skipping"
            )
            return existing_article

        # Create article
        article = Article(**article_data)
        session.add(article)
        session.flush()
        session.refresh(article)

        # Create article link if URL exists
        if article_data.get("url"):
            article_link = ArticleLink(
                article_id=article.id, url=article_data["url"], link_type="canonical"
            )
            session.add(article_link)

        logger.info(f"Created article from email: {article.title} (ID: {article.id})")
        return article

    except Exception as e:
        logger.error(f"Failed to create article from email: {e}")
        logger.error(traceback.format_exc())
        return None


def import_eml_file(
    file_path: Path, session, source_name: str | None = None, **kwargs
) -> tuple[bool, str | None]:
    """
    Import a single .eml file.

    Args:
        file_path: Path to the .eml file
        session: SQLAlchemy session
        source_name: Optional source name override
        kwargs: Additional options

    Returns:
        Tuple of (success, message)
    """
    try:
        # Parse the EML file
        email_data = parse_eml_file(file_path)
        if not email_data:
            return False, f"Failed to parse {file_path.name}"

        # Determine source name
        if not source_name:
            source_name = extract_source_name(email_data["from_address"], email_data["subject"])

        # Create or get source
        source = create_or_get_source(
            session,
            source_name,
            source_type="email",
            domain=email_data.get("from_domain"),
            priority=kwargs.get("priority", 5),
            tags=kwargs.get("tags", "email,newsletter,imported"),
        )

        if not source:
            return False, f"Failed to create/get source: {source_name}"

        # Create article from email
        article = create_article_from_email(
            session,
            email_data,
            source,
            url=kwargs.get("url"),
            language=kwargs.get("language"),
            priority=kwargs.get("priority"),
        )

        if not article:
            return False, f"Failed to create article from {file_path.name}"

        # Commit changes
        session.commit()

        logger.info(f"Successfully imported {file_path.name} -> Article ID: {article.id}")
        return True, f"Imported {file_path.name} as article {article.id}"

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to import {file_path.name}: {e}")
        logger.error(traceback.format_exc())
        return False, f"Failed to import {file_path.name}: {str(e)}"


def import_eml_directory(directory_path: Path, session, **kwargs) -> dict[str, Any]:
    """
    Import all .eml files from a directory.

    Args:
        directory_path: Path to directory containing .eml files
        session: SQLAlchemy session
        kwargs: Options to pass to individual imports

    Returns:
        Dictionary with import statistics
    """
    results = {"total": 0, "success": 0, "failed": 0, "errors": [], "articles_created": []}

    # Find all .eml files
    eml_files = list(directory_path.glob("**/*.eml")) + list(directory_path.glob("**/*.EML"))

    if not eml_files:
        logger.warning(f"No .eml files found in {directory_path}")
        return results

    results["total"] = len(eml_files)
    logger.info(f"Found {len(eml_files)} .eml files to import")

    # Process each file
    for i, eml_file in enumerate(eml_files, 1):
        logger.info(f"Processing {i}/{len(eml_files)}: {eml_file.name}")

        try:
            success, message = import_eml_file(eml_file, session, **kwargs)

            if success:
                results["success"] += 1
                results["articles_created"].append(message)
                logger.info(f"  ✓ {message}")
            else:
                results["failed"] += 1
                results["errors"].append(f"{eml_file.name}: {message}")
                logger.error(f"  ✗ {message}")

        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{eml_file.name}: {str(e)}")
            logger.error(f"  ✗ Unexpected error: {e}")
            session.rollback()

    return results


def main():
    """Main entry point for the EML import tool."""
    parser = argparse.ArgumentParser(
        description="Import .eml files into Open Omniscience database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import single file
  python scripts/import_eml.py path/to/email.eml

  # Import directory of files
  python scripts/import_eml.py /path/to/eml/directory/

  # Import with specific source
  python scripts/import_eml.py /path/to/eml/ --source "My Newsletter"

  # Import with custom options
  python scripts/import_eml.py /path/to/eml/ --source "Tech News" --category "Technology" --priority 5
        """,
    )

    parser.add_argument(
        "path", nargs="+", help="Path to .eml file or directory containing .eml files"
    )

    parser.add_argument(
        "--source",
        "-s",
        type=str,
        default=None,
        help="Source name to use (auto-detected if not provided)",
    )

    parser.add_argument(
        "--priority",
        "-p",
        type=int,
        default=5,
        help="Priority for imported articles (1-10, default: 5)",
    )

    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default="en",
        help="Language for imported articles (default: en)",
    )

    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Test import without saving to database"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively search subdirectories (default: True)",
    )

    args = parser.parse_args()

    # Set up logging level
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Initialize database session
    try:
        from src.database.models import Article, Base, Source, engine, get_session

        # Create tables if they don't exist
        Base.metadata.create_all(engine)

        session = get_session()

        logger.info("Database connection established")
        logger.info(f"Starting EML import from: {args.path}")

        # Process each path
        all_results = {"total_files": 0, "success": 0, "failed": 0, "errors": []}

        for path_str in args.path:
            path = Path(path_str)

            if path.is_file() and path.suffix.lower() in [".eml"]:
                # Single file
                logger.info(f"Importing single file: {path}")
                success, message = import_eml_file(
                    path,
                    session,
                    source_name=args.source,
                    priority=args.priority,
                    language=args.language,
                )

                if success:
                    all_results["success"] += 1
                    logger.info(f"✓ {message}")
                else:
                    all_results["failed"] += 1
                    all_results["errors"].append(message)
                    logger.error(f"✗ {message}")

            elif path.is_dir():
                # Directory
                logger.info(f"Importing directory: {path}")
                results = import_eml_directory(
                    path,
                    session,
                    source_name=args.source,
                    priority=args.priority,
                    language=args.language,
                )

                all_results["total_files"] += results["total"]
                all_results["success"] += results["success"]
                all_results["failed"] += results["failed"]
                all_results["errors"].extend(results["errors"])
            else:
                logger.error(f"Invalid path: {path}")
                all_results["failed"] += 1

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("IMPORT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total files processed: {all_results['total_files']}")
        logger.info(f"Successfully imported: {all_results['success']}")
        logger.info(f"Failed: {all_results['failed']}")

        if all_results["errors"]:
            logger.info("\nErrors:")
            for error in all_results["errors"][:10]:  # Show first 10 errors
                logger.info(f"  - {error}")
            if len(all_results["errors"]) > 10:
                logger.info(f"  ... and {len(all_results['errors']) - 10} more errors")

        # Commit if not dry run
        if not args.dry_run:
            session.commit()
            logger.info("\nChanges committed to database")
        else:
            session.rollback()
            logger.info("\nDry run complete - no changes saved to database")

        session.close()

    except ImportError as e:
        logger.error(f"Failed to import database modules: {e}")
        logger.error("Please ensure you're running from the project root directory")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
