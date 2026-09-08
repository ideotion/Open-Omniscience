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

import math
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.services.keyword_extractor import keyword_extractor
from src.services.text_processor import text_processor
from src.utils.logging_config import setup_logging

logger = setup_logging("services.article_intelligence")


class ArticleIntelligenceAnalyzer:
    def __init__(self):
        self.keyword_extractor = keyword_extractor
        self.text_processor = text_processor

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
                    vectorizer = TfidfVectorizer(
                        tokenizer=lambda x: x.split(), lowercase=False, use_idf=False
                    )
                    tfidf_matrix = vectorizer.fit_transform([text1, text2])
                    similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
                    return float(similarity)
            else:
                vec1 = Counter(processed1["words"])
                vec2 = Counter(processed2["words"])
                all_words = set(vec1.keys()) | set(vec2.keys())
                dot_product = sum(vec1.get(w, 0) * vec2.get(w, 0) for w in all_words)
                norm1 = math.sqrt(sum(v**2 for v in vec1.values()))
                norm2 = math.sqrt(sum(v**2 for v in vec2.values()))
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


# Global instance
article_intelligence_analyzer = ArticleIntelligenceAnalyzer()
