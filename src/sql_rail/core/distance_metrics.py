# sql_guardrail/core/distance_metrics.py
from typing import List, Tuple, Dict, Optional, Literal
from abc import ABC, abstractmethod
import logging
import numpy as np
# from sentence_transformers import SentenceTransformer  # pip install sentence-transformers
from sklearn.metrics.pairwise import cosine_similarity  # pip install scikit-learn
from fuzzywuzzy import fuzz  # pip install fuzzywuzzy[speedup]
import Levenshtein  # python-Levenshtein also provides Jaro-Winkler

logger = logging.getLogger(__name__)

class Distance(ABC):
    """
    Abstract Base Class for all distance and similarity calculation strategies.
    """
    def __init__(self, **kwargs):
        """
        Allows specific distance implementations to accept configuration parameters.
        """
        pass

    @abstractmethod
    def search(self, query_value: str, candidates: List[str], k: int, column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """
        Core method to find top k matching candidates.

        Args:
            query_value: The value from the SQL query.
            candidates: A list of candidate values from the reference data.
            k: The number of top matches to return.
            column_name_or_key: Optional key identifying the candidate set (for preprocessed data).

        Returns:
            A list of tuples, each containing (matching_candidate, similarity_score).
            Similarity score should be normalized to 0.0-1.0 (higher is better).
        """
        pass

    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]):
        """
        Optional method for pre-computation or caching on candidate values.
        Called once when reference data is loaded.
        """
        pass # Default implementation does nothing

    def get_name(self) -> str:
        return self.__class__.__name__

class LevenshteinDistance(Distance):
    """
    Distance metric based on Levenshtein (edit) distance.
    """
    
    def __init__(self, **kwargs):
        """Initialize LevenshteinDistance metric."""
        super().__init__(**kwargs)
    
    def search(self, query_value: str, candidates: List[str], k: int, 
               column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """
        Search for the top-k closest matches using Levenshtein distance.
        
        Args:
            query_value: The value from the SQL query to find matches for
            candidates: List of possible matching values from reference data
            k: Number of top matches to return
            column_name_or_key: Optional column name for cached data
            
        Returns:
            List of tuples (candidate, similarity_score) where similarity_score is between 0.0 and 1.0
        """
        results = []
        for candidate in candidates:
            # Get the maximum possible distance (length of the longer string)
            max_distance = max(len(query_value), len(candidate))
            if max_distance == 0:  # Both strings are empty
                similarity = 1.0
            else:
                # Calculate edit distance and convert to similarity score
                edit_distance = Levenshtein.distance(query_value, candidate)
                similarity = 1.0 - (edit_distance / max_distance)
            
            results.append((candidate, similarity))
        
        # Sort by similarity (higher is better) and take top k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    
    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]) -> None:
        """No preprocessing needed for Levenshtein distance calculation."""
        pass  # No preprocessing required

class JaroWinklerSimilarity(Distance):
    """
    Distance metric based on Jaro-Winkler similarity.
    Good for shorter strings like names.
    """
    
    def __init__(self, **kwargs):
        """Initialize JaroWinklerSimilarity metric."""
        super().__init__(**kwargs)
    
    def search(self, query_value: str, candidates: List[str], k: int,
               column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """
        Search for the top-k closest matches using Jaro-Winkler similarity.
        
        Args:
            query_value: The value from the SQL query to find matches for
            candidates: List of possible matching values from reference data
            k: Number of top matches to return
            column_name_or_key: Optional column name for cached data
            
        Returns:
            List of tuples (candidate, similarity_score) where similarity_score is between 0.0 and 1.0
        """
        results = []
        for candidate in candidates:
            # Jaro-Winkler already returns a value between 0.0 and 1.0
            similarity = Levenshtein.jaro_winkler(query_value, candidate)
            results.append((candidate, similarity))
        
        # Sort by similarity (higher is better) and take top k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    
    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]) -> None:
        """No preprocessing needed for Jaro-Winkler similarity."""
        pass

class TokenSetRatio(Distance):
    """
    Distance metric based on token set ratio from fuzzywuzzy.
    Good for strings where word order doesn't matter or there are extra/missing words.
    """
    
    def __init__(self, **kwargs):
        """Initialize TokenSetRatio metric."""
        super().__init__(**kwargs)
    
    def search(self, query_value: str, candidates: List[str], k: int,
               column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """
        Search for the top-k closest matches using token set ratio.
        
        Args:
            query_value: The value from the SQL query to find matches for
            candidates: List of possible matching values from reference data
            k: Number of top matches to return
            column_name_or_key: Optional column name for cached data
            
        Returns:
            List of tuples (candidate, similarity_score) where similarity_score is between 0.0 and 1.0
        """
        results = []
        for candidate in candidates:
            # fuzzywuzzy's token_set_ratio returns a value between 0 and 100
            # Convert to a 0.0-1.0 range
            ratio = fuzz.token_set_ratio(query_value, candidate) / 100.0
            results.append((candidate, ratio))
        
        # Sort by similarity (higher is better) and take top k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    
    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]) -> None:
        """No preprocessing needed for token set ratio."""
        pass

class SemanticDistance(Distance):
    """
    Distance metric based on semantic similarity using embeddings and cosine similarity.
    Supports multiple embedding models: SentenceTransformer, Word2Vec, or FastText.
    """
    
    def __init__(self, 
                 model_type: Literal['sentence_transformer', 'word2vec', 'fasttext'] = 'sentence_transformer',
                 model_path: str = 'all-MiniLM-L6-v2', 
                 **kwargs):
        """
        Initialize SemanticDistance metric with choice of embedding model.
        
        Args:
            model_type: Type of embedding model to use ('sentence_transformer', 'word2vec', 'fasttext')
            model_path: Path or name of the model to load
            **kwargs: Additional parameters
        """
        super().__init__(**kwargs)
        self.model_type = model_type
        self.model_path = model_path
        self._embeddings_cache = {}
        
        # Initialize the appropriate model based on model_type
        if model_type == 'sentence_transformer':
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_path)
        
        elif model_type == 'word2vec':
            from gensim.models import KeyedVectors, Word2Vec
            
            # Check if it's a binary file (standard .bin) or text format
            try:
                if model_path.endswith('.bin'):
                    self.model = KeyedVectors.load_word2vec_format(model_path, binary=True)
                else:
                    # Try loading as a saved Word2Vec model
                    self.model = Word2Vec.load(model_path)
                    # If it's a full model, get the vectors part
                    if hasattr(self.model, 'wv'):
                        self.model = self.model.wv
            except Exception as e:
                raise ValueError(f"Failed to load Word2Vec model from {model_path}: {e}")
        
        elif model_type == 'fasttext':
            try:
                from gensim.models import FastText
                self.model = FastText.load(model_path)
                if hasattr(self.model, 'wv'):
                    self.model = self.model.wv
            except ImportError:
                # Alternative: Use Facebook's official fastText implementation
                import fasttext
                self.model = fasttext.load_model(model_path)
        else:
            raise ValueError(f"Unsupported model_type: {model_type}. Choose from 'sentence_transformer', 'word2vec', or 'fasttext'")
    
    def _encode_text(self, texts: List[str]) -> np.ndarray:
        """
        Encode texts using the appropriate model.
        
        Args:
            texts: List of texts to encode
            
        Returns:
            ndarray of embeddings
        """
        if self.model_type == 'sentence_transformer':
            return self.model.encode(texts)
        
        elif self.model_type in ['word2vec', 'fasttext']:
            embeddings = []
            
            for text in texts:
                # Split text into words and get embeddings for each word
                words = text.lower().split()
                word_embeddings = []
                
                for word in words:
                    try:
                        if self.model_type == 'fasttext' and hasattr(self.model, 'get_word_vector'):
                            # For Facebook's fastText implementation
                            word_embeddings.append(self.model.get_word_vector(word))
                        else:
                            # For gensim models (Word2Vec or gensim's FastText)
                            word_embeddings.append(self.model[word])
                    except (KeyError, ValueError):
                        # Skip words not in vocabulary
                        continue
                
                if word_embeddings:
                    # Average word embeddings to get text embedding
                    embeddings.append(np.mean(word_embeddings, axis=0))
                else:
                    # No words found in vocabulary - use zeros
                    embedding_size = self.model.vector_size if hasattr(self.model, 'vector_size') else 300
                    embeddings.append(np.zeros(embedding_size))
            
            return np.array(embeddings)
        
        raise ValueError(f"Encoding not implemented for model_type: {self.model_type}")
    
    def search(self, query_value: str, candidates: List[str], k: int,
               column_name_or_key: Optional[str] = None) -> List[Tuple[str, float]]:
        """
        Search for the top-k semantically closest matches using cosine similarity.
        
        Args:
            query_value: The value from the SQL query to find matches for
            candidates: List of possible matching values from reference data
            k: Number of top matches to return
            column_name_or_key: Column name used to retrieve pre-computed embeddings
            
        Returns:
            List of tuples (candidate, similarity_score) where similarity_score is between 0.0 and 1.0
        """
        # Generate embedding for the query
        query_embedding = self._encode_text([query_value])[0]
        
        # Ensure we have embeddings for the candidates
        if not column_name_or_key or column_name_or_key not in self._embeddings_cache:
            self.preprocess_candidates(column_name_or_key or "default", candidates)
            
        cache_key = column_name_or_key or "default"
        # Get candidates' embeddings
        candidate_embeddings = self._embeddings_cache[cache_key]['embeddings']
        
        # Calculate cosine similarity between query and all candidates
        similarities = cosine_similarity([query_embedding], candidate_embeddings)[0]
        
        # Create list of (candidate, similarity) pairs
        results = [(candidates[i], float(similarities[i])) for i in range(len(candidates))]
        
        # Sort by similarity (higher is better) and take top k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    
    def preprocess_candidates(self, column_name_or_key: str, candidates: List[str]) -> None:
        """
        Preprocess candidates by computing and storing their embeddings.
        
        Args:
            column_name_or_key: The column name to use as a key for storing embeddings
            candidates: List of candidate strings to preprocess
        """
        # Generate embeddings for all candidates
        embeddings = self._encode_text(candidates)
        
        # Store in cache
        self._embeddings_cache[column_name_or_key] = {
            'embeddings': embeddings,
            'candidates': candidates  # Store candidates to verify they match later usage
        }
