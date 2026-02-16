"""
Caching layer for API calls to reduce redundant requests.
"""

import hashlib
import json
import time
from typing import Any, Optional, Dict
from pathlib import Path
import pickle


class CacheManager:
    """
    Simple file-based cache manager for API responses.
    Supports TTL (time-to-live) for cache entries.
    """
    
    def __init__(self, cache_dir: Optional[str] = None, default_ttl: int = 3600):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory for cache files (default: .cache in project root)
            default_ttl: Default time-to-live in seconds (default: 1 hour)
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path(".") / ".cache"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }
    
    def _get_cache_key(self, key: str) -> str:
        """
        Generate cache key from input string.
        
        Args:
            key: Input string
            
        Returns:
            MD5 hash of the key
        """
        return hashlib.md5(key.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """Get full path to cache file."""
        return self.cache_dir / f"{cache_key}.pkl"
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value if found and not expired, None otherwise
        """
        cache_key = self._get_cache_key(key)
        cache_path = self._get_cache_path(cache_key)
        
        if not cache_path.exists():
            self.stats["misses"] += 1
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                entry = pickle.load(f)
            
            # Check if expired
            if time.time() > entry["expires_at"]:
                cache_path.unlink()  # Delete expired entry
                self.stats["evictions"] += 1
                self.stats["misses"] += 1
                return None
            
            self.stats["hits"] += 1
            return entry["value"]
        
        except Exception:
            # If cache file is corrupted, delete it
            if cache_path.exists():
                cache_path.unlink()
            self.stats["misses"] += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        cache_key = self._get_cache_key(key)
        cache_path = self._get_cache_path(cache_key)
        
        ttl = ttl or self.default_ttl
        entry = {
            "value": value,
            "expires_at": time.time() + ttl,
            "created_at": time.time()
        }
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(entry, f)
        except Exception as e:
            # Log error but don't fail
            print(f"[Cache] Warning: Failed to cache {key}: {e}")
    
    def clear(self, pattern: Optional[str] = None) -> int:
        """
        Clear cache entries.
        
        Args:
            pattern: Optional pattern to match keys (not implemented yet)
            
        Returns:
            Number of entries cleared
        """
        count = 0
        if pattern:
            # Pattern matching not implemented yet
            return count
        
        # Clear all
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                cache_file.unlink()
                count += 1
            except Exception:
                pass
        
        return count
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return self.stats.copy()
    
    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }


class CachedAPIClient:
    """
    Mixin class to add caching to API clients.
    """
    
    def __init__(self, cache_manager: Optional[CacheManager] = None, cache_enabled: bool = True):
        """
        Initialize with optional cache manager.
        
        Args:
            cache_manager: CacheManager instance (creates new one if None)
            cache_enabled: Whether caching is enabled
        """
        self.cache_enabled = cache_enabled
        if cache_manager:
            self.cache = cache_manager
        elif cache_enabled:
            self.cache = CacheManager()
        else:
            self.cache = None
    
    def _make_cache_key(self, method: str, **kwargs) -> str:
        """
        Generate cache key from method and parameters.
        
        Args:
            method: Method name
            **kwargs: Method parameters
            
        Returns:
            Cache key string
        """
        # Sort kwargs for consistent key generation
        sorted_kwargs = json.dumps(kwargs, sort_keys=True, default=str)
        return f"{self.__class__.__name__}.{method}:{sorted_kwargs}"
    
    def _cached_call(self, method: str, func, ttl: Optional[int] = None, **kwargs) -> Any:
        """
        Execute function with caching.
        
        Args:
            method: Method name for cache key
            func: Function to execute
            ttl: Time-to-live for cache entry
            **kwargs: Function arguments
            
        Returns:
            Function result (from cache or execution)
        """
        if not self.cache_enabled or not self.cache:
            return func(**kwargs)
        
        cache_key = self._make_cache_key(method, **kwargs)
        cached_value = self.cache.get(cache_key)
        
        if cached_value is not None:
            return cached_value
        
        # Execute function
        result = func(**kwargs)
        
        # Cache result
        self.cache.set(cache_key, result, ttl=ttl)
        
        return result

