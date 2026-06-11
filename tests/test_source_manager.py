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
Tests for SourceManager class

This module contains tests for the comprehensive source management functionality.
"""

import sys
from pathlib import Path

import pytest

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "src"))

from database.models import Base, Session, Source, SourceGroup, engine
from database.source_manager import SourceManager


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    # Create all tables
    Base.metadata.create_all(engine)

    session = Session()
    yield session

    # Clean up
    session.close()
    # Drop all tables
    Base.metadata.drop_all(engine)


@pytest.fixture
def source_manager(db_session):
    """Create a SourceManager instance with a database session."""
    return SourceManager(session=db_session)


@pytest.fixture
def sample_sources(db_session):
    """Create sample sources for testing."""
    sources = [
        Source(
            name="BBC News",
            domain="bbc.com",
            rss_url="http://feeds.bbci.co.uk/news/rss.xml",
            rate_limit_ms=1000,
            enabled=True,
            priority=1,
            tags="news,uk",
        ),
        Source(
            name="Reuters",
            domain="reuters.com",
            rss_url="https://www.reuters.com/tools/rss",
            rate_limit_ms=1000,
            enabled=True,
            priority=1,
            tags="news,financial",
        ),
        Source(
            name="TechCrunch",
            domain="techcrunch.com",
            rss_url="https://techcrunch.com/feed/",
            rate_limit_ms=2000,
            enabled=False,
            priority=2,
            tags="technology,startups",
        ),
        Source(
            name="The Guardian",
            domain="theguardian.com",
            rss_url="https://www.theguardian.com/world/rss",
            rate_limit_ms=1500,
            enabled=True,
            priority=2,
            tags="news,uk,opinion",
        ),
    ]

    for source in sources:
        db_session.add(source)
    db_session.commit()

    return sources


@pytest.fixture
def sample_groups(db_session):
    """Create sample groups for testing."""
    groups = [
        SourceGroup(
            name="News Sources",
            description="Major news organizations",
            color="#FF5733",
            is_tag_based=False,
            priority=1,
            rate_limit_ms=1000,
            enabled=True,
        ),
        SourceGroup(
            name="Tech Sources",
            description="Technology news sources",
            color="#33FF57",
            is_tag_based=True,
            tag_pattern="technology,tech",
            priority=2,
            rate_limit_ms=2000,
            enabled=True,
        ),
        SourceGroup(
            name="Disabled Group",
            description="Disabled sources group",
            color="#5733FF",
            is_tag_based=False,
            priority=3,
            rate_limit_ms=3000,
            enabled=False,
        ),
    ]

    for group in groups:
        db_session.add(group)
    db_session.commit()

    return groups


class TestSourceOperations:
    """Test source CRUD operations."""

    def test_create_source(self, source_manager):
        """Test creating a new source."""
        source = source_manager.create_source(
            name="Test Source",
            domain="test.com",
            rss_url="https://test.com/rss",
            rate_limit_ms=2000,
            enabled=True,
            priority=2,
            tags="test,example",
        )

        assert source.id is not None
        assert source.name == "Test Source"
        assert source.domain == "test.com"
        assert source.rss_url == "https://test.com/rss"
        assert source.rate_limit_ms == 2000
        assert source.enabled is True
        assert source.priority == 2
        assert source.tags == "test,example"

    def test_create_duplicate_source(self, source_manager, sample_sources):
        """Test creating a duplicate source (should return existing)."""
        existing = source_manager.get_source_by_domain("bbc.com")
        assert existing is not None

        new_source = source_manager.create_source(
            name="BBC News Duplicate", domain="bbc.com", rss_url="http://different-rss.com"
        )

        assert new_source.id == existing.id
        assert new_source.name == "BBC News"  # Should keep original name

    def test_get_source_by_id(self, source_manager, sample_sources):
        """Test getting a source by ID."""
        source = source_manager.get_source_by_id(sample_sources[0].id)
        assert source is not None
        assert source.name == "BBC News"

    def test_get_source_by_domain(self, source_manager, sample_sources):
        """Test getting a source by domain."""
        source = source_manager.get_source_by_domain("bbc.com")
        assert source is not None
        assert source.name == "BBC News"

    def test_get_source_by_name(self, source_manager, sample_sources):
        """Test getting a source by name."""
        source = source_manager.get_source_by_name("BBC News")
        assert source is not None
        assert source.domain == "bbc.com"

    def test_get_all_sources(self, source_manager, sample_sources):
        """Test getting all sources."""
        sources = source_manager.get_all_sources()
        assert len(sources) == 4

    def test_update_source(self, source_manager, sample_sources):
        """Test updating a source."""
        updated = source_manager.update_source(
            sample_sources[0].id, name="BBC News Updated", rate_limit_ms=5000
        )

        assert updated is not None
        assert updated.name == "BBC News Updated"
        assert updated.rate_limit_ms == 5000

    def test_delete_source(self, source_manager, sample_sources):
        """Test deleting a source."""
        source_id = sample_sources[0].id
        success = source_manager.delete_source(source_id)

        assert success is True

        deleted = source_manager.get_source_by_id(source_id)
        assert deleted is None

    def test_get_sources_by_tags(self, source_manager, sample_sources):
        """Test getting sources by tags."""
        # Test single tag
        sources = source_manager.get_sources_by_tags(["news"])
        assert len(sources) == 3  # BBC News, Reuters, The Guardian

        # Test multiple tags with ANY match
        sources = source_manager.get_sources_by_tags(["news", "technology"])
        assert len(sources) == 4  # BBC News, Reuters, TechCrunch, The Guardian

        # Test multiple tags with ALL match
        sources = source_manager.get_sources_by_tags(["news", "uk"], match_all=True)
        assert len(sources) == 2  # BBC News and The Guardian


class TestBatchSourceOperations:
    """Test batch operations on sources."""

    def test_enable_sources(self, source_manager, sample_sources):
        """Test enabling multiple sources."""
        # Disable TechCrunch first
        source_manager.update_source(sample_sources[2].id, enabled=False)

        # Enable all sources
        count = source_manager.enable_sources([s.id for s in sample_sources])
        assert count == 4

        # Verify all are enabled
        sources = source_manager.get_all_sources()
        assert all(s.enabled for s in sources)

    def test_disable_sources(self, source_manager, sample_sources):
        """Test disabling multiple sources."""
        count = source_manager.disable_sources([sample_sources[0].id, sample_sources[1].id])
        assert count == 2

        # Verify they are disabled
        source1 = source_manager.get_source_by_id(sample_sources[0].id)
        source2 = source_manager.get_source_by_id(sample_sources[1].id)
        assert source1.enabled is False
        assert source2.enabled is False

    def test_set_source_priority(self, source_manager, sample_sources):
        """Test setting priority for multiple sources."""
        count = source_manager.set_source_priority(
            [sample_sources[0].id, sample_sources[1].id], priority=3
        )
        assert count == 2

        # Verify priority is set
        source1 = source_manager.get_source_by_id(sample_sources[0].id)
        source2 = source_manager.get_source_by_id(sample_sources[1].id)
        assert source1.priority == 3
        assert source2.priority == 3

    def test_set_source_rate_limit(self, source_manager, sample_sources):
        """Test setting rate limit for multiple sources."""
        count = source_manager.set_source_rate_limit(
            [sample_sources[0].id, sample_sources[1].id], rate_limit_ms=5000
        )
        assert count == 2

        # Verify rate limit is set
        source1 = source_manager.get_source_by_id(sample_sources[0].id)
        source2 = source_manager.get_source_by_id(sample_sources[1].id)
        assert source1.rate_limit_ms == 5000
        assert source2.rate_limit_ms == 5000

    def test_add_tags_to_sources(self, source_manager, sample_sources):
        """Test adding tags to multiple sources."""
        count = source_manager.add_tags_to_sources(
            [sample_sources[0].id, sample_sources[1].id], tags=["premium", "verified"]
        )
        assert count == 2

        # Verify tags are added
        source1 = source_manager.get_source_by_id(sample_sources[0].id)
        source2 = source_manager.get_source_by_id(sample_sources[1].id)
        assert "premium" in source1.tags
        assert "verified" in source1.tags
        assert "premium" in source2.tags
        assert "verified" in source2.tags

    def test_remove_tags_from_sources(self, source_manager, sample_sources):
        """Test removing tags from multiple sources."""
        # First add some tags
        source_manager.add_tags_to_sources([sample_sources[0].id], tags=["premium"])

        # Now remove them
        count = source_manager.remove_tags_from_sources([sample_sources[0].id], tags=["premium"])
        assert count == 1

        # Verify tags are removed
        source1 = source_manager.get_source_by_id(sample_sources[0].id)
        assert "premium" not in source1.tags


class TestGroupOperations:
    """Test group CRUD operations."""

    def test_create_group(self, source_manager):
        """Test creating a new group."""
        group = source_manager.create_group(
            name="Test Group",
            description="A test group",
            color="#FF0000",
            priority=1,
            rate_limit_ms=1500,
            enabled=True,
        )

        assert group.id is not None
        assert group.name == "Test Group"
        assert group.description == "A test group"
        assert group.color == "#FF0000"
        assert group.priority == 1
        assert group.rate_limit_ms == 1500
        assert group.enabled is True

    def test_create_duplicate_group(self, source_manager):
        """Test creating a duplicate group (should return existing)."""
        group1 = source_manager.create_group(name="Duplicate Group")
        group2 = source_manager.create_group(name="Duplicate Group")

        assert group1.id == group2.id

    def test_get_group_by_id(self, source_manager, sample_groups):
        """Test getting a group by ID."""
        group = source_manager.get_group_by_id(sample_groups[0].id)
        assert group is not None
        assert group.name == "News Sources"

    def test_get_group_by_name(self, source_manager, sample_groups):
        """Test getting a group by name."""
        group = source_manager.get_group_by_name("Tech Sources")
        assert group is not None
        assert group.id == sample_groups[1].id

    def test_get_all_groups(self, source_manager, sample_groups):
        """Test getting all groups."""
        groups = source_manager.get_all_groups()
        assert len(groups) == 3

    def test_update_group(self, source_manager, sample_groups):
        """Test updating a group."""
        updated = source_manager.update_group(
            sample_groups[0].id, description="Updated description", priority=3
        )

        assert updated is not None
        assert updated.description == "Updated description"
        assert updated.priority == 3

    def test_delete_group(self, source_manager, sample_groups):
        """Test deleting a group."""
        group_id = sample_groups[0].id
        success = source_manager.delete_group(group_id)

        assert success is True

        deleted = source_manager.get_group_by_id(group_id)
        assert deleted is None


class TestGroupSourceAssociation:
    """Test group-source association operations."""

    def test_add_sources_to_group(self, source_manager, sample_sources, sample_groups):
        """Test adding sources to a group."""
        count = source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )

        assert count == 2

        # Verify sources are in group
        group = source_manager.get_group_by_id(sample_groups[0].id)
        group_sources = group.sources.all()
        assert len(group_sources) == 2
        assert sample_sources[0].id in [s.id for s in group_sources]
        assert sample_sources[1].id in [s.id for s in group_sources]

    def test_remove_sources_from_group(self, source_manager, sample_sources, sample_groups):
        """Test removing sources from a group."""
        # First add sources to group
        source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )

        # Now remove one
        count = source_manager.remove_sources_from_group(
            sample_groups[0].id, [sample_sources[0].id]
        )

        assert count == 1

        # Verify source is removed
        group = source_manager.get_group_by_id(sample_groups[0].id)
        group_sources = group.sources.all()
        assert len(group_sources) == 1
        assert sample_sources[0].id not in [s.id for s in group_sources]

    def test_add_source_to_groups(self, source_manager, sample_sources, sample_groups):
        """Test adding a source to multiple groups."""
        count = source_manager.add_source_to_groups(
            sample_sources[0].id, [sample_groups[0].id, sample_groups[1].id]
        )

        assert count == 2

        # Verify source is in both groups
        source = source_manager.get_source_by_id(sample_sources[0].id)
        groups = source.groups.all()
        assert len(groups) == 2

    def test_get_source_groups(self, source_manager, sample_sources, sample_groups):
        """Test getting all groups a source belongs to."""
        # Add source to some groups
        source_manager.add_source_to_groups(
            sample_sources[0].id, [sample_groups[0].id, sample_groups[1].id]
        )

        groups = source_manager.get_source_groups(sample_sources[0].id)
        assert len(groups) == 2


class TestTagBasedGroups:
    """Test tag-based group operations."""

    def test_create_tag_based_group(self, source_manager, sample_sources):
        """Test creating a tag-based group."""
        group = source_manager.create_tag_based_group(name="News Tag Group", tag_pattern="news,uk")

        assert group.is_tag_based is True
        assert group.tag_pattern == "news,uk"

        # Should auto-populate with matching sources
        group_sources = group.sources.all()
        assert len(group_sources) >= 2  # BBC News and The Guardian have news tag

    def test_refresh_tag_based_groups(self, source_manager, sample_sources):
        """Test refreshing all tag-based groups."""
        # Create a tag-based group
        source_manager.create_tag_based_group(name="Tech Tag Group", tag_pattern="technology")

        # Add a new source with technology tag
        source_manager.create_source(
            name="New Tech Source", domain="newtech.com", tags="technology"
        )

        # Refresh groups
        count = source_manager.refresh_tag_based_groups()
        assert count >= 1

        # Verify the new source is in the group
        group = source_manager.get_group_by_name("Tech Tag Group")
        group_sources = group.sources.all()
        source_names = [s.name for s in group_sources]
        assert "New Tech Source" in source_names


class TestMetadataOperations:
    """Test metadata operations."""

    def test_create_metadata(self, source_manager, sample_sources):
        """Test creating metadata for a source."""
        metadata = source_manager.create_metadata(
            sample_sources[0].id,
            language="en",
            country="GB",
            city="London",
            robots_allowed=True,
            alexa_rank=100,
        )

        assert metadata.source_id == sample_sources[0].id
        assert metadata.language == "en"
        # country canonicalised to lowercase ISO-2 (the one conversion layer, 0.09)
        assert metadata.country == "gb"
        assert metadata.city == "London"
        assert metadata.robots_allowed is True
        assert metadata.alexa_rank == 100

    def test_get_metadata(self, source_manager, sample_sources):
        """Test getting metadata for a source."""
        # First create metadata
        source_manager.create_metadata(sample_sources[0].id, language="en", country="GB")

        metadata = source_manager.get_metadata(sample_sources[0].id)
        assert metadata is not None
        assert metadata.language == "en"
        assert metadata.country == "gb"

    def test_update_metadata(self, source_manager, sample_sources):
        """Test updating metadata for a source."""
        # First create metadata
        source_manager.create_metadata(sample_sources[0].id, language="en", country="GB")

        # Update it
        updated = source_manager.update_metadata(
            sample_sources[0].id, language="en-US", city="London"
        )

        assert updated is not None
        assert updated.language == "en-US"
        assert updated.city == "London"

    def test_delete_metadata(self, source_manager, sample_sources):
        """Test deleting metadata for a source."""
        # First create metadata
        source_manager.create_metadata(sample_sources[0].id, language="en")

        # Delete it
        success = source_manager.delete_metadata(sample_sources[0].id)
        assert success is True

        # Verify it's deleted
        metadata = source_manager.get_metadata(sample_sources[0].id)
        assert metadata is None

    def test_get_sources_by_country(self, source_manager, sample_sources):
        """Test getting sources by country."""
        # Add metadata to sources
        source_manager.create_metadata(sample_sources[0].id, country="GB")
        source_manager.create_metadata(sample_sources[1].id, country="US")
        source_manager.create_metadata(sample_sources[2].id, country="GB")

        # Get sources by country — any-case code or full name (one conversion layer)
        gb_sources = source_manager.get_sources_by_country("GB")
        assert len(gb_sources) == 2

        us_sources = source_manager.get_sources_by_country("US")
        assert len(us_sources) == 1

        assert len(source_manager.get_sources_by_country("United Kingdom")) == 2

    def test_get_sources_by_language(self, source_manager, sample_sources):
        """Test getting sources by language."""
        # Add metadata to sources
        source_manager.create_metadata(sample_sources[0].id, language="en")
        source_manager.create_metadata(sample_sources[1].id, language="en")
        source_manager.create_metadata(sample_sources[2].id, language="fr")

        # Get sources by language
        en_sources = source_manager.get_sources_by_language("en")
        assert len(en_sources) == 2

        fr_sources = source_manager.get_sources_by_language("fr")
        assert len(fr_sources) == 1


class TestStatistics:
    """Test statistics operations."""

    def test_get_source_statistics(self, source_manager, sample_sources, sample_groups):
        """Test getting source statistics."""
        # Add some metadata
        source_manager.create_metadata(sample_sources[0].id, country="GB", language="en")
        source_manager.create_metadata(sample_sources[1].id, country="US", language="en")

        stats = source_manager.get_source_statistics()

        assert stats["total_sources"] == 4
        assert stats["enabled_sources"] == 3  # TechCrunch is disabled
        assert stats["disabled_sources"] == 1
        assert stats["total_groups"] == 3
        assert stats["with_metadata"] == 2
        assert stats["with_country"] == 2
        assert stats["with_language"] == 2

        # Check priority counts
        assert stats["priority_counts"]["priority_1"] == 2
        assert stats["priority_counts"]["priority_2"] == 2

        # Check tag counts
        assert "news" in stats["tag_counts"]
        assert stats["tag_counts"]["news"] >= 2


class TestImportExport:
    """Test import/export operations."""

    def test_export_sources_to_yaml(self, source_manager, sample_sources, tmp_path):
        """Test exporting sources to YAML."""
        yaml_path = str(tmp_path / "sources.yml")
        count = source_manager.export_sources_to_yaml(yaml_path)

        assert count == 4

        # Verify file exists and contains data
        import yaml

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        assert "sources" in data
        assert len(data["sources"]) == 4
        assert data["sources"][0]["name"] == "BBC News"

    def test_import_sources_from_yaml(self, source_manager, tmp_path):
        """Test importing sources from YAML."""
        # Create a YAML file
        yaml_content = {
            "project_name": "Test",
            "sources": [
                {
                    "name": "Imported Source 1",
                    "domain": "imported1.com",
                    "rss_url": "https://imported1.com/rss",
                    "rate_limit_ms": 2000,
                    "enabled": True,
                    "priority": 2,
                    "tags": "imported,test",
                },
                {
                    "name": "Imported Source 2",
                    "domain": "imported2.com",
                    "rss_url": "https://imported2.com/rss",
                    "rate_limit_ms": 3000,
                    "enabled": False,
                    "priority": 3,
                    "tags": "imported",
                },
            ],
        }

        yaml_path = str(tmp_path / "import.yml")
        import yaml

        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        # Import the sources
        result = source_manager.import_sources_from_yaml(yaml_path)

        assert result["added"] == 2
        assert result["updated"] == 0
        assert result["skipped"] == 0

        # Verify sources were added
        source1 = source_manager.get_source_by_domain("imported1.com")
        source2 = source_manager.get_source_by_domain("imported2.com")

        assert source1 is not None
        assert source2 is not None
        assert source1.name == "Imported Source 1"
        assert source2.enabled is False


class TestBatchGroupOperations:
    """Test batch operations on groups."""

    def test_enable_groups(self, source_manager, sample_sources, sample_groups):
        """Test enabling all sources in multiple groups."""
        # Add sources to groups
        source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )
        source_manager.add_sources_to_group(sample_groups[1].id, [sample_sources[2].id])

        # Disable all sources first
        source_manager.disable_sources([s.id for s in sample_sources])

        # Enable groups
        count = source_manager.enable_groups([sample_groups[0].id, sample_groups[1].id])
        assert count == 3  # 2 from first group, 1 from second

        # Verify sources in groups are enabled
        sources = []
        for group_id in [sample_groups[0].id, sample_groups[1].id]:
            sources.extend(source_manager.get_sources_by_group(group_id))
        assert all(s.enabled for s in sources)

    def test_disable_groups(self, source_manager, sample_sources, sample_groups):
        """Test disabling all sources in multiple groups."""
        # Add sources to groups
        source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )
        source_manager.add_sources_to_group(sample_groups[1].id, [sample_sources[2].id])

        # Disable groups
        count = source_manager.disable_groups([sample_groups[0].id, sample_groups[1].id])
        assert count == 3

        # Verify sources in groups are disabled
        sources = []
        for group_id in [sample_groups[0].id, sample_groups[1].id]:
            sources.extend(source_manager.get_sources_by_group(group_id))
        assert all(not s.enabled for s in sources)

    def test_set_group_priority(self, source_manager, sample_sources, sample_groups):
        """Test setting priority for all sources in multiple groups."""
        # Add sources to groups
        source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )
        source_manager.add_sources_to_group(sample_groups[1].id, [sample_sources[2].id])

        # Set priority
        count = source_manager.set_group_priority([sample_groups[0].id, sample_groups[1].id], 1)
        assert count == 3

        # Verify priority is set for sources in groups
        sources = []
        for group_id in [sample_groups[0].id, sample_groups[1].id]:
            sources.extend(source_manager.get_sources_by_group(group_id))
        assert all(s.priority == 1 for s in sources)

    def test_set_group_rate_limit(self, source_manager, sample_sources, sample_groups):
        """Test setting rate limit for all sources in multiple groups."""
        # Add sources to groups
        source_manager.add_sources_to_group(
            sample_groups[0].id, [sample_sources[0].id, sample_sources[1].id]
        )
        source_manager.add_sources_to_group(sample_groups[1].id, [sample_sources[2].id])

        # Set rate limit
        count = source_manager.set_group_rate_limit(
            [sample_groups[0].id, sample_groups[1].id], 5000
        )
        assert count == 3

        # Verify rate limit is set for sources in groups
        sources = []
        for group_id in [sample_groups[0].id, sample_groups[1].id]:
            sources.extend(source_manager.get_sources_by_group(group_id))
        assert all(s.rate_limit_ms == 5000 for s in sources)
