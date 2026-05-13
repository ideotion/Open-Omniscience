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
Tests for NetworkAnalyzer module
"""

import pytest
from src.analysis.network_analyzer import (
    NetworkAnalyzer, 
    NetworkNode, 
    NetworkEdge, 
    NetworkStatus,
    NetworkType,
    Community
)


@pytest.fixture
def network_analyzer():
    try:
        return NetworkAnalyzer()
    except ImportError:
        pytest.skip("NetworkX not available")


@pytest.fixture
def simple_nodes():
    return [
        NetworkNode(
            node_id="user1",
            node_type="user",
            content="Hello world",
            timestamp="2024-01-01T12:00:00Z"
        ),
        NetworkNode(
            node_id="user2",
            node_type="user", 
            content="Hi there",
            timestamp="2024-01-01T12:01:00Z"
        ),
        NetworkNode(
            node_id="user3",
            node_type="user",
            content="Good morning",
            timestamp="2024-01-01T12:02:00Z"
        )
    ]


@pytest.fixture
def simple_edges():
    return [
        NetworkEdge(
            source="user1",
            target="user2",
            edge_type="mention",
            weight=1.0,
            timestamp="2024-01-01T12:00:30Z"
        ),
        NetworkEdge(
            source="user2",
            target="user3", 
            edge_type="mention",
            weight=1.0,
            timestamp="2024-01-01T12:01:30Z"
        )
    ]


@pytest.fixture
def empty_network():
    return [], []


class TestNetworkAnalyzer:
    def test_initialization(self, network_analyzer):
        assert network_analyzer is not None
        assert hasattr(network_analyzer, 'analyze')
        assert hasattr(network_analyzer, 'check_dependencies')

    def test_empty_network(self, network_analyzer, empty_network):
        nodes, edges = empty_network
        result = network_analyzer.analyze(nodes, edges)
        assert result.status == NetworkStatus.NONE
        assert result.score == 0.0
        assert result.node_count == 0
        assert result.edge_count == 0

    def test_simple_network(self, network_analyzer, simple_nodes, simple_edges):
        result = network_analyzer.analyze(simple_nodes, simple_edges)
        assert result.status in [NetworkStatus.NONE, NetworkStatus.LOW]
        assert result.node_count == 3
        assert result.edge_count == 2
        assert result.community_count >= 1

    def test_check_dependencies(self, network_analyzer):
        deps = network_analyzer.check_dependencies()
        assert "networkx" in deps

    def test_result_serialization(self, network_analyzer, simple_nodes, simple_edges):
        result = network_analyzer.analyze(simple_nodes, simple_edges)
        result_dict = result.to_dict()
        assert "status" in result_dict
        assert "score" in result_dict
        assert "nodes" in result_dict
        assert "edges" in result_dict
        assert "communities" in result_dict
        
        result_json = result.to_json()
        assert isinstance(result_json, str)
        assert len(result_json) > 0


class TestNetworkNode:
    def test_to_dict(self):
        node = NetworkNode(
            node_id="test_user",
            node_type="user",
            content="Test content",
            timestamp="2024-01-01T12:00:00Z"
        )
        node_dict = node.to_dict()
        assert node_dict["node_id"] == "test_user"
        assert node_dict["node_type"] == "user"
        assert node_dict["content"] == "Test content"


class TestNetworkEdge:
    def test_to_dict(self):
        edge = NetworkEdge(
            source="user1",
            target="user2",
            edge_type="mention",
            weight=1.0,
            timestamp="2024-01-01T12:00:00Z"
        )
        edge_dict = edge.to_dict()
        assert edge_dict["source"] == "user1"
        assert edge_dict["target"] == "user2"
        assert edge_dict["weight"] == 1.0


class TestCommunity:
    def test_to_dict(self):
        community = Community(
            community_id=0,
            nodes=["user1", "user2"],
            size=2,
            cohesion=0.8,
            centrality=0.5,
            narrative="test narrative"
        )
        community_dict = community.to_dict()
        assert community_dict["community_id"] == 0
        assert community_dict["size"] == 2
        assert community_dict["narrative"] == "test narrative"
