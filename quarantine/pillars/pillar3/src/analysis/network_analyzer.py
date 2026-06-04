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
Network Analysis Module

Analyzes social networks and information spread patterns to detect
disinformation campaigns using 100% FOSS libraries. Works completely offline.

Features:
- Network construction from media items
- Community detection (Louvain, Leiden)
- Centrality analysis
- Narrative clustering
- Temporal analysis
- Influence mapping
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

try:
    import community as community_louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False

try:
    import igraph
    HAS_IGRAPH = True
except ImportError:
    HAS_IGRAPH = False

try:
    import leidenalg
    HAS_LEIDEN = True
except ImportError:
    HAS_LEIDEN = False


class NetworkStatus(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class NetworkType(Enum):
    SOCIAL = "social"
    INFORMATION = "information"
    COLLABORATION = "collaboration"
    CITATION = "citation"


@dataclass
class NetworkNode:
    node_id: str
    node_type: str
    content: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    centrality: Dict[str, float] = field(default_factory=dict)
    community: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "centrality": self.centrality,
            "community": self.community,
        }


@dataclass
class NetworkEdge:
    source: str
    target: str
    edge_type: str
    weight: float
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class Community:
    community_id: int
    nodes: List[str]
    size: int
    cohesion: float
    centrality: float
    narrative: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "community_id": self.community_id,
            "nodes": self.nodes,
            "size": self.size,
            "cohesion": self.cohesion,
            "centrality": self.centrality,
            "narrative": self.narrative,
        }


@dataclass
class NetworkAnalysisResult:
    status: NetworkStatus
    confidence: float
    score: float
    nodes: List[NetworkNode] = field(default_factory=list)
    edges: List[NetworkEdge] = field(default_factory=list)
    communities: List[Community] = field(default_factory=list)
    centrality_metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)
    network_metrics: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    processing_time: float = 0.0
    timestamp: str = ""
    model_version: str = "1.0.0"
    
    @property
    def has_anomalies(self) -> bool:
        return len(self.anomalies) > 0
    
    @property
    def community_count(self) -> int:
        return len(self.communities)
    
    @property
    def node_count(self) -> int:
        return len(self.nodes)
    
    @property
    def edge_count(self) -> int:
        return len(self.edges)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "score": self.score,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "communities": [c.to_dict() for c in self.communities],
            "centrality_metrics": self.centrality_metrics,
            "network_metrics": self.network_metrics,
            "anomalies": self.anomalies,
            "processing_time": self.processing_time,
            "timestamp": self.timestamp,
            "has_anomalies": self.has_anomalies,
            "community_count": self.community_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class NetworkAnalyzer:
    """
    Analyzes networks for disinformation campaign detection.
    
    Example usage:
        analyzer = NetworkAnalyzer()
        nodes = [NetworkNode(node_id="user1", node_type="user", content="Hello", timestamp="2024-01-01")]
        edges = [NetworkEdge(source="user1", target="user2", edge_type="mention", weight=1.0, timestamp="2024-01-01")]
        result = analyzer.analyze(nodes, edges)
        print(f"Network status: {result.status}")
        print(f"Communities found: {result.community_count}")
    """
    
    def __init__(self):
        self._check_dependencies()
    
    def _check_dependencies(self) -> None:
        if not HAS_NETWORKX:
            raise ImportError("NetworkX is required for network analysis. Install with: pip install networkx")
    
    def _get_timestamp(self) -> str:
        return datetime.utcnow().isoformat() + 'Z'
    
    def analyze(
        self,
        nodes: List[NetworkNode],
        edges: List[NetworkEdge],
        network_type: NetworkType = NetworkType.INFORMATION
    ) -> NetworkAnalysisResult:
        import time
        start_time = time.time()
        
        if not nodes and not edges:
            return NetworkAnalysisResult(
                status=NetworkStatus.NONE,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
            )
        
        # Build NetworkX graph
        graph = self._build_graph(nodes, edges)
        
        # Calculate network metrics
        network_metrics = self._calculate_network_metrics(graph)
        
        # Calculate centrality metrics
        centrality_metrics = self._calculate_centrality(graph)
        
        # Detect communities
        communities = self._detect_communities(graph)
        
        # Detect anomalies
        anomalies = self._detect_anomalies(graph, centrality_metrics, communities)
        
        # Calculate confidence and score
        confidence = self._calculate_confidence(anomalies, network_metrics)
        score = confidence * 100.0
        
        # Determine status
        if score >= 80:
            status = NetworkStatus.EXTREME
        elif score >= 60:
            status = NetworkStatus.HIGH
        elif score >= 40:
            status = NetworkStatus.MEDIUM
        elif score >= 20:
            status = NetworkStatus.LOW
        else:
            status = NetworkStatus.NONE
        
        # Update nodes with centrality and community info
        updated_nodes = self._update_nodes_with_metrics(nodes, centrality_metrics, communities)
        
        processing_time = time.time() - start_time
        
        return NetworkAnalysisResult(
            status=status,
            confidence=confidence,
            score=score,
            nodes=updated_nodes,
            edges=edges,
            communities=communities,
            centrality_metrics=centrality_metrics,
            network_metrics=network_metrics,
            anomalies=anomalies,
            processing_time=processing_time,
            timestamp=self._get_timestamp(),
        )
    
    def _build_graph(self, nodes: List[NetworkNode], edges: List[NetworkEdge]) -> "nx.Graph":
        graph = nx.Graph()
        
        # Add nodes
        for node in nodes:
            graph.add_node(
                node.node_id,
                node_type=node.node_type,
                content=node.content,
                timestamp=node.timestamp,
                metadata=node.metadata
            )
        
        # Add edges
        for edge in edges:
            graph.add_edge(
                edge.source,
                edge.target,
                edge_type=edge.edge_type,
                weight=edge.weight,
                timestamp=edge.timestamp,
                metadata=edge.metadata
            )
        
        return graph
    
    def _calculate_network_metrics(self, graph: "nx.Graph") -> Dict[str, float]:
        metrics = {}
        
        if len(graph.nodes) > 0:
            metrics["num_nodes"] = len(graph.nodes)
            metrics["num_edges"] = len(graph.edges)
            metrics["density"] = nx.density(graph)
            metrics["average_degree"] = sum(dict(graph.degree()).values()) / len(graph.nodes)
            metrics["average_clustering"] = nx.average_clustering(graph)
            metrics["transitivity"] = nx.transitivity(graph)
            
            if nx.is_connected(graph):
                metrics["diameter"] = nx.diameter(graph)
                metrics["average_shortest_path"] = nx.average_shortest_path_length(graph)
            else:
                metrics["diameter"] = 0.0
                metrics["average_shortest_path"] = 0.0
        
        return metrics
    
    def _calculate_centrality(self, graph: "nx.Graph") -> Dict[str, Dict[str, float]]:
        centrality = {}
        
        if len(graph.nodes) > 0:
            # Degree centrality
            degree_centrality = nx.degree_centrality(graph)
            centrality["degree"] = degree_centrality
            
            # Betweenness centrality
            betweenness = nx.betweenness_centrality(graph)
            centrality["betweenness"] = betweenness
            
            # Closeness centrality
            closeness = nx.closeness_centrality(graph)
            centrality["closeness"] = closeness
            
            # Eigenvector centrality
            try:
                eigenvector = nx.eigenvector_centrality(graph)
                centrality["eigenvector"] = eigenvector
            except nx.PowerIterationFailedConvergence:
                centrality["eigenvector"] = {}
            
            # PageRank
            pagerank = nx.pagerank(graph)
            centrality["pagerank"] = pagerank
        
        return centrality
    
    def _detect_communities(self, graph: "nx.Graph") -> List[Community]:
        communities = []
        
        if len(graph.nodes) == 0:
            return communities
        
        # Try Louvain method first
        if HAS_LOUVAIN:
            try:
                partition = community_louvain.best_partition(graph)
                for community_id, nodes in self._group_by_community(partition).items():
                    community_nodes = list(nodes)
                    subgraph = graph.subgraph(community_nodes)
                    communities.append(Community(
                        community_id=community_id,
                        nodes=community_nodes,
                        size=len(community_nodes),
                        cohesion=nx.average_clustering(subgraph),
                        centrality=self._calculate_community_centrality(subgraph),
                        narrative=self._extract_narrative(community_nodes)
                    ))
                return communities
            except Exception:
                pass
        
        # Try Leiden algorithm
        if HAS_LEIDEN and HAS_IGRAPH:
            try:
                ig_graph = igraph.Graph.from_networkx(graph)
                partition = leidenalg.find_partition(ig_graph, leidenalg.RBConfigurationVertexPartition)
                for i, community_nodes in enumerate(partition):
                    subgraph = graph.subgraph(community_nodes)
                    communities.append(Community(
                        community_id=i,
                        nodes=list(community_nodes),
                        size=len(community_nodes),
                        cohesion=nx.average_clustering(subgraph),
                        centrality=self._calculate_community_centrality(subgraph),
                        narrative=self._extract_narrative(list(community_nodes))
                    ))
                return communities
            except Exception:
                pass
        
        # Fallback: use connected components
        for i, component in enumerate(nx.connected_components(graph)):
            subgraph = graph.subgraph(component)
            communities.append(Community(
                community_id=i,
                nodes=list(component),
                size=len(component),
                cohesion=nx.average_clustering(subgraph),
                centrality=self._calculate_community_centrality(subgraph),
                narrative=self._extract_narrative(list(component))
            ))
        
        return communities
    
    def _group_by_community(self, partition: Dict[str, int]) -> Dict[int, Set[str]]:
        communities = {}
        for node, community_id in partition.items():
            if community_id not in communities:
                communities[community_id] = set()
            communities[community_id].add(node)
        return communities
    
    def _calculate_community_centrality(self, subgraph: "nx.Graph") -> float:
        if len(subgraph.nodes) == 0:
            return 0.0
        try:
            centrality = nx.degree_centrality(subgraph)
            return sum(centrality.values()) / len(centrality)
        except Exception:
            return 0.0
    
    def _extract_narrative(self, nodes: List[str]) -> str:
        # Extract common themes from node content
        contents = []
        for node in nodes:
            if hasattr(node, 'content'):
                contents.append(node)
            elif isinstance(node, str):
                # Look up node in original nodes
                pass
        
        if not contents:
            return ""
        
        # Simple narrative extraction - find most common words
        from collections import Counter
        all_words = []
        for content in contents:
            words = re.findall(r'\b\w+\b', content.lower())
            all_words.extend(words)
        
        if not all_words:
            return ""
        
        word_counts = Counter(all_words)
        # Remove common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        for stop_word in stop_words:
            word_counts.pop(stop_word, None)
        
        top_words = word_counts.most_common(5)
        return " ".join([word for word, count in top_words])
    
    def _detect_anomalies(
        self,
        graph: "nx.Graph",
        centrality_metrics: Dict[str, Dict[str, float]],
        communities: List[Community]
    ) -> List[Dict[str, Any]]:
        anomalies = []
        
        # Detect high centrality nodes (potential influencers)
        if "degree" in centrality_metrics:
            degree_centrality = centrality_metrics["degree"]
            avg_degree = sum(degree_centrality.values()) / len(degree_centrality) if degree_centrality else 0
            for node, centrality in degree_centrality.items():
                if centrality > avg_degree * 3:  # 3x above average
                    anomalies.append({
                        "type": "high_centrality",
                        "node": node,
                        "centrality": centrality,
                        "severity": "high",
                        "description": f"Node {node} has unusually high degree centrality"
                    })
        
        # Detect bridge nodes between communities
        if len(communities) > 1:
            for community in communities:
                for node in community.nodes:
                    # Check connections to other communities
                    neighbors = list(graph.neighbors(node))
                    other_communities = set()
                    for neighbor in neighbors:
                        for other_community in communities:
                            if neighbor in other_community.nodes and other_community.community_id != community.community_id:
                                other_communities.add(other_community.community_id)
                    
                    if len(other_communities) >= 2:
                        anomalies.append({
                            "type": "bridge_node",
                            "node": node,
                            "communities_connected": len(other_communities),
                            "severity": "medium",
                            "description": f"Node {node} connects {len(other_communities)} communities"
                        })
        
        # Detect isolated nodes
        for node in graph.nodes():
            if graph.degree(node) == 0:
                anomalies.append({
                    "type": "isolated_node",
                    "node": node,
                    "severity": "low",
                    "description": f"Node {node} is isolated"
                })
        
        return anomalies
    
    def _calculate_confidence(self, anomalies: List[Dict[str, Any]], network_metrics: Dict[str, float]) -> float:
        if not anomalies:
            return 0.0
        
        severity_weights = {"low": 0.1, "medium": 0.3, "high": 0.5, "critical": 0.8}
        total_weight = 0.0
        
        for anomaly in anomalies:
            severity = anomaly.get("severity", "low")
            total_weight += severity_weights.get(severity, 0.1)
        
        # Normalize by number of nodes
        num_nodes = network_metrics.get("num_nodes", 1)
        anomaly_density = len(anomalies) / num_nodes if num_nodes > 0 else 0
        
        return min(1.0, total_weight * anomaly_density * 0.5)
    
    def _update_nodes_with_metrics(
        self,
        nodes: List[NetworkNode],
        centrality_metrics: Dict[str, Dict[str, float]],
        communities: List[Community]
    ) -> List[NetworkNode]:
        updated_nodes = []
        node_community_map = {}
        
        for community in communities:
            for node_id in community.nodes:
                node_community_map[node_id] = community.community_id
        
        for node in nodes:
            # Update centrality
            node_centrality = {}
            for metric_name, metric_values in centrality_metrics.items():
                if node.node_id in metric_values:
                    node_centrality[metric_name] = metric_values[node.node_id]
            
            # Update community
            node_community = node_community_map.get(node.node_id, 0)
            
            updated_node = NetworkNode(
                node_id=node.node_id,
                node_type=node.node_type,
                content=node.content,
                timestamp=node.timestamp,
                metadata=node.metadata,
                centrality=node_centrality,
                community=node_community
            )
            updated_nodes.append(updated_node)
        
        return updated_nodes
    
    def check_dependencies(self) -> Dict[str, bool]:
        return {
            "networkx": HAS_NETWORKX,
            "louvain": HAS_LOUVAIN,
            "igraph": HAS_IGRAPH,
            "leiden": HAS_LEIDEN,
        }
    
    def get_community_descriptions(self) -> Dict[str, str]:
        return {
            "louvain": "Louvain method for community detection (fast, good quality)",
            "leiden": "Leiden algorithm for community detection (improved Louvain)",
            "connected_components": "Connected components as fallback community detection",
        }
