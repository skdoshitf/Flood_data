"""
Data models for orchestrator inputs and outputs.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any

from src.models.agent_models import (
    AddressVerificationResult,
    FloodZoneResult,
)


@dataclass
class OrchestratorRequest:
    """Input to orchestrator - supports both structured and natural language"""
    
    # Natural language query
    natural_language_query: Optional[str] = None
    
    # Structured parameters (alternative to NL)
    address: Optional[str] = None
    parcel_id: Optional[str] = None
    region: Optional[str] = None
    
    # Configuration
    include_loma: bool = True
    include_buildings: bool = True
    use_wfs: bool = False
    
    # ReportAll configuration
    reportall_client_key: Optional[str] = None
    
    # LOMA search radius (in miles)
    loma_radius_miles: float = 0.05


@dataclass
class OrchestratorResult:
    """Final aggregated result from orchestrator"""
    
    # Request info
    request: OrchestratorRequest
    
    # Agent results
    address_verification: AddressVerificationResult
    flood_zone: FloodZoneResult
    
    # Summary
    status: str  # "success", "partial", "failed"
    execution_time_seconds: float
    
    # Files generated
    output_files: Dict[str, str] = field(default_factory=dict)  # filename -> path
    
    # Error information
    error: Optional[str] = None
    error_details: Dict[str, Any] = field(default_factory=dict)

