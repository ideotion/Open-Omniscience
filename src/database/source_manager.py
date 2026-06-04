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
Source Manager for Open Omniscience

This module provides comprehensive source management functionality including:
- Batch operations (enable/disable, add/remove sources to groups)
- Group management (create, update, delete, tag-based groups)
- Rate limit and priority adjustments
- Source metadata management
- RSS feed discovery and validation
- Integration with DuckDuckGo search for source discovery

Author: Ideotion
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from sqlalchemy import and_, asc, desc, func, not_, or_
from sqlalchemy.orm import Session

# Import database models
from src.database.models import (
    Source,
    SourceGroup,
    SourceMetadata,
    get_session,
    source_group_association,
)

# Import logging config
from src.utils.logging_config import setup_logging

logger = setup_logging("source_manager")

# Import DuckDuckGo search
from src.services.duckduckgo import DuckDuckGoSearch


class SourceManager:
    """
    Comprehensive source management class for Open Omniscience.
    
    This class provides methods for managing sources, groups, and metadata
    with support for batch operations and advanced querying.
    """
    
    def __init__(self, session: Session | None = None):
        """
        Initialize the SourceManager.
        
        Args:
            session: Optional SQLAlchemy session. If not provided, a new session will be created.
        """
        self.session = session or get_session()
        self._owns_session = session is None
    
    def close(self):
        """Close the session if it was created by this manager."""
        if self._owns_session and self.session:
            self.session.close()
            self.session = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    # ==================== SOURCE OPERATIONS ====================
    
    def get_source_by_id(self, source_id: int) -> Source | None:
        """Get a source by its ID."""
        return self.session.query(Source).filter_by(id=source_id).first()
    
    def get_source_by_domain(self, domain: str) -> Source | None:
        """Get a source by its domain."""
        return self.session.query(Source).filter_by(domain=domain).first()
    
    def get_source_by_name(self, name: str) -> Source | None:
        """Get a source by its name."""
        return self.session.query(Source).filter_by(name=name).first()
    
    def get_all_sources(self, limit: int = None, offset: int = 0) -> list[Source]:
        """Get all sources with optional pagination."""
        query = self.session.query(Source)
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        return query.all()
    
    def get_sources_by_tags(self, tags: list[str], match_all: bool = False) -> list[Source]:
        """
        Get sources by tags.
        
        Args:
            tags: List of tags to search for
            match_all: If True, sources must have ALL tags. If False, sources must have ANY tag.
        
        Returns:
            List of matching sources
        """
        if not tags:
            return []
        
        conditions = []
        for tag in tags:
            conditions.append(Source.tags.ilike(f'%{tag}%'))
        
        if match_all:
            # Sources must have all tags
            query = self.session.query(Source)
            for condition in conditions:
                query = query.filter(condition)
            return query.all()
        else:
            # Sources must have any tag
            return self.session.query(Source).filter(or_(*conditions)).all()
    
    def get_sources_by_group(self, group_id: int) -> list[Source]:
        """Get all sources in a specific group."""
        group = self.session.query(SourceGroup).filter_by(id=group_id).first()
        if group:
            return group.sources.all()
        return []
    
    def get_sources_by_group_name(self, group_name: str) -> list[Source]:
        """Get all sources in a group by group name."""
        group = self.session.query(SourceGroup).filter_by(name=group_name).first()
        if group:
            return group.sources.all()
        return []
    
    def create_source(self, name: str, domain: str, **kwargs) -> Source:
        """
        Create a new source.
        
        Args:
            name: Name of the source
            domain: Domain of the source
            **kwargs: Additional source attributes (rss_url, rate_limit_ms, enabled, priority, tags)
        
        Returns:
            The created Source object
        """
        # Check if source already exists
        existing = self.session.query(Source).filter_by(domain=domain).first()
        if existing:
            logger.warning(f"Source with domain {domain} already exists")
            return existing
        
        source_data = {
            'name': name,
            'domain': domain,
            'rss_url': kwargs.get('rss_url'),
            'rate_limit_ms': kwargs.get('rate_limit_ms', 2000),
            'enabled': kwargs.get('enabled', True),
            'priority': kwargs.get('priority', 2),
            'tags': kwargs.get('tags', ''),
        }
        
        source = Source(**source_data)
        self.session.add(source)
        self.session.commit()
        logger.info(f"Created new source: {name} ({domain})")
        return source
    
    def update_source(self, source_id: int, **kwargs) -> Source | None:
        """
        Update a source.
        
        Args:
            source_id: ID of the source to update
            **kwargs: Attributes to update
        
        Returns:
            The updated Source object, or None if not found
        """
        source = self.session.query(Source).filter_by(id=source_id).first()
        if not source:
            logger.warning(f"Source with ID {source_id} not found")
            return None
        
        for key, value in kwargs.items():
            if hasattr(source, key):
                setattr(source, key, value)
        
        self.session.commit()
        logger.info(f"Updated source: {source.name} (ID: {source_id})")
        return source
    
    def delete_source(self, source_id: int) -> bool:
        """
        Delete a source.
        
        Args:
            source_id: ID of the source to delete
        
        Returns:
            True if deleted, False if not found
        """
        source = self.session.query(Source).filter_by(id=source_id).first()
        if not source:
            logger.warning(f"Source with ID {source_id} not found")
            return False
        
        self.session.delete(source)
        self.session.commit()
        logger.info(f"Deleted source: {source.name} (ID: {source_id})")
        return True
    
    # ==================== BATCH SOURCE OPERATIONS ====================
    
    def enable_sources(self, source_ids: list[int]) -> int:
        """
        Enable multiple sources.
        
        Args:
            source_ids: List of source IDs to enable
        
        Returns:
            Number of sources updated
        """
        result = self.session.query(Source).filter(Source.id.in_(source_ids)).update(
            {'enabled': True}, synchronize_session=False
        )
        self.session.commit()
        logger.info(f"Enabled {result} sources")
        return result
    
    def disable_sources(self, source_ids: list[int]) -> int:
        """
        Disable multiple sources.
        
        Args:
            source_ids: List of source IDs to disable
        
        Returns:
            Number of sources updated
        """
        result = self.session.query(Source).filter(Source.id.in_(source_ids)).update(
            {'enabled': False}, synchronize_session=False
        )
        self.session.commit()
        logger.info(f"Disabled {result} sources")
        return result
    
    def set_source_priority(self, source_ids: list[int], priority: int) -> int:
        """
        Set priority for multiple sources.
        
        Args:
            source_ids: List of source IDs
            priority: Priority level (1 = high, 3 = low)
        
        Returns:
            Number of sources updated
        """
        result = self.session.query(Source).filter(Source.id.in_(source_ids)).update(
            {'priority': priority}, synchronize_session=False
        )
        self.session.commit()
        logger.info(f"Set priority {priority} for {result} sources")
        return result
    
    def set_source_rate_limit(self, source_ids: list[int], rate_limit_ms: int) -> int:
        """
        Set rate limit for multiple sources.
        
        Args:
            source_ids: List of source IDs
            rate_limit_ms: Rate limit in milliseconds
        
        Returns:
            Number of sources updated
        """
        result = self.session.query(Source).filter(Source.id.in_(source_ids)).update(
            {'rate_limit_ms': rate_limit_ms}, synchronize_session=False
        )
        self.session.commit()
        logger.info(f"Set rate limit {rate_limit_ms}ms for {result} sources")
        return result
    
    def add_tags_to_sources(self, source_ids: list[int], tags: list[str]) -> int:
        """
        Add tags to multiple sources.
        
        Args:
            source_ids: List of source IDs
            tags: List of tags to add
        
        Returns:
            Number of sources updated
        """
        # Get current tags for each source
        sources = self.session.query(Source).filter(Source.id.in_(source_ids)).all()
        
        for source in sources:
            current_tags = source.tags.split(',') if source.tags else []
            current_tags = [tag.strip() for tag in current_tags if tag.strip()]
            
            # Add new tags
            for tag in tags:
                tag = tag.strip()
                if tag and tag not in current_tags:
                    current_tags.append(tag)
            
            source.tags = ', '.join(current_tags)
        
        self.session.commit()
        logger.info(f"Added tags {tags} to {len(sources)} sources")
        return len(sources)
    
    def remove_tags_from_sources(self, source_ids: list[int], tags: list[str]) -> int:
        """
        Remove tags from multiple sources.
        
        Args:
            source_ids: List of source IDs
            tags: List of tags to remove
        
        Returns:
            Number of sources updated
        """
        # Get current tags for each source
        sources = self.session.query(Source).filter(Source.id.in_(source_ids)).all()
        
        for source in sources:
            current_tags = source.tags.split(',') if source.tags else []
            current_tags = [tag.strip() for tag in current_tags if tag.strip()]
            
            # Remove specified tags
            for tag in tags:
                tag = tag.strip()
                if tag in current_tags:
                    current_tags.remove(tag)
            
            source.tags = ', '.join(current_tags)
        
        self.session.commit()
        logger.info(f"Removed tags {tags} from {len(sources)} sources")
        return len(sources)
    
    # ==================== GROUP OPERATIONS ====================
    
    def get_group_by_id(self, group_id: int) -> SourceGroup | None:
        """Get a group by its ID."""
        return self.session.query(SourceGroup).filter_by(id=group_id).first()
    
    def get_group_by_name(self, name: str) -> SourceGroup | None:
        """Get a group by its name."""
        return self.session.query(SourceGroup).filter_by(name=name).first()
    
    def get_all_groups(self, limit: int = None, offset: int = 0) -> list[SourceGroup]:
        """Get all groups with optional pagination."""
        query = self.session.query(SourceGroup)
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        return query.all()
    
    def create_group(self, name: str, **kwargs) -> SourceGroup:
        """
        Create a new source group.
        
        Args:
            name: Name of the group
            **kwargs: Additional group attributes
        
        Returns:
            The created SourceGroup object
        """
        # Check if group already exists
        existing = self.session.query(SourceGroup).filter_by(name=name).first()
        if existing:
            logger.warning(f"Group with name {name} already exists")
            return existing
        
        group_data = {
            'name': name,
            'description': kwargs.get('description', ''),
            'color': kwargs.get('color', '#666666'),
            'is_tag_based': kwargs.get('is_tag_based', False),
            'tag_pattern': kwargs.get('tag_pattern', ''),
            'priority': kwargs.get('priority', 2),
            'rate_limit_ms': kwargs.get('rate_limit_ms', 2000),
            'enabled': kwargs.get('enabled', True),
        }
        
        group = SourceGroup(**group_data)
        self.session.add(group)
        self.session.commit()
        logger.info(f"Created new group: {name}")
        return group
    
    def update_group(self, group_id: int, **kwargs) -> SourceGroup | None:
        """
        Update a group.
        
        Args:
            group_id: ID of the group to update
            **kwargs: Attributes to update
        
        Returns:
            The updated SourceGroup object, or None if not found
        """
        group = self.session.query(SourceGroup).filter_by(id=group_id).first()
        if not group:
            logger.warning(f"Group with ID {group_id} not found")
            return None
        
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)
        
        self.session.commit()
        logger.info(f"Updated group: {group.name} (ID: {group_id})")
        return group
    
    def delete_group(self, group_id: int) -> bool:
        """
        Delete a group.
        
        Args:
            group_id: ID of the group to delete
        
        Returns:
            True if deleted, False if not found
        """
        group = self.session.query(SourceGroup).filter_by(id=group_id).first()
        if not group:
            logger.warning(f"Group with ID {group_id} not found")
            return False
        
        self.session.delete(group)
        self.session.commit()
        logger.info(f"Deleted group: {group.name} (ID: {group_id})")
        return True
    
    # ==================== GROUP-SOURCE ASSOCIATION OPERATIONS ====================
    
    def add_sources_to_group(self, group_id: int, source_ids: list[int]) -> int:
        """
        Add sources to a group.
        
        Args:
            group_id: ID of the group
            source_ids: List of source IDs to add
        
        Returns:
            Number of sources added
        """
        group = self.session.query(SourceGroup).filter_by(id=group_id).first()
        if not group:
            logger.warning(f"Group with ID {group_id} not found")
            return 0
        
        sources = self.session.query(Source).filter(Source.id.in_(source_ids)).all()
        source_set = set(sources)
        
        # Get current sources in group
        current_sources = group.sources.all()
        current_source_ids = {s.id for s in current_sources}
        
        added_count = 0
        for source in sources:
            if source.id not in current_source_ids:
                group.sources.append(source)
                added_count += 1
        
        self.session.commit()
        logger.info(f"Added {added_count} sources to group {group.name}")
        return added_count
    
    def remove_sources_from_group(self, group_id: int, source_ids: list[int]) -> int:
        """
        Remove sources from a group.
        
        Args:
            group_id: ID of the group
            source_ids: List of source IDs to remove
        
        Returns:
            Number of sources removed
        """
        group = self.session.query(SourceGroup).filter_by(id=group_id).first()
        if not group:
            logger.warning(f"Group with ID {group_id} not found")
            return 0
        
        # Get sources to remove
        sources_to_remove = self.session.query(Source).filter(Source.id.in_(source_ids)).all()
        source_ids_to_remove = {s.id for s in sources_to_remove}
        
        # Get current sources in group
        current_sources = group.sources.all()
        
        removed_count = 0
        for source in current_sources:
            if source.id in source_ids_to_remove:
                group.sources.remove(source)
                removed_count += 1
        
        self.session.commit()
        logger.info(f"Removed {removed_count} sources from group {group.name}")
        return removed_count
    
    def add_source_to_groups(self, source_id: int, group_ids: list[int]) -> int:
        """
        Add a source to multiple groups.
        
        Args:
            source_id: ID of the source
            group_ids: List of group IDs
        
        Returns:
            Number of groups the source was added to
        """
        source = self.session.query(Source).filter_by(id=source_id).first()
        if not source:
            logger.warning(f"Source with ID {source_id} not found")
            return 0
        
        groups = self.session.query(SourceGroup).filter(SourceGroup.id.in_(group_ids)).all()
        
        added_count = 0
        for group in groups:
            if source not in group.sources:
                group.sources.append(source)
                added_count += 1
        
        self.session.commit()
        logger.info(f"Added source {source.name} to {added_count} groups")
        return added_count
    
    def remove_source_from_groups(self, source_id: int, group_ids: list[int]) -> int:
        """
        Remove a source from multiple groups.
        
        Args:
            source_id: ID of the source
            group_ids: List of group IDs
        
        Returns:
            Number of groups the source was removed from
        """
        source = self.session.query(Source).filter_by(id=source_id).first()
        if not source:
            logger.warning(f"Source with ID {source_id} not found")
            return 0
        
        groups = self.session.query(SourceGroup).filter(SourceGroup.id.in_(group_ids)).all()
        
        removed_count = 0
        for group in groups:
            if source in group.sources:
                group.sources.remove(source)
                removed_count += 1
        
        self.session.commit()
        logger.info(f"Removed source {source.name} from {removed_count} groups")
        return removed_count
    
    def get_source_groups(self, source_id: int) -> list[SourceGroup]:
        """Get all groups a source belongs to."""
        source = self.session.query(Source).filter_by(id=source_id).first()
        if source:
            return source.groups.all()
        return []
    
    # ==================== TAG-BASED GROUP OPERATIONS ====================
    
    def create_tag_based_group(self, name: str, tag_pattern: str, **kwargs) -> SourceGroup:
        """
        Create a tag-based group that automatically includes sources with matching tags.
        
        Args:
            name: Name of the group
            tag_pattern: Comma-separated list of tags to match
            **kwargs: Additional group attributes
        
        Returns:
            The created SourceGroup object
        """
        group = self.create_group(
            name=name,
            is_tag_based=True,
            tag_pattern=tag_pattern,
            **kwargs
        )
        
        # Auto-populate with matching sources
        tags = [tag.strip() for tag in tag_pattern.split(',') if tag.strip()]
        if tags:
            matching_sources = self.get_sources_by_tags(tags, match_all=False)
            source_ids = [s.id for s in matching_sources]
            if source_ids:
                self.add_sources_to_group(group.id, source_ids)
        
        logger.info(f"Created tag-based group: {name} with pattern {tag_pattern}")
        return group
    
    def update_tag_based_group(self, group_id: int, tag_pattern: str) -> SourceGroup | None:
        """
        Update a tag-based group and refresh its source membership.
        
        Args:
            group_id: ID of the group
            tag_pattern: New tag pattern
        
        Returns:
            The updated SourceGroup object
        """
        group = self.update_group(group_id, tag_pattern=tag_pattern)
        if not group:
            return None
        
        # Clear current sources
        current_sources = group.sources.all()
        for source in current_sources[:]:  # Copy to avoid modification during iteration
            group.sources.remove(source)
        
        # Add matching sources
        tags = [tag.strip() for tag in tag_pattern.split(',') if tag.strip()]
        if tags:
            matching_sources = self.get_sources_by_tags(tags, match_all=False)
            for source in matching_sources:
                group.sources.append(source)
        
        self.session.commit()
        logger.info(f"Updated tag-based group {group.name} with new pattern {tag_pattern}")
        return group
    
    def refresh_tag_based_groups(self) -> int:
        """
        Refresh all tag-based groups to ensure they have the correct sources.
        
        Returns:
            Number of groups refreshed
        """
        tag_based_groups = self.session.query(SourceGroup).filter_by(is_tag_based=True).all()
        
        for group in tag_based_groups:
            if group.tag_pattern:
                tags = [tag.strip() for tag in group.tag_pattern.split(',') if tag.strip()]
                if tags:
                    # Clear current sources
                    current_sources = group.sources.all()
                    for source in current_sources[:]:
                        group.sources.remove(source)
                    
                    # Add matching sources
                    matching_sources = self.get_sources_by_tags(tags, match_all=False)
                    for source in matching_sources:
                        group.sources.append(source)
        
        self.session.commit()
        logger.info(f"Refreshed {len(tag_based_groups)} tag-based groups")
        return len(tag_based_groups)
    
    # ==================== METADATA OPERATIONS ====================
    
    def get_metadata(self, source_id: int) -> SourceMetadata | None:
        """Get metadata for a source."""
        return self.session.query(SourceMetadata).filter_by(source_id=source_id).first()
    
    def create_metadata(self, source_id: int, **kwargs) -> SourceMetadata:
        """
        Create metadata for a source.
        
        Args:
            source_id: ID of the source
            **kwargs: Metadata attributes
        
        Returns:
            The created SourceMetadata object
        """
        # Check if metadata already exists
        existing = self.session.query(SourceMetadata).filter_by(source_id=source_id).first()
        if existing:
            logger.warning(f"Metadata for source {source_id} already exists")
            return existing
        
        metadata = SourceMetadata(source_id=source_id, **kwargs)
        self.session.add(metadata)
        self.session.commit()
        logger.info(f"Created metadata for source {source_id}")
        return metadata
    
    def update_metadata(self, source_id: int, **kwargs) -> SourceMetadata | None:
        """
        Update metadata for a source.
        
        Args:
            source_id: ID of the source
            **kwargs: Metadata attributes to update
        
        Returns:
            The updated SourceMetadata object, or None if not found
        """
        metadata = self.session.query(SourceMetadata).filter_by(source_id=source_id).first()
        if not metadata:
            logger.warning(f"Metadata for source {source_id} not found")
            return None
        
        for key, value in kwargs.items():
            if hasattr(metadata, key):
                setattr(metadata, key, value)
        
        self.session.commit()
        logger.info(f"Updated metadata for source {source_id}")
        return metadata
    
    def delete_metadata(self, source_id: int) -> bool:
        """
        Delete metadata for a source.
        
        Args:
            source_id: ID of the source
        
        Returns:
            True if deleted, False if not found
        """
        metadata = self.session.query(SourceMetadata).filter_by(source_id=source_id).first()
        if not metadata:
            logger.warning(f"Metadata for source {source_id} not found")
            return False
        
        self.session.delete(metadata)
        self.session.commit()
        logger.info(f"Deleted metadata for source {source_id}")
        return True
    
    def get_sources_by_country(self, country: str) -> list[Source]:
        """Get sources by country code."""
        metadata_list = self.session.query(SourceMetadata).filter_by(country=country).all()
        source_ids = [m.source_id for m in metadata_list]
        return self.session.query(Source).filter(Source.id.in_(source_ids)).all()
    
    def get_sources_by_language(self, language: str) -> list[Source]:
        """Get sources by language code."""
        metadata_list = self.session.query(SourceMetadata).filter_by(language=language).all()
        source_ids = [m.source_id for m in metadata_list]
        return self.session.query(Source).filter(Source.id.in_(source_ids)).all()
    
    def get_sources_robots_allowed(self, allowed: bool = True) -> list[Source]:
        """Get sources based on robots.txt permission."""
        metadata_list = self.session.query(SourceMetadata).filter_by(robots_allowed=allowed).all()
        source_ids = [m.source_id for m in metadata_list]
        return self.session.query(Source).filter(Source.id.in_(source_ids)).all()
    
    # ==================== BATCH GROUP OPERATIONS ====================
    
    def enable_groups(self, group_ids: list[int]) -> int:
        """
        Enable all sources in multiple groups.
        
        Args:
            group_ids: List of group IDs
        
        Returns:
            Number of sources enabled
        """
        sources = self.session.query(Source).join(source_group_association).filter(
            source_group_association.c.group_id.in_(group_ids)
        ).all()
        
        source_ids = [s.id for s in sources]
        return self.enable_sources(source_ids)
    
    def disable_groups(self, group_ids: list[int]) -> int:
        """
        Disable all sources in multiple groups.
        
        Args:
            group_ids: List of group IDs
        
        Returns:
            Number of sources disabled
        """
        sources = self.session.query(Source).join(source_group_association).filter(
            source_group_association.c.group_id.in_(group_ids)
        ).all()
        
        source_ids = [s.id for s in sources]
        return self.disable_sources(source_ids)
    
    def set_group_priority(self, group_ids: list[int], priority: int) -> int:
        """
        Set priority for all sources in multiple groups.
        
        Args:
            group_ids: List of group IDs
            priority: Priority level
        
        Returns:
            Number of sources updated
        """
        sources = self.session.query(Source).join(source_group_association).filter(
            source_group_association.c.group_id.in_(group_ids)
        ).all()
        
        source_ids = [s.id for s in sources]
        return self.set_source_priority(source_ids, priority)
    
    def set_group_rate_limit(self, group_ids: list[int], rate_limit_ms: int) -> int:
        """
        Set rate limit for all sources in multiple groups.
        
        Args:
            group_ids: List of group IDs
            rate_limit_ms: Rate limit in milliseconds
        
        Returns:
            Number of sources updated
        """
        sources = self.session.query(Source).join(source_group_association).filter(
            source_group_association.c.group_id.in_(group_ids)
        ).all()
        
        source_ids = [s.id for s in sources]
        return self.set_source_rate_limit(source_ids, rate_limit_ms)
    
    # ==================== SOURCE DISCOVERY ====================
    
    def discover_rss_feeds(self, source_ids: list[int] = None, timeout: int = 10) -> list[dict]:
        """
        Discover RSS feeds for sources that don't have them.
        
        Args:
            source_ids: Optional list of source IDs to check. If None, checks all sources without RSS URLs.
            timeout: Request timeout in seconds
        
        Returns:
            List of sources with discovered RSS feeds
        """
        if source_ids:
            sources = self.session.query(Source).filter(Source.id.in_(source_ids)).all()
        else:
            sources = self.session.query(Source).filter(
                or_(Source.rss_url == None, Source.rss_url == '')
            ).all()
        
        source_list = [
            {
                'id': s.id,
                'name': s.name,
                'domain': s.domain,
                'url': f"https://{s.domain}" if not s.rss_url else s.rss_url,
                'rss_url': s.rss_url
            }
            for s in sources
        ]
        
        # Use DuckDuckGo to find missing RSS feeds
        results = DuckDuckGoSearch.find_missing_rss_feeds(source_list, timeout=timeout)
        
        # Update sources with found RSS feeds
        updated_count = 0
        for result in results:
            if result.get('rss_url'):
                source = self.session.query(Source).filter_by(domain=result.get('domain')).first()
                if source and not source.rss_url:
                    source.rss_url = result['rss_url']
                    updated_count += 1
        
        if updated_count > 0:
            self.session.commit()
            logger.info(f"Discovered RSS feeds for {updated_count} sources")
        
        return results
    
    def discover_sources_by_topic(self, topic: str, max_sources: int = 20, **kwargs) -> list[dict]:
        """
        Discover new sources for a specific topic using DuckDuckGo.
        
        Args:
            topic: The topic to search for
            max_sources: Maximum number of sources to return
            **kwargs: Additional arguments for DuckDuckGo search
        
        Returns:
            List of discovered source dictionaries
        """
        return DuckDuckGoSearch.discover_sources_by_topic(topic, max_sources, **kwargs)
    
    def add_discovered_sources(self, discovered_sources: list[dict], group_name: str = None) -> list[Source]:
        """
        Add discovered sources to the database.
        
        Args:
            discovered_sources: List of discovered source dictionaries
            group_name: Optional group name to add sources to
        
        Returns:
            List of created Source objects
        """
        created_sources = []
        
        for source_data in discovered_sources:
            domain = source_data.get('domain', '')
            if not domain:
                continue
            
            # Check if source already exists
            existing = self.session.query(Source).filter_by(domain=domain).first()
            if existing:
                # Update existing source with new information
                if source_data.get('rss_url') and not existing.rss_url:
                    existing.rss_url = source_data['rss_url']
                if source_data.get('name') and not existing.name:
                    existing.name = source_data['name']
                created_sources.append(existing)
                continue
            
            # Create new source
            source = self.create_source(
                name=source_data.get('name', domain.replace('.', ' ').title()),
                domain=domain,
                rss_url=source_data.get('rss_url'),
                tags=', '.join(source_data.get('tags', []))
            )
            created_sources.append(source)
        
        # Add to group if specified
        if group_name and created_sources:
            group = self.get_group_by_name(group_name)
            if not group:
                group = self.create_group(group_name)
            
            source_ids = [s.id for s in created_sources]
            self.add_sources_to_group(group.id, source_ids)
        
        self.session.commit()
        logger.info(f"Added {len(created_sources)} discovered sources")
        return created_sources
    
    # ==================== IMPORT/EXPORT OPERATIONS ====================
    
    def import_sources_from_yaml(self, file_path: str) -> dict[str, int]:
        """
        Import sources from a YAML file.
        
        Args:
            file_path: Path to the YAML file
        
        Returns:
            Dictionary with counts of added, updated, and skipped sources
        """
        with open(file_path) as f:
            data = yaml.safe_load(f)
        
        sources_data = data.get('sources', [])
        
        added = 0
        updated = 0
        skipped = 0
        
        for source_data in sources_data:
            domain = source_data.get('domain', '')
            if not domain:
                skipped += 1
                continue
            
            existing = self.session.query(Source).filter_by(domain=domain).first()
            if existing:
                # Update existing source
                existing.name = source_data.get('name', existing.name)
                existing.rss_url = source_data.get('rss_url', existing.rss_url)
                existing.rate_limit_ms = source_data.get('rate_limit_ms', existing.rate_limit_ms)
                existing.enabled = source_data.get('enabled', existing.enabled)
                existing.priority = source_data.get('priority', existing.priority)
                existing.tags = source_data.get('tags', existing.tags)
                updated += 1
            else:
                # Create new source
                self.create_source(
                    name=source_data.get('name', domain.replace('.', ' ').title()),
                    domain=domain,
                    rss_url=source_data.get('rss_url'),
                    rate_limit_ms=source_data.get('rate_limit_ms', 2000),
                    enabled=source_data.get('enabled', True),
                    priority=source_data.get('priority', 2),
                    tags=source_data.get('tags', '')
                )
                added += 1
        
        self.session.commit()
        logger.info(f"Imported sources: {added} added, {updated} updated, {skipped} skipped")
        return {'added': added, 'updated': updated, 'skipped': skipped}
    
    def export_sources_to_yaml(self, file_path: str, group_id: int = None) -> int:
        """
        Export sources to a YAML file.
        
        Args:
            file_path: Path to the YAML file
            group_id: Optional group ID to export only sources from that group
        
        Returns:
            Number of sources exported
        """
        if group_id:
            sources = self.get_sources_by_group(group_id)
        else:
            sources = self.get_all_sources()
        
        sources_data = []
        for source in sources:
            source_data = {
                'name': source.name,
                'domain': source.domain,
                'rss_url': source.rss_url,
                'rate_limit_ms': source.rate_limit_ms,
                'enabled': source.enabled,
                'priority': source.priority,
                'tags': source.tags or ''
            }
            sources_data.append(source_data)
        
        data = {
            'project_name': 'OpenOmniscience',
            'description': 'Global Intelligence Platform for Investigative Journalism',
            'version': '0.2.0',
            'date_created': datetime.now().isoformat(),
            'sources': sources_data
        }
        
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        
        logger.info(f"Exported {len(sources_data)} sources to {file_path}")
        return len(sources_data)
    
    # ==================== STATISTICS AND ANALYTICS ====================
    
    def get_source_statistics(self) -> dict[str, Any]:
        """
        Get statistics about sources.
        
        Returns:
            Dictionary with various source statistics
        """
        total_sources = self.session.query(Source).count()
        enabled_sources = self.session.query(Source).filter_by(enabled=True).count()
        disabled_sources = total_sources - enabled_sources
        
        # Count by priority
        priority_counts = {}
        for priority in [1, 2, 3]:
            count = self.session.query(Source).filter_by(priority=priority).count()
            priority_counts[f'priority_{priority}'] = count
        
        # Count by tags
        all_tags = {}
        sources = self.session.query(Source).all()
        for source in sources:
            if source.tags:
                tags = [tag.strip() for tag in source.tags.split(',') if tag.strip()]
                for tag in tags:
                    all_tags[tag] = all_tags.get(tag, 0) + 1
        
        # Count groups
        total_groups = self.session.query(SourceGroup).count()
        tag_based_groups = self.session.query(SourceGroup).filter_by(is_tag_based=True).count()
        
        # Count sources with/without RSS
        with_rss = self.session.query(Source).filter(Source.rss_url != None, Source.rss_url != '').count()
        without_rss = total_sources - with_rss
        
        # Count by metadata
        with_metadata = self.session.query(SourceMetadata).count()
        with_country = self.session.query(SourceMetadata).filter(SourceMetadata.country != None).count()
        with_language = self.session.query(SourceMetadata).filter(SourceMetadata.language != None).count()
        
        return {
            'total_sources': total_sources,
            'enabled_sources': enabled_sources,
            'disabled_sources': disabled_sources,
            'priority_counts': priority_counts,
            'tag_counts': all_tags,
            'total_groups': total_groups,
            'tag_based_groups': tag_based_groups,
            'with_rss': with_rss,
            'without_rss': without_rss,
            'with_metadata': with_metadata,
            'with_country': with_country,
            'with_language': with_language,
        }


# Convenience functions for module-level usage
def get_source_manager() -> SourceManager:
    """Get a new SourceManager instance."""
    return SourceManager()


if __name__ == "__main__":
    # Example usage
    print("Testing SourceManager...")
    
    with SourceManager() as manager:
        # Test basic operations
        print(f"Total sources: {len(manager.get_all_sources())}")
        print(f"Total groups: {len(manager.get_all_groups())}")
        
        # Test statistics
        stats = manager.get_source_statistics()
        print(f"Statistics: {stats}")
        
        # Test source discovery (commented out to avoid network calls)
        # print("Discovering sources for 'technology news'...")
        # discovered = manager.discover_sources_by_topic("technology news", max_sources=5)
        # print(f"Discovered {len(discovered)} sources")
        
        # Test RSS discovery (commented out to avoid network calls)
        # print("Discovering missing RSS feeds...")
        # results = manager.discover_rss_feeds(timeout=5)
        # print(f"Found RSS feeds for {len([r for r in results if r.get('rss_url')])} sources")
