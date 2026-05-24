# """
# Semantic caching layer for Text-to-SQL queries.
# Reduces latency by caching query results based on semantic similarity.
# """

# from typing import Optional, Tuple, Any
# import hashlib
# import json
# from diskcache import Cache
# from loguru import logger
# # from langchain_huggingface import HuggingFaceEmbeddings
# from .embeddings import get_embeddings
# import numpy as np
# from ..config import settings

# class SemanticCache:
#     """
#     Semantic cache that stores query results indexed by question embeddings.
#     Uses cosine similarity to match semantically similar questions.
#     """
    
#     def __init__(self):
#         self.enabled = settings.enable_semantic_cache
#         self.threshold = settings.cache_similarity_threshold
        
#         if not self.enabled:
#             logger.info("Semantic cache disabled")
#             return
        
#         # Initialize disk cache
#         self.cache = Cache("./cache/semantic_cache")
        
#         # Initialize embedding model with HuggingFace (local)
#         # self.embeddings = HuggingFaceEmbeddings(
#         #     model_name=settings.embedding_model
#         # )
#         self.embeddings = get_embeddings()
        
#         logger.info(f"Semantic cache initialized (threshold: {self.threshold})")
        
#     def _compute_embedding(self, text: str) -> np.ndarray:
#         """Compute embedding vector for text."""
#         try:
#             embedding = self.embeddings.embed_query(text)
#             return np.array(embedding)
#         except Exception as e:
#             logger.error(f"Embedding error: {e}")
#             return None
            
#     def get(self, question: str) -> Optional[dict]:
#         """
#         Retrieve cached result for a question.
        
#         Args:
#             question: User's question
            
#         Returns:
#             Cached result dict or None if no match
#         """
#         if not self.enabled:
#             return None
        
#         try:
#             # Compute embedding for question
#             query_embedding = self._compute_embedding(question)
#             if query_embedding is None:
#                 return None
            
#             # Get all cached items
#             # In production, use a vector database (ChromaDB, Pinecone, etc.)
#             # For simplicity, we iterate through cache
#             best_match = None
#             best_similarity = 0.0
            
#             for key in self.cache:
#                 if key.startswith("embedding_"):
#                     cached_data = self.cache[key]
#                     cached_embedding = np.array(cached_data["embedding"])
                    
#                     similarity = self._cosine_similarity(query_embedding, cached_embedding)
                    
#                     if similarity > best_similarity and similarity >= self.threshold:
#                         best_similarity = similarity
#                         best_match = cached_data
            
#             if best_match:
#                 logger.info(f"✓ Cache HIT (similarity: {best_similarity:.3f})")
#                 return best_match["result"]
#             else:
#                 logger.info("✗ Cache MISS")
#                 return None
                
#         except Exception as e:
#             logger.error(f"Cache retrieval error: {e}")
#             return None
        
#     def set(self, question: str, result: dict):
#         """
#         Store query result in cache.
        
#         Args:
#             question: User's question
#             result: Result dict to cache
#         """
#         if not self.enabled:
#             return
        
#         try:
#             # Compute embedding
#             embedding = self._compute_embedding(question)
#             if embedding is None:
#                 return
            
#             # Create cache key
#             key = f"embedding_{hashlib.md5(question.encode()).hexdigest()}"
            
#             # Store with embedding
#             cache_data = {
#                 "question": question,
#                 "embedding": embedding.tolist(),
#                 "result": result
#             }
            
#             self.cache[key] = cache_data
#             logger.info(f"✓ Cached result for question")
            
#         except Exception as e:
#             logger.error(f"Cache storage error: {e}")
    
#     def clear(self):
#         """Clear all cached items."""
#         if self.enabled:
#             self.cache.clear()
#             logger.info("Cache cleared")


# # Global cache instance
# semantic_cache = SemanticCache()

"""
Semantic caching layer for Text-to-SQL queries.
Reduces latency by caching query results based on semantic similarity.
"""

from typing import Optional, Tuple, Any
import hashlib
import json
from diskcache import Cache
from loguru import logger
import numpy as np
from ..config import settings
from .embeddings import get_embeddings

class SemanticCache:
    """
    Semantic cache that stores query results indexed by question embeddings.
    Uses cosine similarity to match semantically similar questions.
    """
    
    def __init__(self):
        self.enabled = settings.enable_semantic_cache
        self.threshold = settings.cache_similarity_threshold
        
        if not self.enabled:
            logger.info("Semantic cache disabled")
            return
        
        # Initialize disk cache
        self.cache = Cache("./cache/semantic_cache")
        
        self.embeddings = get_embeddings()

        logger.info(
            f"Semantic cache initialized (OpenAI {settings.embedding_model}, "
            f"threshold: {self.threshold})"
        )
        
    def _compute_embedding(self, text: str) -> np.ndarray | None:
        """Compute embedding vector for text."""
        try:
            embedding = self.embeddings.embed_query(text)
            return np.array(embedding, dtype=np.float64)
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return None

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity in [0, 1] for normalized embedding vectors."""
        a = np.asarray(a, dtype=np.float64).flatten()
        b = np.asarray(b, dtype=np.float64).flatten()
        if a.shape != b.shape or a.size == 0:
            return 0.0
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def get(self, question: str) -> Optional[dict]:
        """
        Retrieve cached result for a question.
        
        Args:
            question: User's question
            
        Returns:
            Cached result dict or None if no match
        """
        if not self.enabled:
            return None
        
        try:
            # Compute embedding for question
            query_embedding = self._compute_embedding(question)
            if query_embedding is None:
                return None
            
            # Get all cached items
            # In production, use a vector database (ChromaDB, Pinecone, etc.)
            # For simplicity, we iterate through cache
            best_match = None
            best_similarity = 0.0
            
            for key in self.cache:
                if key.startswith("embedding_"):
                    cached_data = self.cache[key]
                    cached_embedding = np.array(cached_data["embedding"])
                    
                    similarity = self._cosine_similarity(query_embedding, cached_embedding)
                    
                    if similarity > best_similarity and similarity >= self.threshold:
                        best_similarity = similarity
                        best_match = cached_data
            
            if best_match:
                logger.info(f"✓ Cache HIT (similarity: {best_similarity:.3f})")
                return best_match["result"]
            else:
                logger.info("✗ Cache MISS")
                return None
                
        except Exception as e:
            logger.error(f"Cache retrieval error: {e}")
            return None
        
    def set(self, question: str, result: dict):
        """
        Store query result in cache.
        
        Args:
            question: User's question
            result: Result dict to cache
        """
        if not self.enabled:
            return
        
        try:
            # Compute embedding
            embedding = self._compute_embedding(question)
            if embedding is None:
                return
            
            # Create cache key
            key = f"embedding_{hashlib.md5(question.encode()).hexdigest()}"
            
            # Store with embedding
            cache_data = {
                "question": question,
                "embedding": embedding.tolist(),
                "result": result
            }
            
            self.cache[key] = cache_data
            logger.info(f"✓ Cached result for question")
            
        except Exception as e:
            logger.error(f"Cache storage error: {e}")
    
    def clear(self):
        """Clear all cached items."""
        if self.enabled:
            self.cache.clear()
            logger.info("Cache cleared")


# Global cache instance
semantic_cache = SemanticCache()