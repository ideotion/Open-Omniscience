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
Network Analyzer Service for Open Omniscience

This module provides functionality for analyzing the network of source relationships,
including graph analysis, centrality measures, and community detection.

Author: Open Omniscience Team
"""

from typing import List, Dict, Optional, Any, Tuple, Set
from datetime import datetime, timezone
import logging
import networkx as nx
import numpy as np

# Configure logging
logger = logging.getLogger(__name__)

# Optional import for visualization
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.warning("matplotlib not available. Network visualization features will be disabled.")


class NetworkAnalyzer:
    """
    Service for analyzing the network of source relationships.
    
    This class provides methods to:
    - Build and analyze source relationship graphs
    - Calculate centrality measures
    - Detect communities
    - Identify influential sources
    - Generate network visualizations
    """
    
    def __init__(self):
        """Initialize the NetworkAnalyzer."""
        # Graph types
        self.graph_types = {
            'directed': 'Directed graph (articles -> sources)',
            'undirected': 'Undirected graph (articles - sources)',
            'bipartite': 'Bipartite graph (articles and sources as separate sets)',
            'weighted': 'Weighted graph (edge weights based on relationship strength)'
        }
        
        # Centrality measures
        self.centrality_measures = {
            'degree': 'Degree centrality',
            'betweenness': 'Betweenness centrality',
            'closeness': 'Closeness centrality',
            'eigenvector': 'Eigenvector centrality',
            'pagerank': 'PageRank',
            'authority': 'Authority score (HITS)',
            'hub': 'Hub score (HITS)'
        }
    
    def build_network_graph(self, relationships: List[Dict[str, Any]], 
                           graph_type: str = 'directed') -> nx.Graph:
        """
        Build a network graph from relationships.
        
        Args:
            relationships: List of relationship dictionaries
            graph_type: Type of graph to build ('directed', 'undirected', 'bipartite', 'weighted')
            
        Returns:
            NetworkX graph object
        """
        if graph_type == 'directed':
            graph = nx.DiGraph()
        else:
            graph = nx.Graph()
        
        # Add nodes and edges
        for rel in relationships:
            article_id = rel.get('article_id')
            source_domain = rel.get('source_domain')
            
            if not article_id or not source_domain:
                continue
            
            # Add nodes with attributes
            if not graph.has_node(article_id):
                graph.add_node(article_id, node_type='article')
            
            if not graph.has_node(source_domain):
                graph.add_node(source_domain, node_type='source')
            
            # Add edge with attributes
            edge_attrs = {
                'relationship_type': rel.get('relationship_type', 'reference'),
                'confidence_score': rel.get('confidence_score', 0.5),
                'time_delta_days': rel.get('time_delta_days'),
                'is_temporal_anomaly': rel.get('is_temporal_anomaly', False)
            }
            
            # For weighted graphs, use confidence score as weight
            if graph_type == 'weighted':
                weight = rel.get('confidence_score', 0.5)
                graph.add_edge(article_id, source_domain, weight=weight, **edge_attrs)
            else:
                graph.add_edge(article_id, source_domain, **edge_attrs)
        
        return graph
    
    def analyze_network(self, relationships: List[Dict[str, Any]], 
                       graph_type: str = 'directed') -> Dict[str, Any]:
        """
        Analyze the network of source relationships.
        
        Args:
            relationships: List of relationship dictionaries
            graph_type: Type of graph to build
            
        Returns:
            Dictionary containing network analysis results
        """
        if not relationships:
            return {
                'graph_type': graph_type,
                'num_nodes': 0,
                'num_edges': 0,
                'node_types': {},
                'edge_types': {},
                'centrality': {},
                'communities': {},
                'influential_sources': []
            }
        
        # Build graph
        graph = self.build_network_graph(relationships, graph_type)
        
        # Basic statistics
        num_nodes = graph.number_of_nodes()
        num_edges = graph.number_of_edges()
        
        # Count node types
        node_types = {}
        for node, attrs in graph.nodes(data=True):
            node_type = attrs.get('node_type', 'unknown')
            node_types[node_type] = node_types.get(node_type, 0) + 1
        
        # Count edge types
        edge_types = {}
        for _, _, attrs in graph.edges(data=True):
            rel_type = attrs.get('relationship_type', 'unknown')
            edge_types[rel_type] = edge_types.get(rel_type, 0) + 1
        
        # Calculate centrality measures
        centrality = self._calculate_centrality_measures(graph, graph_type)
        
        # Detect communities
        communities = self._detect_communities(graph, graph_type)
        
        # Identify influential sources
        influential_sources = self._identify_influential_sources(graph, centrality)
        
        return {
            'graph_type': graph_type,
            'num_nodes': num_nodes,
            'num_edges': num_edges,
            'node_types': node_types,
            'edge_types': edge_types,
            'centrality': centrality,
            'communities': communities,
            'influential_sources': influential_sources,
            'graph_properties': self._calculate_graph_properties(graph)
        }
    
    def _calculate_centrality_measures(self, graph: nx.Graph, graph_type: str) -> Dict[str, Any]:
        """
        Calculate various centrality measures for the graph.
        
        Args:
            graph: NetworkX graph
            graph_type: Type of graph
            
        Returns:
            Dictionary containing centrality measures
        """
        centrality = {}
        
        try:
            # Degree centrality
            if graph_type == 'directed':
                degree_centrality = nx.in_degree_centrality(graph)
            else:
                degree_centrality = nx.degree_centrality(graph)
            centrality['degree'] = dict(degree_centrality)
        except Exception as e:
            logger.warning(f"Error calculating degree centrality: {e}")
            centrality['degree'] = {}
        
        try:
            # Betweenness centrality
            betweenness = nx.betweenness_centrality(graph)
            centrality['betweenness'] = dict(betweenness)
        except Exception as e:
            logger.warning(f"Error calculating betweenness centrality: {e}")
            centrality['betweenness'] = {}
        
        try:
            # Closeness centrality
            if graph_type == 'directed':
                # For directed graphs, we need to handle disconnected components
                if nx.is_strongly_connected(graph):
                    closeness = nx.closeness_centrality(graph)
                else:
                    # Calculate for each weakly connected component
                    closeness = {}
                    for component in nx.weakly_connected_components(graph):
                        subgraph = graph.subgraph(component)
                        if nx.is_strongly_connected(subgraph):
                            component_closeness = nx.closeness_centrality(subgraph)
                            closeness.update(component_closeness)
            else:
                if nx.is_connected(graph):
                    closeness = nx.closeness_centrality(graph)
                else:
                    # Calculate for each connected component
                    closeness = {}
                    for component in nx.connected_components(graph):
                        subgraph = graph.subgraph(component)
                        if nx.is_connected(subgraph):
                            component_closeness = nx.closeness_centrality(subgraph)
                            closeness.update(component_closeness)
            centrality['closeness'] = dict(closeness)
        except Exception as e:
            logger.warning(f"Error calculating closeness centrality: {e}")
            centrality['closeness'] = {}
        
        try:
            # Eigenvector centrality
            if graph_type == 'weighted' and 'weight' in graph.edges(data=True):
                eigenvector = nx.eigenvector_centrality(graph, weight='weight')
            else:
                eigenvector = nx.eigenvector_centrality(graph)
            centrality['eigenvector'] = dict(eigenvector)
        except Exception as e:
            logger.warning(f"Error calculating eigenvector centrality: {e}")
            centrality['eigenvector'] = {}
        
        try:
            # PageRank
            if graph_type == 'weighted' and 'weight' in graph.edges(data=True):
                pagerank = nx.pagerank(graph, weight='weight')
            else:
                pagerank = nx.pagerank(graph)
            centrality['pagerank'] = dict(pagerank)
        except Exception as e:
            logger.warning(f"Error calculating PageRank: {e}")
            centrality['pagerank'] = {}
        
        try:
            # HITS algorithm
            if graph_type == 'directed':
                hits = nx.hits(graph)
                centrality['authority'] = dict(hits[0])
                centrality['hub'] = dict(hits[1])
            else:
                # For undirected graphs, convert to directed first
                directed_graph = graph.to_directed()
                hits = nx.hits(directed_graph)
                centrality['authority'] = dict(hits[0])
                centrality['hub'] = dict(hits[1])
        except Exception as e:
            logger.warning(f"Error calculating HITS: {e}")
            centrality['authority'] = {}
            centrality['hub'] = {}
        
        return centrality
    
    def _detect_communities(self, graph: nx.Graph, graph_type: str) -> Dict[str, Any]:
        """
        Detect communities in the graph.
        
        Args:
            graph: NetworkX graph
            graph_type: Type of graph
            
        Returns:
            Dictionary containing community detection results
        """
        communities = {}
        
        try:
            # For undirected graphs, use Louvain method (requires python-louvain)
            if graph_type != 'directed':
                try:
                    import community as community_louvain
                    partition = community_louvain.best_partition(graph)
                    communities['louvain'] = {
                        'partition': dict(partition),
                        'num_communities': len(set(partition.values())),
                        'modularity': community_louvain.modularity(partition, graph)
                    }
                except ImportError:
                    logger.warning("python-louvain not available for Louvain community detection")
            
            # For directed graphs, use strongly connected components
            if graph_type == 'directed':
                scc = list(nx.strongly_connected_components(graph))
                communities['strongly_connected'] = {
                    'num_components': len(scc),
                    'component_sizes': [len(comp) for comp in scc],
                    'largest_component_size': max(len(comp) for comp in scc) if scc else 0
                }
            
            # Always calculate weakly connected components
            wcc = list(nx.weakly_connected_components(graph) if graph_type == 'directed' 
                      else nx.connected_components(graph))
            communities['weakly_connected'] = {
                'num_components': len(wcc),
                'component_sizes': [len(comp) for comp in wcc],
                'largest_component_size': max(len(comp) for comp in wcc) if wcc else 0
            }
            
        except Exception as e:
            logger.warning(f"Error detecting communities: {e}")
        
        return communities
    
    def _identify_influential_sources(self, graph: nx.Graph, centrality: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Identify influential sources based on centrality measures.
        
        Args:
            graph: NetworkX graph
            centrality: Dictionary of centrality measures
            
        Returns:
            List of influential source dictionaries
        """
        influential_sources = []
        
        # Get source nodes
        source_nodes = [node for node, attrs in graph.nodes(data=True) 
                       if attrs.get('node_type') == 'source']
        
        if not source_nodes:
            return influential_sources
        
        # Calculate composite influence score for each source
        for source in source_nodes:
            influence_score = 0.0
            scores = {}
            
            # Degree centrality
            if centrality.get('degree') and source in centrality['degree']:
                influence_score += centrality['degree'][source] * 0.2
                scores['degree'] = centrality['degree'][source]
            
            # Betweenness centrality
            if centrality.get('betweenness') and source in centrality['betweenness']:
                influence_score += centrality['betweenness'][source] * 0.3
                scores['betweenness'] = centrality['betweenness'][source]
            
            # Closeness centrality
            if centrality.get('closeness') and source in centrality['closeness']:
                influence_score += centrality['closeness'][source] * 0.1
                scores['closeness'] = centrality['closeness'][source]
            
            # Eigenvector centrality
            if centrality.get('eigenvector') and source in centrality['eigenvector']:
                influence_score += centrality['eigenvector'][source] * 0.2
                scores['eigenvector'] = centrality['eigenvector'][source]
            
            # PageRank
            if centrality.get('pagerank') and source in centrality['pagerank']:
                influence_score += centrality['pagerank'][source] * 0.2
                scores['pagerank'] = centrality['pagerank'][source]
            
            # Authority score
            if centrality.get('authority') and source in centrality['authority']:
                influence_score += centrality['authority'][source] * 0.1
                scores['authority'] = centrality['authority'][source]
            
            # Get node attributes
            node_attrs = graph.nodes[source]
            
            influential_sources.append({
                'source': source,
                'influence_score': influence_score,
                'centrality_scores': scores,
                'node_type': node_attrs.get('node_type'),
                'degree': graph.degree(source)
            })
        
        # Sort by influence score
        influential_sources.sort(key=lambda x: x['influence_score'], reverse=True)
        
        # Return top 10
        return influential_sources[:10]
    
    def _calculate_graph_properties(self, graph: nx.Graph) -> Dict[str, Any]:
        """
        Calculate various graph properties.
        
        Args:
            graph: NetworkX graph
            
        Returns:
            Dictionary containing graph properties
        """
        properties = {}
        
        try:
            # Basic properties
            properties['num_nodes'] = graph.number_of_nodes()
            properties['num_edges'] = graph.number_of_edges()
            properties['density'] = nx.density(graph)
            
            # Average degree
            degrees = [degree for _, degree in graph.degree()]
            properties['avg_degree'] = sum(degrees) / len(degrees) if degrees else 0
            
            # For directed graphs
            if isinstance(graph, nx.DiGraph):
                in_degrees = [degree for _, degree in graph.in_degree()]
                out_degrees = [degree for _, degree in graph.out_degree()]
                properties['avg_in_degree'] = sum(in_degrees) / len(in_degrees) if in_degrees else 0
                properties['avg_out_degree'] = sum(out_degrees) / len(out_degrees) if out_degrees else 0
            
            # Connected components
            if isinstance(graph, nx.DiGraph):
                wcc = list(nx.weakly_connected_components(graph))
                scc = list(nx.strongly_connected_components(graph))
                properties['num_weakly_connected_components'] = len(wcc)
                properties['num_strongly_connected_components'] = len(scc)
                properties['largest_weakly_connected_component'] = max(len(comp) for comp in wcc) if wcc else 0
                properties['largest_strongly_connected_component'] = max(len(comp) for comp in scc) if scc else 0
            else:
                cc = list(nx.connected_components(graph))
                properties['num_connected_components'] = len(cc)
                properties['largest_connected_component'] = max(len(comp) for comp in cc) if cc else 0
            
            # Diameter (for connected graphs)
            try:
                if isinstance(graph, nx.DiGraph):
                    if nx.is_strongly_connected(graph):
                        properties['diameter'] = nx.diameter(graph)
                    else:
                        # Try weakly connected
                        undirected_graph = graph.to_undirected()
                        if nx.is_connected(undirected_graph):
                            properties['diameter'] = nx.diameter(undirected_graph)
                        else:
                            properties['diameter'] = None
                else:
                    if nx.is_connected(graph):
                        properties['diameter'] = nx.diameter(graph)
                    else:
                        properties['diameter'] = None
            except Exception as e:
                logger.warning(f"Error calculating diameter: {e}")
                properties['diameter'] = None
            
            # Average path length
            try:
                if isinstance(graph, nx.DiGraph):
                    if nx.is_strongly_connected(graph):
                        properties['avg_path_length'] = nx.average_shortest_path_length(graph)
                    else:
                        undirected_graph = graph.to_undirected()
                        if nx.is_connected(undirected_graph):
                            properties['avg_path_length'] = nx.average_shortest_path_length(undirected_graph)
                        else:
                            properties['avg_path_length'] = None
                else:
                    if nx.is_connected(graph):
                        properties['avg_path_length'] = nx.average_shortest_path_length(graph)
                    else:
                        properties['avg_path_length'] = None
            except Exception as e:
                logger.warning(f"Error calculating average path length: {e}")
                properties['avg_path_length'] = None
            
        except Exception as e:
            logger.warning(f"Error calculating graph properties: {e}")
        
        return properties
    
    def visualize_network(self, graph: nx.Graph, output_file: str = 'network.png',
                         layout: str = 'spring', node_size: int = 50, 
                         with_labels: bool = False) -> bool:
        """
        Generate a visualization of the network graph.
        
        Args:
            graph: NetworkX graph to visualize
            output_file: Output file path
            layout: Layout algorithm ('spring', 'circular', 'random', 'kamada_kawai')
            node_size: Size of nodes in the visualization
            with_labels: Whether to show node labels
            
        Returns:
            True if visualization was generated successfully
        """
        if not HAS_MATPLOTLIB:
            logger.warning("matplotlib not available. Cannot generate network visualization.")
            return False
            
        try:
            plt.figure(figsize=(12, 12))
            
            # Choose layout
            if layout == 'spring':
                pos = nx.spring_layout(graph)
            elif layout == 'circular':
                pos = nx.circular_layout(graph)
            elif layout == 'random':
                pos = nx.random_layout(graph)
            elif layout == 'kamada_kawai':
                pos = nx.kamada_kawai_layout(graph)
            else:
                pos = nx.spring_layout(graph)
            
            # Get node colors based on type
            node_colors = []
            for node in graph.nodes():
                node_type = graph.nodes[node].get('node_type', 'unknown')
                if node_type == 'article':
                    node_colors.append('skyblue')
                elif node_type == 'source':
                    node_colors.append('lightgreen')
                else:
                    node_colors.append('gray')
            
            # Draw nodes
            nx.draw_networkx_nodes(graph, pos, node_size=node_size, 
                                   node_color=node_colors, alpha=0.8)
            
            # Draw edges
            nx.draw_networkx_edges(graph, pos, alpha=0.2)
            
            # Draw labels if requested
            if with_labels:
                labels = {node: node for node in graph.nodes()}
                nx.draw_networkx_labels(graph, pos, labels=labels, font_size=8)
            
            plt.title(f"Source Relationship Network ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)")
            plt.axis('off')
            plt.tight_layout()
            plt.savefig(output_file, dpi=300)
            plt.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Error generating network visualization: {e}")
            return False
    
    def get_network_statistics(self, relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the source relationship network.
        
        Args:
            relationships: List of relationship dictionaries
            
        Returns:
            Dictionary containing network statistics
        """
        if not relationships:
            return {
                'total_articles': 0,
                'total_sources': 0,
                'total_relationships': 0,
                'avg_relationships_per_article': 0,
                'avg_relationships_per_source': 0
            }
        
        # Count unique articles and sources
        articles = set(rel.get('article_id') for rel in relationships if rel.get('article_id'))
        sources = set(rel.get('source_domain') for rel in relationships if rel.get('source_domain'))
        
        total_articles = len(articles)
        total_sources = len(sources)
        total_relationships = len(relationships)
        
        # Calculate averages
        avg_per_article = total_relationships / total_articles if total_articles > 0 else 0
        avg_per_source = total_relationships / total_sources if total_sources > 0 else 0
        
        # Count relationship types
        relationship_types = {}
        for rel in relationships:
            rel_type = rel.get('relationship_type', 'unknown')
            relationship_types[rel_type] = relationship_types.get(rel_type, 0) + 1
        
        # Count source types
        source_types = {}
        for rel in relationships:
            source_type = rel.get('source_type', 'unknown')
            source_types[source_type] = source_types.get(source_type, 0) + 1
        
        # Count temporal anomalies
        temporal_anomalies = sum(1 for rel in relationships if rel.get('is_temporal_anomaly', False))
        
        return {
            'total_articles': total_articles,
            'total_sources': total_sources,
            'total_relationships': total_relationships,
            'avg_relationships_per_article': avg_per_article,
            'avg_relationships_per_source': avg_per_source,
            'relationship_types': relationship_types,
            'source_types': source_types,
            'temporal_anomalies': temporal_anomalies,
            'anomaly_rate': temporal_anomalies / total_relationships if total_relationships > 0 else 0
        }
    
    def find_connected_sources(self, source_domain: str, relationships: List[Dict[str, Any]],
                              max_depth: int = 2) -> Dict[str, Any]:
        """
        Find sources connected to a given source within a certain depth.
        
        Args:
            source_domain: Domain of the source to start from
            relationships: List of relationship dictionaries
            max_depth: Maximum depth to search
            
        Returns:
            Dictionary containing connected sources and relationships
        """
        # Build graph
        graph = self.build_network_graph(relationships, 'undirected')
        
        if not graph.has_node(source_domain):
            return {
                'source': source_domain,
                'connected_sources': [],
                'connected_articles': [],
                'depth': 0
            }
        
        # Find all nodes within max_depth
        connected_nodes = nx.ego_graph(graph, source_domain, radius=max_depth)
        
        # Separate sources and articles
        connected_sources = []
        connected_articles = []
        
        for node in connected_nodes.nodes():
            node_type = connected_nodes.nodes[node].get('node_type', 'unknown')
            if node_type == 'source' and node != source_domain:
                connected_sources.append(node)
            elif node_type == 'article':
                connected_articles.append(node)
        
        return {
            'source': source_domain,
            'connected_sources': connected_sources,
            'connected_articles': connected_articles,
            'depth': max_depth,
            'total_connected': len(connected_sources) + len(connected_articles)
        }
    
    def get_graph_types(self) -> Dict[str, str]:
        """
        Get all available graph types with descriptions.
        
        Returns:
            Dictionary of graph types and descriptions
        """
        return self.graph_types.copy()
    
    def get_centrality_measures(self) -> Dict[str, str]:
        """
        Get all available centrality measures with descriptions.
        
        Returns:
            Dictionary of centrality measures and descriptions
        """
        return self.centrality_measures.copy()