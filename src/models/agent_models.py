"""
Data models for agent inputs and outputs.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

from src.models import Address, Evidence  # Import from src/models.py (not package)


@dataclass
class AddressVerificationResult:
    """Output from Agent 1: Address Verification & Polygon Extraction"""
    
    # Address details
    address: Address
    address_type: str  # "Standard", "Incomplete", "Non-standard"
    confidence: float  # 0.0-1.0
    routing: str  # "Auto", "HITL", "Enrich / Request More Info", etc.
    
    # Geometry
    parcel_wkt: str  # WKT geometry of parcel
    parcel_centroid: Tuple[float, float]  # (lon, lat)
    parcel_record: Dict[str, Any]  # Full ReportAll record
    
    # Metadata
    verification_status: str  # "verified", "incomplete", "failed"
    
    # Buildings (if available)
    buildings: List[Dict[str, Any]] = field(default_factory=list)  # Building footprints with geometry
    evidence: Evidence = field(default_factory=Evidence)
    logs: List[str] = field(default_factory=list)
    
    # Optional classification details
    classification_variant: Optional[str] = None  # For incomplete addresses
    classification_rationale: List[str] = field(default_factory=list)


@dataclass
class FloodZoneResult:
    """Output from Agent 2: Flood Zone Determination & LOMA Detection"""
    
    # Flood zone classification
    flood_zones: List[Dict[str, Any]] = field(default_factory=list)  # Per-zone overlaps with attributes
    union_overlap_wkt: Optional[str] = None  # Union of all overlaps
    
    # LOMA information
    loma_features: List[Dict[str, Any]] = field(default_factory=list)  # Ranked by distance
    nearest_loma_distance_m: Optional[float] = None
    
    # Building analysis
    building_overlaps: List[Dict[str, Any]] = field(default_factory=list)  # Per-building flood zone overlaps
    
    # Summary
    in_flood_zone: bool = False
    primary_zone: Optional[str] = None  # e.g., "AE", "X", "VE"
    zone_subtype: Optional[str] = None
    
    # Metadata
    query_bbox: Optional[Tuple[float, float, float, float]] = None  # (minx, miny, maxx, maxy)
    nfhl_features_count: int = 0
    logs: List[str] = field(default_factory=list)
    
    # Error information
    error: Optional[str] = None

