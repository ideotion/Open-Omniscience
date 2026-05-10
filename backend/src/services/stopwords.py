"""
Stopwords Manager for Open-Omniscience
Multi-language stopwords for text processing
"""

from typing import Set, Dict, Optional
import os
from pathlib import Path


class StopwordsManager:
    """
    Manages stopwords for multiple languages.
    Supports loading from files and in-memory stopword lists.
    """
    
    # Common English stopwords
    ENGLISH_STOPWORDS: Set[str] = {
        'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", 
        "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 
        'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 
        'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 
        'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 
        'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 
        'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 
        'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 
        'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 
        'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 
        'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 
        'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 
        'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 
        'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', "should've", 
        'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', "aren't", 'couldn', 
        "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', "hadn't", 'hasn', 
        "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', "mightn't", 'mustn', 
        "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', "shouldn't", 'wasn', 
        "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', "wouldn't"
    }
    
    # Common French stopwords
    FRENCH_STOPWORDS: Set[str] = {
        'au', 'aux', 'avec', 'ce', 'ces', 'dans', 'de', 'des', 'du', 'elle', 'en', 
        'et', 'eux', 'il', 'je', 'la', 'le', 'les', 'leur', 'lui', 'ma', 'mais', 'me', 
        'même', 'mes', 'moi', 'mon', 'ne', 'nos', 'notre', 'nous', 'on', 'ou', 'par', 
        'pas', 'pour', 'qu', 'que', 'qui', 'sa', 'se', 'ses', 'son', 'sur', 'ta', 'te', 
        'tes', 'toi', 'ton', 'tu', 'un', 'une', 'vos', 'votre', 'vous', 'c', "c'est", 
        "ce", 'cette', 'ces', 'celui', 'celle', 'ceux', 'celles', 'celà', 'ça', 'd', 
        'des', 'un', 'une', 'du', 'de', 'la', 'le', 'les', 'en', 'au', 'aux'
    }
    
    # Common German stopwords
    GERMAN_STOPWORDS: Set[str] = {
        'aber', 'alle', 'allem', 'allen', 'aller', 'alles', 'als', 'also', 'am', 'an', 
        'ander', 'andere', 'anderem', 'anderen', 'anderer', 'anderes', 'anderm', 
        'anderr', 'anders', 'au', 'auch', 'auf', 'aus', 'bei', 'bin', 'bis', 'bist', 
        'da', 'dadurch', 'daher', 'darum', 'das', 'daß', 'die', 'diese', 'dieser', 
        'dieses', 'do', 'dort', 'du', 'durch', 'ein', 'eine', 'einem', 'einen', 
        'einer', 'eines', 'er', 'es', 'euer', 'eure', 'für', 'hat', 'hatte', 'hattest', 
        'hattet', 'hatten', 'hatten', 'habe', 'habt', 'hatte', 'hattest', 'hatten', 
        'hatten', 'hatte', 'hättest', 'hättet', 'hätten', 'hätte', 'ich', 'ihm', 'ihn', 
        'ihnen', 'ihr', 'ihre', 'im', 'in', 'indem', 'ins', 'ist', 'jede', 'jedem', 
        'jeden', 'jeder', 'jedes', 'jener', 'jenes', 'jetzt', 'kann', 'kannst', 
        'können', 'könnt', 'könnte', 'mac', 'machen', 'man', 'manche', 'manchem', 
        'manchen', 'mancher', 'manches', 'mein', 'meine', 'mit', 'muss', 'musst', 
        'muß', 'mußt', 'nach', 'nicht', 'nichts', 'no', 'nur', 'ob', 'oder', 'ohne', 
        'seid', 'sein', 'seine', 'sich', 'sie', 'sind', 'so', 'solche', 'solchem', 
        'solchen', 'solcher', 'solches', 'soll', 'sollen', 'sondern', 'sonst', 'über', 
        'um', 'un', 'uns', 'unser', 'unsere', 'unter', 'v', 'ver', 'vom', 'von', 'vor', 
        'war', 'waren', 'warst', 'was', 'weg', 'weil', 'weiter', 'welche', 'welchem', 
        'welchen', 'welcher', 'welches', 'wenn', 'werde', 'werden', 'wie', 'will', 
        'willst', 'wir', 'wird', 'wirst', 'wo', 'wollen', 'wollt', 'würde', 'würden', 
        'würdest', 'würdet', 'zu', 'zum', 'zur', 'zwar', 'zwischen'
    }
    
    # Common Spanish stopwords
    SPANISH_STOPWORDS: Set[str] = {
        'a', 'al', 'algo', 'algunas', 'algunos', 'ante', 'antes', 'bajo', 'cabe', 
        'cada', 'com', 'como', 'con', 'contra', 'cuando', 'de', 'del', 'des', 'desde', 
        'donde', 'durante', 'e', 'el', 'la', 'lo', 'los', 'las', 'le', 'les', 'se', 
        'es', 'y', 'o', 'u', 'un', 'una', 'unos', 'unas', 'que', 'qui', 'quien', 'quienes', 
        'que', 'el', 'la', 'lo', 'las', 'los', 'un', 'una', 'unos', 'unas', 'ser', 'es', 
        'son', 'con', 'por', 'para', 'no', 'una', 'su', 'sus', 'este', 'esta', 'estos', 
        'estas', 'ese', 'esa', 'esos', 'esas', 'aquel', 'aquella', 'aquellos', 'aquellas', 
        'mi', 'mis', 'tu', 'tus', 'su', 'sus', 'nuestro', 'nuestra', 'nuestros', 
        'nuestras', 'vuestro', 'vuestra', 'vuestros', 'vuestras', 'al', 'algun', 
        'alguna', 'algunos', 'algunas', 'ningun', 'ninguna', 'ningunos', 'ningunas', 
        'algo', 'nada', 'alguien', 'nadie', 'cual', 'cuales', 'cualquier', 'cualquiera', 
        'cualesquiera', 'cuanto', 'cuanta', 'cuantos', 'cuantas', 'cuanto', 'donde', 
        'adonde', 'si', 'no', 'tampoco', 'tambien', 'o', 'u', 'ya', 'aun', 'aunque', 
        'pero', 'mas', 'sino', 'sin', 'sobre', 'bajo', 'entre', 'hacia', 'hasta', 
        'para', 'por', 'según', 'sin', 'so', 'sobre', 'tras', 'versus', 'via'
    }
    
    # Language to stopwords mapping
    LANGUAGE_STOPWORDS: Dict[str, Set[str]] = {
        'en': ENGLISH_STOPWORDS,
        'english': ENGLISH_STOPWORDS,
        'fr': FRENCH_STOPWORDS,
        'french': FRENCH_STOPWORDS,
        'de': GERMAN_STOPWORDS,
        'german': GERMAN_STOPWORDS,
        'es': SPANISH_STOPWORDS,
        'spanish': SPANISH_STOPWORDS,
    }
    
    def __init__(self, custom_stopwords: Optional[Set[str]] = None):
        """
        Initialize the stopwords manager.
        
        Args:
            custom_stopwords: Optional set of custom stopwords to add
        """
        self.custom_stopwords: Set[str] = custom_stopwords or set()
        self._loaded_stopwords: Dict[str, Set[str]] = {}
        
    def get_stopwords(self, language: str = 'en') -> Set[str]:
        """
        Get stopwords for a specific language.
        
        Args:
            language: Language code ('en', 'fr', 'de', 'es') or full name
            
        Returns:
            Set of stopwords for the specified language
        """
        language = language.lower()
        
        # Check if already loaded
        if language in self._loaded_stopwords:
            return self._loaded_stopwords[language]
        
        # Try to get from built-in
        if language in self.LANGUAGE_STOPWORDS:
            stopwords = self.LANGUAGE_STOPWORDS[language].copy()
            stopwords.update(self.custom_stopwords)
            self._loaded_stopwords[language] = stopwords
            return stopwords
        
        # Try to load from file
        stopwords = self._load_stopwords_from_file(language)
        if stopwords:
            stopwords.update(self.custom_stopwords)
            self._loaded_stopwords[language] = stopwords
            return stopwords
        
        # Fallback to English
        stopwords = self.ENGLISH_STOPWORDS.copy()
        stopwords.update(self.custom_stopwords)
        self._loaded_stopwords[language] = stopwords
        return stopwords
    
    def _load_stopwords_from_file(self, language: str) -> Optional[Set[str]]:
        """
        Load stopwords from a file if available.
        
        Args:
            language: Language code
            
        Returns:
            Set of stopwords or None if file not found
        """
        # Try common file locations
        possible_paths = [
            Path('/workspace/open-omniscience/data/stopwords') / f'{language}.txt',
            Path('/workspace/open-omniscience/backend/src/services/stopwords') / f'{language}.txt',
        ]
        
        for path in possible_paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        stopwords = {line.strip().lower() for line in f if line.strip()}
                    return stopwords
                except Exception:
                    continue
        
        return None
    
    def add_custom_stopwords(self, stopwords: Set[str]) -> None:
        """
        Add custom stopwords to all languages.
        
        Args:
            stopwords: Set of stopwords to add
        """
        self.custom_stopwords.update(stopwords)
        # Clear cache to force reload
        self._loaded_stopwords.clear()
    
    def is_stopword(self, word: str, language: str = 'en') -> bool:
        """
        Check if a word is a stopword.
        
        Args:
            word: Word to check
            language: Language code
            
        Returns:
            True if the word is a stopword, False otherwise
        """
        stopwords = self.get_stopwords(language)
        return word.lower() in stopwords
    
    def filter_stopwords(self, words: list, language: str = 'en') -> list:
        """
        Filter stopwords from a list of words.
        
        Args:
            words: List of words to filter
            language: Language code
            
        Returns:
            List of words with stopwords removed
        """
        stopwords = self.get_stopwords(language)
        return [word for word in words if word.lower() not in stopwords]


# Global instance
stopwords_manager = StopwordsManager()
