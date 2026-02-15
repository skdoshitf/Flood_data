"""
FEMA NFHL API client for querying flood zone data and LOMA features.
"""

import tempfile
from typing import Tuple, Optional
import requests
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
import urllib3
from urllib3.util.ssl_ import create_urllib3_context

# Configure SSL context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import ssl
    ctx = create_urllib3_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    class HTTPAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)
    
    session = requests.Session()
    session.mount('https://', HTTPAdapter())
    session.mount('http://', HTTPAdapter())
except Exception as e:
    print(f"[WARNING] Could not configure SSL context: {e}")
    session = requests.Session()


# Constants
NFHL_WFS = "https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WFSServer"
NFHL_TYPENAME = "S_FLD_HAZ_AR"
NFHL_REST_LAYER28 = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"
NFHL_REST_LAYER5 = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/5"


def _pd_concat(parts: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    """Helper to concatenate GeoDataFrames."""
    return pd.concat(parts, ignore_index=True)


class FEMAClient:
    """Client for interacting with FEMA NFHL APIs."""
    
    def __init__(self, use_wfs: bool = False):
        """
        Initialize FEMA client.
        
        Args:
            use_wfs: If True, use WFS endpoint; otherwise use REST endpoint
        """
        self.use_wfs = use_wfs
        self.wfs_url = NFHL_WFS
        self.rest_layer28_url = NFHL_REST_LAYER28
        self.rest_layer5_url = NFHL_REST_LAYER5
        self.typename = NFHL_TYPENAME
    
    def fetch_flood_zones(self, bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """
        Fetch FEMA NFHL flood zones within bounding box.
        
        Args:
            bbox_4326: Bounding box as (minx, miny, maxx, maxy) in EPSG:4326
            
        Returns:
            GeoDataFrame of flood zone features
        """
        if self.use_wfs:
            return self._fetch_wfs(bbox_4326)
        else:
            return self._fetch_rest(bbox_4326)
    
    def _fetch_wfs(self, bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """Fetch flood zones using WFS endpoint."""
        gdfs = []
        start_index = 0
        page_size = 2000
        
        while True:
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": self.typename,
                "bbox": f"{bbox_4326[0]},{bbox_4326[1]},{bbox_4326[2]},{bbox_4326[3]},EPSG:4326",
                "srsName": "EPSG:4326",
                "count": page_size,
                "startIndex": start_index,
                "outputFormat": "application/json",
            }
            
            resp = session.get(self.wfs_url, params=params, timeout=120, verify=False)
            resp.raise_for_status()
            
            # Try JSON; otherwise GML fallback
            try:
                data = resp.json()
                feats = data.get("features", [])
                if not feats:
                    break
                gdf = gpd.GeoDataFrame.from_features(data, crs="EPSG:4326")
            except ValueError:
                # GML fallback
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".gml")
                tmp.write(resp.content)
                tmp.close()
                gdf = gpd.read_file(tmp.name)
                if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(4326)
            
            gdf = gdf[gdf.geometry.notnull() & (~gdf.geometry.is_empty)]
            gdfs.append(gdf)
            
            if len(gdf) < page_size:
                break
            start_index += page_size
        
        return gpd.GeoDataFrame(_pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    
    def _fetch_rest(self, bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """Fetch flood zones using REST endpoint."""
        gdfs = []
        offset = 0
        page_size = 2000
        
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "f": "geojson",
                "geometry": f"{bbox_4326[0]},{bbox_4326[1]},{bbox_4326[2]},{bbox_4326[3]}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outSR": 4326,
                "returnGeometry": "true",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }
            
            resp = session.get(self.rest_layer28_url + "/query", params=params, timeout=120, verify=False)
            resp.raise_for_status()
            data = resp.json()
            feats = data.get("features", [])
            
            if not feats:
                break
            
            gdf = gpd.GeoDataFrame.from_features(data, crs="EPSG:4326")
            gdf = gdf[gdf.geometry.notnull() & (~gdf.geometry.is_empty)]
            gdfs.append(gdf)
            
            if len(feats) < page_size:
                break
            offset += page_size
        
        return gpd.GeoDataFrame(_pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    
    def fetch_loma(self, bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """
        Fetch FEMA NFHL LOMA (Letters of Map Amendment) features.
        
        Args:
            bbox_4326: Bounding box as (minx, miny, maxx, maxy) in EPSG:4326
            
        Returns:
            GeoDataFrame of LOMA features
        """
        gdfs = []
        offset = 0
        page_size = 1000
        
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "f": "geojson",
                "geometry": f"{bbox_4326[0]},{bbox_4326[1]},{bbox_4326[2]},{bbox_4326[3]}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outSR": 4326,
                "returnGeometry": "true",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }
            
            resp = session.get(self.rest_layer5_url + "/query", params=params, timeout=120, verify=False)
            resp.raise_for_status()
            data = resp.json()
            feats = data.get("features", [])
            
            if not feats:
                break
            
            gdf = gpd.GeoDataFrame.from_features(data, crs="EPSG:4326")
            gdf = gdf[gdf.geometry.notnull() & (~gdf.geometry.is_empty)]
            gdfs.append(gdf)
            
            if len(feats) < page_size:
                break
            offset += page_size
        
        return gpd.GeoDataFrame(_pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    
    @staticmethod
    def overlay_parcel_floodzones(parcel_geom, nfhl_gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, Optional[object]]:
        """
        Perform spatial overlay between parcel and flood zones.
        
        Args:
            parcel_geom: Shapely geometry of parcel
            nfhl_gdf: GeoDataFrame of flood zone features
            
        Returns:
            Tuple of (per_zone_gdf, union_geom) where:
            - per_zone_gdf: each row is parcel∩NFHL feature with attributes
            - union_geom: union of all overlaps (None if no overlap)
        """
        if nfhl_gdf.empty:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), None
        
        # Keep only features that intersect the parcel
        nfhl_gdf = nfhl_gdf.loc[nfhl_gdf.geometry.intersects(parcel_geom)]
        if nfhl_gdf.empty:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), None
        
        # Intersections per feature
        rows = []
        for idx, row in nfhl_gdf.iterrows():
            inter = row.geometry.intersection(parcel_geom)
            if inter.is_empty:
                continue
            r = row.copy()
            r.geometry = inter
            rows.append(r)
        
        if not rows:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), None
        
        per_zone = gpd.GeoDataFrame(rows, crs="EPSG:4326", geometry="geometry")
        
        # Union of the intersected parts
        union_geom = unary_union(list(per_zone.geometry))
        return per_zone, union_geom

