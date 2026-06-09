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
Keyword Extractor for Open Omniscience

This module provides comprehensive keyword extraction capabilities for articles.

Author: Open Omniscience Team
"""

import logging
from collections import Counter

logger = logging.getLogger(__name__)


class KeywordExtractor:
    """Extracts keywords from articles and text content."""
    
    def __init__(self, min_keyword_length=3, max_keyword_length=50, min_frequency=1):
        from .stopwords import stopwords_manager as default_stopwords
        from .text_processor import text_processor as default_text_processor
        
        self.text_processor = default_text_processor
        self.stopwords_manager = default_stopwords
        self.min_keyword_length = min_keyword_length
        self.max_keyword_length = max_keyword_length
        self.min_frequency = min_frequency
        
        self.keyword_categories = {
            "politics": {"politics", "political", "government", "election", "president", "policy"},
            "economy": {"economy", "economic", "finance", "money", "market", "trade"},
            "technology": {"technology", "tech", "computer", "software", "internet", "ai"},
            "health": {"health", "medical", "doctor", "hospital", "disease", "vaccine"},
            "science": {"science", "research", "study", "discovery", "physics", "chemistry"},
            "sports": {"sport", "sports", "game", "football", "basketball", "tennis"},
            "entertainment": {"entertainment", "movie", "film", "music", "actor", "singer"},
            "crime": {"crime", "criminal", "theft", "murder", "police", "arrest"},
            "education": {"education", "school", "university", "student", "teacher", "learning"},
        }
    
    def extract_keywords(self, text, language="en", include_ngrams=True, 
                         ngram_range=(1, 3), min_frequency=None, remove_stopwords=True):
        if not text:
            return {
                "keywords": [], "unigrams": [], "bigrams": [], "trigrams": [],
                "frequencies": {}, "language": language, "total_words": 0, "unique_words": 0
            }
        
        min_freq = min_frequency if min_frequency is not None else self.min_frequency
        
        processed = self.text_processor.process_text(
            text, language=language, remove_stopwords=remove_stopwords,
            include_ngrams=include_ngrams, ngram_range=ngram_range
        )
        
        words = processed["words"]
        frequencies = Counter(words)
        
        filtered_keywords = [
            word for word, count in frequencies.items()
            if count >= min_freq and self.min_keyword_length <= len(word) <= self.max_keyword_length
        ]
        filtered_keywords.sort(key=lambda x: frequencies[x], reverse=True)
        
        unigrams = [w for w in filtered_keywords if len(w.split()) == 1]
        bigrams = [w for w in filtered_keywords if len(w.split()) == 2] if include_ngrams else []
        trigrams = [w for w in filtered_keywords if len(w.split()) == 3] if include_ngrams else []
        
        return {
            "keywords": filtered_keywords, "unigrams": unigrams,
            "bigrams": bigrams, "trigrams": trigrams,
            "frequencies": dict(frequencies), "language": language,
            "total_words": len(words), "unique_words": len(frequencies)
        }
    
    def extract_keywords_from_article(self, article_text, title="", language="en", title_weight=2.0):
        text_result = self.extract_keywords(article_text, language)
        
        if not title:
            return text_result
        
        title_result = self.extract_keywords(title, language)
        combined_freq = Counter(text_result["frequencies"])
        for word, count in title_result["frequencies"].items():
            combined_freq[word] += count * title_weight
        
        filtered_keywords = [
            word for word, count in combined_freq.items()
            if count >= self.min_frequency and self.min_keyword_length <= len(word) <= self.max_keyword_length
        ]
        filtered_keywords.sort(key=lambda x: combined_freq[x], reverse=True)
        
        text_result["keywords"] = filtered_keywords
        text_result["frequencies"] = dict(combined_freq)
        text_result["title_keywords"] = title_result["keywords"]
        return text_result
    
    def categorize_keywords(self, keywords):
        categories = {category: [] for category in self.keyword_categories}
        uncategorized = []
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            categorized = False
            for category, category_words in self.keyword_categories.items():
                if keyword_lower in category_words:
                    categories[category].append(keyword)
                    categorized = True
                    break
            if not categorized:
                uncategorized.append(keyword)
        
        categories["uncategorized"] = uncategorized
        return categories
    
    def get_top_keywords(self, text, language="en", top_n=10, include_scores=False):
        result = self.extract_keywords(text, language)
        
        if not include_scores:
            top_keywords = sorted(
                result["frequencies"].items(), key=lambda x: x[1], reverse=True
            )[:top_n]
            return top_keywords
        else:
            scores = self.calculate_keyword_scores(
                result["keywords"], result["frequencies"], len(text), result["total_words"]
            )
            top_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
            return top_keywords
    
    def calculate_keyword_scores(self, keywords, frequencies, text_length, total_words):
        scores = {}
        for keyword in keywords:
            frequency = frequencies.get(keyword, 0)
            tf = frequency / total_words if total_words > 0 else 0
            idf = 1.0
            length_score = min(1.0, len(keyword) / 10)
            score = (tf * idf) * (1 + length_score)
            scores[keyword] = round(score, 6)
        return scores
    
    def extract_key_phrases(self, text, language="en", min_phrase_length=2, 
                           max_phrase_length=5, top_n=10):
        tokens = self.text_processor.tokenize(text)
        phrases = []
        for length in range(min_phrase_length, max_phrase_length + 1):
            phrases.extend(self.text_processor.extract_ngrams(tokens, length))
        if not phrases:
            return []
        phrase_freq = Counter(phrases)
        top_phrases = sorted(phrase_freq.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [phrase for phrase, freq in top_phrases]
    
    def get_keyword_statistics(self, text, language="en"):
        result = self.extract_keywords(text, language)
        freq_values = list(result["frequencies"].values())
        
        def calculate_median(values):
            if not values:
                return 0.0
            sorted_values = sorted(values)
            n = len(sorted_values)
            mid = n // 2
            if n % 2 == 0:
                return (sorted_values[mid - 1] + sorted_values[mid]) / 2
            else:
                return float(sorted_values[mid])
        
        return {
            "total_keywords": len(result["keywords"]),
            "total_unigrams": len(result["unigrams"]),
            "total_bigrams": len(result["bigrams"]),
            "total_trigrams": len(result["trigrams"]),
            "total_words": result["total_words"],
            "unique_words": result["unique_words"],
            "avg_frequency": sum(freq_values) / len(freq_values) if freq_values else 0,
            "max_frequency": max(freq_values) if freq_values else 0,
            "min_frequency": min(freq_values) if freq_values else 0,
            "median_frequency": calculate_median(freq_values) if freq_values else 0,
            "language": result["language"],
            "categories": self.categorize_keywords(result["keywords"]),
            "top_keywords": self.get_top_keywords(text, language, top_n=10, include_scores=False),
        }


keyword_extractor = KeywordExtractor()
