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
Article Intelligence Analysis for Open Omniscience

Author: Open Omniscience Team
"""

from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
import math
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.database.models import get_session, Article, Source
from src.services.keyword_extractor import keyword_extractor
from src.services.text_processor import text_processor
from src.utils.logging_config import setup_logging

logger = setup_logging("services.article_intelligence")


class ArticleIntelligenceAnalyzer:
    def __init__(self):
        self.keyword_extractor = keyword_extractor
        self.text_processor = text_processor

    def extract_terms_with_metadata(self, text, language="en"):
        if not text:
            return {"terms": [], "metadata": {}, "statistics": {}}

        processed = self.text_processor.process_text(text, language=language, remove_stopwords=True)
        words = processed["words"]

        ke = self.keyword_extractor
        term_result = ke.extract_keywords(text, language=language)

        word_positions = defaultdict(list)
        for idx, word in enumerate(words):
            word_positions[word].append(idx)

        terms_with_metadata = []
        for term in term_result["keywords"]:
            positions = word_positions.get(term, [])
            if positions:
                terms_with_metadata.append({
                    "term": term,
                    "frequency": len(positions),
                    "first_position": positions[0],
                    "last_position": positions[-1],
                    "all_positions": positions
                })

        return {
            "terms": terms_with_metadata,
            "frequencies": term_result["frequencies"],
            "statistics": term_result
        }

    def calculate_similarity(self, text1, text2, method="cosine", use_tfidf=True):
        """Calculate similarity between two texts."""
        if not text1 or not text2:
            return 0.0
        
        processed1 = self.text_processor.process_text(text1, remove_stopwords=True)
        processed2 = self.text_processor.process_text(text2, remove_stopwords=True)
        
        words1 = set(processed1["words"])
        words2 = set(processed2["words"])
        
        if method == "jaccard":
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            return intersection / union if union > 0 else 0.0
        
        elif method == "cosine":
            if use_tfidf:
                try:
                    vectorizer = TfidfVectorizer(tokenizer=lambda x: x.split(), lowercase=False)
                    tfidf_matrix = vectorizer.fit_transform([text1, text2])
                    similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                    return float(similarity)
                except Exception as e:
                    logger.debug(f"TF-IDF with IDF failed, trying without: {e}")
                    vectorizer = TfidfVectorizer(tokenizer=lambda x: x.split(), lowercase=False, use_idf=False)
                    tfidf_matrix = vectorizer.fit_transform([text1, text2])
                    similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                    return float(similarity)
            else:
                vec1 = Counter(processed1["words"])
                vec2 = Counter(processed2["words"])
                all_words = set(vec1.keys()) | set(vec2.keys())
                dot_product = sum(vec1.get(w, 0) * vec2.get(w, 0) for w in all_words)
                norm1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
                norm2 = math.sqrt(sum(v ** 2 for v in vec2.values()))
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                return dot_product / (norm1 * norm2)
        
        elif method == "euclidean":
            vec1 = Counter(processed1["words"])
            vec2 = Counter(processed2["words"])
            all_words = set(vec1.keys()) | set(vec2.keys())
            distance = math.sqrt(sum((vec1.get(w, 0) - vec2.get(w, 0)) ** 2 for w in all_words))
            max_distance = math.sqrt(len(all_words))
            return 1.0 - (distance / max_distance) if max_distance > 0 else 0.0
        
        elif method == "manhattan":
            vec1 = Counter(processed1["words"])
            vec2 = Counter(processed2["words"])
            all_words = set(vec1.keys()) | set(vec2.keys())
            distance = sum(abs(vec1.get(w, 0) - vec2.get(w, 0)) for w in all_words)
            max_distance = len(all_words)
            return 1.0 - (distance / max_distance) if max_distance > 0 else 0.0
        
        else:
            raise ValueError(f"Unknown similarity method: {method}")

    def group_by_similarity(self, articles, threshold=0.7, method="cosine"):
        """Group articles by similarity using hierarchical clustering."""
        if not articles or len(articles) < 2:
            return [{"cluster_id": 0, "articles": articles, "size": len(articles)}]
        
        texts = [article.get("content", "") for article in articles]
        n = len(texts)
        similarity_matrix = np.zeros((n, n))
        
        for i in range(n):
            for j in range(i, n):
                if i == j:
                    similarity_matrix[i][j] = 1.0
                else:
                    sim = self.calculate_similarity(texts[i], texts[j], method=method)
                    similarity_matrix[i][j] = sim
                    similarity_matrix[j][i] = sim
        
        clusters = [[i] for i in range(n)]
        cluster_merged = [False] * n
        
        for i in range(n):
            if cluster_merged[i]:
                continue
            for j in range(i + 1, n):
                if cluster_merged[j]:
                    continue
                if similarity_matrix[i][j] >= threshold:
                    cluster_i = None
                    cluster_j = None
                    for idx, cluster in enumerate(clusters):
                        if i in cluster:
                            cluster_i = idx
                        if j in cluster:
                            cluster_j = idx
                    if cluster_i is not None and cluster_j is not None and cluster_i != cluster_j:
                        clusters[cluster_i].extend(clusters[cluster_j])
                        del clusters[cluster_j]
                        for member in clusters[cluster_i]:
                            cluster_merged[member] = True
                    elif cluster_i is not None:
                        clusters[cluster_i].append(j)
                        cluster_merged[j] = True
        
        result_clusters = []
        for cluster_idx, cluster in enumerate(clusters):
            cluster_articles = [articles[i] for i in cluster]
            avg_sim = self._calculate_cluster_avg_similarity(cluster, similarity_matrix)
            result_clusters.append({
                "cluster_id": cluster_idx,
                "articles": cluster_articles,
                "size": len(cluster_articles),
                "average_similarity": avg_sim
            })
        
        result_clusters.sort(key=lambda x: x["size"], reverse=True)
        return result_clusters

    def _calculate_cluster_avg_similarity(self, cluster, similarity_matrix):
        if len(cluster) < 2:
            return 1.0
        total = 0.0
        count = 0
        for i in cluster:
            for j in cluster:
                if i != j:
                    total += similarity_matrix[i][j]
                    count += 1
        return total / count if count > 0 else 1.0


# Global instance
article_intelligence_analyzer = ArticleIntelligenceAnalyzer()
