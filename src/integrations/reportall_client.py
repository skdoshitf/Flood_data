"""
ReportAll API client for querying parcel data.
"""

import math
from typing import Dict, Optional, List, Tuple
import requests
import urllib3
from urllib3.util.ssl_ import create_urllib3_context
from shapely import wkt as shapely_wkt

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
REPORTALL_BASE = "https://reportallusa.com/api/parcels"
REPORTALL_API_VERSION = "9"


class ReportAllClient:
    """Client for interacting with ReportAll API."""
    
    def __init__(self, client_key: str):
        """
        Initialize ReportAll client.
        
        Args:
            client_key: ReportAll client key or token
        """
        self.client_key = client_key
        self.base_url = REPORTALL_BASE
        self.api_version = REPORTALL_API_VERSION
    
    def query_by_address(self,
                        q: Optional[str] = None,
                        address: Optional[str] = None,
                        region: Optional[str] = None) -> Dict:
        """
        Query ReportAll by address.
        
        Args:
            q: Full address string (e.g., "1137 Barnett street, johnstown, pa")
            address: Street address (e.g., "1000 4th Ave")
            region: Region/County (e.g., "King County, Washington")
            
        Returns:
            JSON response from ReportAll API
            
        Raises:
            ValueError: If required parameters are missing
            requests.HTTPError: If API request fails
        """
        params = {
            "v": self.api_version,
            "client": self.client_key,
            "return_buildings": "true"
        }
        
        if q:
            params["q"] = q
        elif address and region:
            params["address"] = address
            params["region"] = region
        else:
            raise ValueError("Must provide either 'q' or both 'address' and 'region'")
        
        response = session.get(self.base_url, params=params, timeout=60, verify=False)
        response.raise_for_status()
        return response.json()
    
    def query_by_parcel_id(self, parcel_id: str, region: str) -> Dict:
        """
        Query ReportAll by parcel ID.
        
        Args:
            parcel_id: Assessor Parcel ID (APN/PIN)
            region: Region/County (e.g., "King County, Washington")
            
        Returns:
            JSON response from ReportAll API
            
        Raises:
            requests.HTTPError: If API request fails
        """
        params = {
            "v": self.api_version,
            "parcel_id": parcel_id,
            "region": region,
            "client": self.client_key,
            "return_buildings": "true"
        }
        
        response = session.get(self.base_url, params=params, timeout=60, verify=False)
        response.raise_for_status()
        return response.json()
    
    def query_nearby_parcels(self,
                            lon: float,
                            lat: float,
                            radius_miles: float = 0.05) -> List[Dict]:
        """
        Query ReportAll for nearby parcels within a radius.
        
        Args:
            lon: Longitude (WGS84)
            lat: Latitude (WGS84)
            radius_miles: Search radius in miles
            
        Returns:
            List of nearby parcel records
        """
        point_wkt = f"POINT({lon} {lat})"
        params = {
            "v": self.api_version,
            "spatial_nearest": point_wkt,
            "sn_srid": "4326",
            "rpp": 100,
            "client": self.client_key,
            "return_buildings": "true"
        }
        
        response = session.get(self.base_url, params=params, timeout=60, verify=False)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        
        # Filter to parcels within radius
        radius_deg = radius_miles / 69.0
        nearby = []
        for rec in results:
            try:
                wkt_str = rec.get("geom_as_wkt")
                if wkt_str:
                    geom = shapely_wkt.loads(wkt_str)
                    cx, cy = geom.centroid.x, geom.centroid.y
                    dist_deg = math.sqrt((cx - lon)**2 + (cy - lat)**2)
                    if dist_deg <= radius_deg:
                        nearby.append(rec)
            except Exception:
                pass
        
        return nearby
    
    @staticmethod
    def parse_first_parcel(response: Dict) -> Tuple[str, Dict]:
        """
        Extract the first parcel's WKT and record from ReportAll response.
        
        Args:
            response: JSON response from ReportAll API
            
        Returns:
            Tuple of (wkt_string, record_dict)
            
        Raises:
            RuntimeError: If response is invalid or no results found
        """
        if response.get("status") != "OK":
            raise RuntimeError(
                f"ReportAll API returned status={response.get('status')}: {response}"
            )
        
        results = response.get("results", [])
        if not results:
            raise RuntimeError("No results returned from ReportAll.")
        
        rec = results[0]
        wkt_str = rec.get("geom_as_wkt")
        if not wkt_str:
            raise RuntimeError("`geom_as_wkt` not present in the first result.")
        
        return wkt_str, rec

