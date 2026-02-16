"""
Configuration management for the application.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class Config:
    """Application configuration."""
    
    # API Keys
    reportall_client_key: str = "Wtn9iKgWVx"
    
    # FEMA Settings
    use_wfs: bool = False
    fema_timeout: int = 120
    
    # Cache Settings
    cache_enabled: bool = True
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600  # 1 hour default
    
    # LOMA Settings
    loma_radius_miles: float = 0.05
    include_loma: bool = True
    
    # Building Settings
    include_buildings: bool = True
    
    # Output Settings
    output_dir: str = "."
    
    # Logging Settings
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # Retry Settings
    max_retries: int = 3
    retry_delay: float = 2.0
    
    @classmethod
    def from_file(cls, config_path: str) -> "Config":
        """
        Load configuration from JSON file.
        
        Args:
            config_path: Path to JSON config file
            
        Returns:
            Config instance
        """
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        return cls(**data)
    
    @classmethod
    def from_env(cls) -> "Config":
        """
        Load configuration from environment variables.
        
        Returns:
            Config instance
        """
        return cls(
            reportall_client_key=os.getenv("REPORTALL_CLIENT_KEY", "Wtn9iKgWVx"),
            use_wfs=os.getenv("USE_WFS", "false").lower() == "true",
            cache_enabled=os.getenv("CACHE_ENABLED", "true").lower() == "true",
            cache_dir=os.getenv("CACHE_DIR"),
            cache_ttl=int(os.getenv("CACHE_TTL", "3600")),
            loma_radius_miles=float(os.getenv("LOMA_RADIUS_MILES", "0.05")),
            include_loma=os.getenv("INCLUDE_LOMA", "true").lower() == "true",
            include_buildings=os.getenv("INCLUDE_BUILDINGS", "true").lower() == "true",
            output_dir=os.getenv("OUTPUT_DIR", "."),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("RETRY_DELAY", "2.0"))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "reportall_client_key": self.reportall_client_key,
            "use_wfs": self.use_wfs,
            "fema_timeout": self.fema_timeout,
            "cache_enabled": self.cache_enabled,
            "cache_dir": self.cache_dir,
            "cache_ttl": self.cache_ttl,
            "loma_radius_miles": self.loma_radius_miles,
            "include_loma": self.include_loma,
            "include_buildings": self.include_buildings,
            "output_dir": self.output_dir,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay
        }
    
    def save(self, config_path: str) -> None:
        """
        Save configuration to JSON file.
        
        Args:
            config_path: Path to save config file
        """
        config_file = Path(config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


# Global config instance
_config: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get global configuration instance.
    
    Args:
        config_path: Optional path to config file
        
    Returns:
        Config instance
    """
    global _config
    
    if _config is not None:
        return _config
    
    if config_path:
        _config = Config.from_file(config_path)
    elif os.getenv("CONFIG_FILE"):
        _config = Config.from_file(os.getenv("CONFIG_FILE"))
    else:
        _config = Config.from_env()
    
    return _config


def set_config(config: Config) -> None:
    """Set global configuration."""
    global _config
    _config = config

