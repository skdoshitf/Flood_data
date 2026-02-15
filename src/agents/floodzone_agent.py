"""
Agent 2: Flood Zone Determination & LOMA Detection
"""

import math
from typing import Dict, Any, Optional, Tuple
from shapely import wkt as shapely_wkt
from shapely.ops import transform
from pyproj import Transformer

from src.agents.base import BaseAgent
from src.models.agent_models import FloodZoneResult
from src.integrations.fema_client import FEMAClient


def _bbox_from_geom(geom, pad_meters: float = 10.0) -> Tuple[float, float, float, float]:
    """
    Build a slightly expanded bbox around the geometry in EPSG:4326.
    pad_meters is converted to degrees approximately (lat/lon).
    """
    minx, miny, maxx, maxy = geom.bounds
    
    # Crude degree padding (~meters to degrees at mid-latitude)
    # 1 degree lat ~ 111,320 m; 1 degree lon ~ 111,320 * cos(lat)
    lat_mid = (miny + maxy) / 2.0
    dlat = pad_meters / 111_320.0
    dlon = pad_meters / (111_320.0 * max(0.2, math.cos(math.radians(lat_mid))))
    return (minx - dlon, miny - dlat, maxx + dlon, maxy + dlat)


class FloodZoneAgent(BaseAgent):
    """Agent 2: Flood zone determination and LOMA detection using FEMA APIs."""
    
    def __init__(self, use_wfs: bool = False):
        """
        Initialize Flood Zone Agent.
        
        Args:
            use_wfs: If True, use WFS endpoint; otherwise use REST endpoint
        """
        super().__init__("FloodZoneAgent")
        self.fema_client = FEMAClient(use_wfs=use_wfs)
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate input data."""
        return bool(input_data.get("parcel_wkt"))
    
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute flood zone determination and LOMA detection.
        
        Input:
            {
                "parcel_wkt": str,  # Required: WKT geometry of parcel
                "parcel_centroid": Tuple[float, float],  # Optional: (lon, lat)
                "buildings": List[Dict],  # Optional: Building footprints
                "include_loma": bool,  # Optional: Whether to include LOMA search
                "loma_radius_miles": float,  # Optional: LOMA search radius
                "reportall_client_key": str,  # Optional: For nearby parcel query
            }
        
        Returns:
            FloodZoneResult as dict
        """
        if not self.validate_input(input_data):
            raise ValueError("Invalid input: parcel_wkt is required")
        
        try:
            parcel_wkt = input_data["parcel_wkt"]
            parcel_geom = shapely_wkt.loads(parcel_wkt)
            
            # Step 1: Build AOI bbox from parcel geometry
            bbox = _bbox_from_geom(parcel_geom, pad_meters=2.0)
            self.log(f"Query bbox: {bbox}")
            
            # Step 2: Fetch flood zones
            self.log("Fetching FEMA NFHL flood zones...")
            nfhl_gdf = self.fema_client.fetch_flood_zones(bbox)
            self.log(f"Found {len(nfhl_gdf)} flood zone features")
            
            # Step 3: Perform spatial overlay
            per_zone, union_geom = FEMAClient.overlay_parcel_floodzones(parcel_geom, nfhl_gdf)
            
            # Step 4: Extract flood zone information
            flood_zones = []
            primary_zone = None
            zone_subtype = None
            in_flood_zone = False
            
            if not per_zone.empty:
                in_flood_zone = True
                # Convert to list of dicts
                for idx, row in per_zone.iterrows():
                    zone_info = {
                        "overlap_wkt": row.geometry.wkt,
                        "src": "parcel"
                    }
                    # Add NFHL attributes if present
                    for col in ["FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE"]:
                        if col in row:
                            zone_info[col] = row[col]
                    if not primary_zone and "FLD_ZONE" in row:
                        primary_zone = row["FLD_ZONE"]
                    if not zone_subtype and "ZONE_SUBTY" in row:
                        zone_subtype = row["ZONE_SUBTY"]
                    flood_zones.append(zone_info)
            
            # Step 5: Analyze building footprints if available
            building_overlaps = []
            buildings = input_data.get("buildings", [])
            if buildings and not nfhl_gdf.empty:
                transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
                
                for building in buildings:
                    bwkt = building.get("geom_wkt")
                    if not bwkt:
                        continue
                    
                    try:
                        bgeom = shapely_wkt.loads(bwkt)
                        per_bld, _ = FEMAClient.overlay_parcel_floodzones(bgeom, nfhl_gdf)
                        
                        if not per_bld.empty:
                            # Compute building area and overlap area
                            try:
                                b_area = transform(transformer.transform, bgeom).area
                            except Exception:
                                b_area = None
                            
                            try:
                                overlap_area = 0.0
                                for geom in per_bld.geometry:
                                    if geom is None or geom.is_empty:
                                        continue
                                    overlap_area += transform(transformer.transform, geom).area
                            except Exception:
                                overlap_area = None
                            
                            for idx, row in per_bld.iterrows():
                                bldg_overlap = {
                                    "building_index": building.get("building_index"),
                                    "overlap_wkt": row.geometry.wkt,
                                    "bldg_area_m2": b_area,
                                    "bldg_overlap_area_m2": overlap_area,
                                    "bldg_geom_wkt": bwkt
                                }
                                # Add NFHL attributes
                                for col in ["FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE"]:
                                    if col in row:
                                        bldg_overlap[col] = row[col]
                                building_overlaps.append(bldg_overlap)
                    except Exception as e:
                        self.log(f"Error processing building: {e}")
                        continue
            
            # Step 6: LOMA detection (if requested)
            loma_features = []
            nearest_loma_distance_m = None
            include_loma = input_data.get("include_loma", True)
            
            if include_loma:
                self.log("Fetching LOMA features...")
                # Build bbox from nearby parcels if available
                parcel_centroid = input_data.get("parcel_centroid")
                reportall_key = input_data.get("reportall_client_key")
                
                if parcel_centroid and reportall_key:
                    # Query nearby parcels to expand search area
                    from src.integrations.reportall_client import ReportAllClient
                    reportall_client = ReportAllClient(reportall_key)
                    loma_radius = input_data.get("loma_radius_miles", 0.05)
                    
                    nearby_parcels = reportall_client.query_nearby_parcels(
                        parcel_centroid[0],
                        parcel_centroid[1],
                        radius_miles=loma_radius
                    )
                    
                    if nearby_parcels:
                        # Build union of nearby parcel geometries
                        from shapely.ops import unary_union
                        all_geoms = []
                        for p in nearby_parcels:
                            wkt_str = p.get("geom_as_wkt")
                            if wkt_str:
                                try:
                                    geom = shapely_wkt.loads(wkt_str)
                                    all_geoms.append(geom)
                                except Exception:
                                    pass
                        
                        if all_geoms:
                            union_geoms = unary_union(all_geoms)
                            loma_bbox = _bbox_from_geom(union_geoms, pad_meters=50.0)
                        else:
                            loma_bbox = _bbox_from_geom(parcel_geom, pad_meters=50.0)
                    else:
                        loma_bbox = _bbox_from_geom(parcel_geom, pad_meters=50.0)
                else:
                    loma_bbox = _bbox_from_geom(parcel_geom, pad_meters=50.0)
                
                lomas = self.fema_client.fetch_loma(loma_bbox)
                self.log(f"Found {len(lomas)} LOMA features")
                
                if not lomas.empty and parcel_centroid:
                    # Rank LOMAs by distance to parcel centroid
                    from shapely.geometry import Point
                    address_point = Point(parcel_centroid[0], parcel_centroid[1])
                    lomas = lomas.copy()
                    lomas["distance_m"] = lomas.geometry.apply(
                        lambda g: address_point.distance(g) * 111_320.0 if g else None
                    )
                    lomas = lomas.sort_values("distance_m")
                    
                    # Convert to list of dicts
                    for idx, row in lomas.iterrows():
                        loma_info = {
                            "distance_m": row.get("distance_m"),
                        }
                        # Add all other columns
                        for col in lomas.columns:
                            if col not in ["geometry", "distance_m"]:
                                loma_info[col] = row[col]
                        loma_features.append(loma_info)
                    
                    if loma_features:
                        nearest_loma_distance_m = loma_features[0].get("distance_m")
            
            # Step 7: Build result
            result = FloodZoneResult(
                flood_zones=flood_zones,
                union_overlap_wkt=union_geom.wkt if union_geom and not union_geom.is_empty else None,
                loma_features=loma_features,
                nearest_loma_distance_m=nearest_loma_distance_m,
                building_overlaps=building_overlaps,
                in_flood_zone=in_flood_zone,
                primary_zone=primary_zone,
                zone_subtype=zone_subtype,
                query_bbox=bbox,
                nfhl_features_count=len(nfhl_gdf),
                logs=self.logs
            )
            
            self.log("Flood zone determination completed successfully")
            return self._result_to_dict(result)
            
        except Exception as e:
            self.log(f"Error during flood zone determination: {e}")
            # Return partial result with error
            error_result = FloodZoneResult(
                flood_zones=[],
                in_flood_zone=False,
                query_bbox=None,
                nfhl_features_count=0,
                logs=self.logs + [f"ERROR: {str(e)}"],
                error=str(e)
            )
            return self._result_to_dict(error_result)
    
    def _result_to_dict(self, result: FloodZoneResult) -> Dict[str, Any]:
        """Convert FloodZoneResult to dictionary."""
        from dataclasses import asdict
        return asdict(result)

