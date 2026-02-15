
#!/usr/bin/env python3
"""
Flow:
  1) Use ReportAll API to query by Address or Parcel ID (get parcel geometry).
  2) Extract WKT from 'geom_as_wkt' (SRID 4326 per ReportAll docs).
  3) Build AOI from that polygon and query FEMA NFHL flood zones in the AOI.
  4) Spatial overlay (intersection) → output overlapped area in WKT.

Docs:
- ReportAll Standard API "parcels" (v=9), response includes `geom_as_wkt` (WGS84 lon/lat, SRID 4326).  [CITE: turn5search1]
- FEMA NFHL WFS endpoint (typeNames=S_FLD_HAZ_AR) and schema.  [CITE: turn2search13, turn2search21]
- FEMA NFHL REST fallback: MapServer layer 28 query (GeoJSON).  [CITE: turn2search29, turn2search28]
"""

import os
import sys
import math
import json
import time
import tempfile
from typing import Dict, Optional, Tuple, List

import requests
import pandas as pd
import geopandas as gpd
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, box
from shapely.ops import unary_union, transform
from pyproj import Transformer
from tqdm import tqdm

# Configure urllib3 to ignore unexpected EOF errors from OpenSSL
import urllib3
from urllib3.util.ssl_ import create_urllib3_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create a custom SSL context that ignores unexpected EOF errors
try:
    import ssl
    ctx = create_urllib3_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    # Patch requests to use this context
    class HTTPAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)
    
    # Apply the custom adapter to all requests
    session = requests.Session()
    session.mount('https://', HTTPAdapter())
    session.mount('http://', HTTPAdapter())
except Exception as e:
    print(f"[WARNING] Could not configure SSL context: {e}")


# ========= USER CONFIG =========

# Provide your ReportAll client key OR token (use the param name you pass below).
REPORTALL_CLIENT_OR_TOKEN = "Wtn9iKgWVx"

# Choose one input mode:
INPUT_MODE = "address"   # "address" or "parcel_id"

# (A) Address mode: either use q="full address string", or address + region
ADDRESS_Q = "1137 Barnett street, johnstown, pa"      # <-- Example full address (City Hall area)
ADDRESS = None                                     # or e.g. "1000 4th Ave"
REGION  = None                                     # or e.g. "King County, Washington"

# (B) Parcel-id mode: requires region + assessor parcel id (APN / PIN / Parcel ID)
PARCEL_ID = None                                   # e.g., "766620-1420"
PARCEL_REGION = None          # used when INPUT_MODE == "parcel_id"

# FEMA NFHL options
USE_WFS = False   # True → WFS (preferred); False → REST/GeoJSON fallback

# Output
OUT_OVERLAP_CSV = "overlap_by_zone.csv"   # per-zone intersections (if any)
OUT_OVERLAP_WKT = "overlap_union.wkt"     # a single unioned WKT for all overlaps
OUT_PARCEL_WKT = "parcel_geom.wkt"     # WKT of the parcel polygon
OUT_LOMA_CSV = "loma_results.csv"   # LOMA features nearby, ranked by distance

# ========= CONSTANTS & ENDPOINTS =========

REPORTALL_BASE = "https://reportallusa.com/api/parcels"
REPORTALL_API_VERSION = "9"  # current version as per docs  [CITE: turn5search1]

# FEMA WFS (Flood Hazard Areas layer: S_FLD_HAZ_AR)https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WFSServer
NFHL_WFS = "https://hazards.fema.gov/arcgis/services/public/NFHL/MapServer/WFSServer"  # [CITE: turn2search13]
NFHL_TYPENAME = "S_FLD_HAZ_AR"  # [CITE: turn2search21]

# FEMA REST fallback (layer 28: Flood Hazard Zones)https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
NFHL_REST_LAYER28 = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"  # [CITE: turn2search29, turn2search28]

# FEMA LOMA (Letters of Map Amendment) layer 5
NFHL_REST_LAYER5 = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/5"


# ========= HELPERS =========

def _required(val, name):
    if not val:
        raise ValueError(f"Required value missing: {name}")
    return val

def _bbox_from_geom(geom, pad_meters: float = 10.0) -> Tuple[float, float, float, float]:
    """
    Build a slightly expanded bbox around the geometry in EPSG:4326.
    pad_meters is converted to degrees approximately (lat/lon).
    """
    minx, miny, maxx, maxy = geom.bounds

    #print(minx, miny, maxx, maxy)
    # crude degree padding (~meters to degrees at mid-latitude)
    # 1 degree lat ~ 111,320 m; 1 degree lon ~ 111,320 * cos(lat)
    lat_mid = (miny + maxy) / 2.0
    dlat = pad_meters / 111_320.0
    dlon = pad_meters / (111_320.0 * max(0.2, math.cos(math.radians(lat_mid))))
    return (minx - dlon, miny - dlat, maxx + dlon, maxy + dlat)

def _parse_first_geom_as_wkt(reportall_json: Dict) -> Tuple[str, Dict]:
    """
    Extract the first parcel's WKT from ReportAll results.
    Returns (wkt_str, record_dict).
    """
    if reportall_json.get("status") != "OK":
        raise RuntimeError(f"ReportAll API returned status={reportall_json.get('status')}: {reportall_json}")
    results = reportall_json.get("results", [])
    if not results:
        raise RuntimeError("No results returned from ReportAll.")
    rec = results[0]
    wkt_str = rec.get("geom_as_wkt")
    if not wkt_str:
        raise RuntimeError("`geom_as_wkt` not present in the first result (unexpected).")
    return wkt_str, rec


# ========= STEP 1 — ReportAll query =========

def query_reportall_by_address(client_or_token: str,
                               q: Optional[str] = None,
                               address: Optional[str] = None,
                               region: Optional[str] = None) -> Dict:
    """
    Use the ReportAll Standard API (v=9) to search parcels by address.
    - Either pass q="full address" OR address + region.
    Response includes 'geom_as_wkt' per record.  [CITE: turn5search1]
    """
    params = {
        "v": REPORTALL_API_VERSION,
        "return_buildings": "true"
    }
    # per docs you can pass either client=... OR token=...
    # we use "client" by default for simplicity; change to "token" if you prefer a token
    params["client"] = client_or_token

    if q:
        params["q"] = q
    else:
        _required(address, "address")
        _required(region,  "region")
        params["address"] = address
        params["region"]  = region

    r = session.get(REPORTALL_BASE, params=params, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()

def query_reportall_by_parcel_id(client_or_token: str,
                                 parcel_id: str,
                                 region: str) -> Dict:
    """
    Use the ReportAll Standard API (v=9) to search parcels by assessor Parcel ID.
    Requires region and parcel_id; returns 'geom_as_wkt' in results.  [CITE: turn5search1]
    """
    params = {
        "v": REPORTALL_API_VERSION,
        "parcel_id": _required(parcel_id, "parcel_id"),
        "region":    _required(region, "region"),
        "client":    client_or_token,
        "return_buildings": "true"
    }
    r = session.get(REPORTALL_BASE, params=params, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()


def query_reportall_nearby_parcels(client_or_token: str, lon: float, lat: float, radius_miles: float = 0.05) -> Dict:
    """
    Query ReportAll for nearby parcels within a radius of a point using spatial_nearest.
    Returns list of nearby parcel records.
    """
    # spatial_nearest in WGS84 (SRID 4326)
    point_wkt = f"POINT({lon} {lat})"
    params = {
        "v": REPORTALL_API_VERSION,
        "spatial_nearest": point_wkt,
        "sn_srid": "4326",
        "rpp": 100,  # get many nearby parcels
        "client": client_or_token,
        "return_buildings": "true"
    }
    r = session.get(REPORTALL_BASE, params=params, timeout=60, verify=False)
    r.raise_for_status()
    data = r.json()
    # Filter to only parcels within the radius (rough distance check)
    results = data.get("results", [])
    
    # Convert radius miles to degrees (approximate: 1 degree ~ 69 miles)
    radius_deg = radius_miles / 69.0
    nearby = []
    for rec in results:
        # Simple distance check on centroid if available
        # otherwise parse geometry and get centroid
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


# ========= STEP 3 — FEMA NFHL fetch (AOI-based) =========

def fetch_nfhl_wfs(bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """
    FEMA WFS 2.0.0 (typeNames=S_FLD_HAZ_AR) within AOI bbox, GeoJSON if supported.
    [CITE: turn2search13, turn2search21]
    """
    gdfs = []
    start_index = 0
    page_size = 2000
    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": NFHL_TYPENAME,
            "bbox": f"{bbox_4326[0]},{bbox_4326[1]},{bbox_4326[2]},{bbox_4326[3]},EPSG:4326",
            "srsName": "EPSG:4326",
            "count": page_size,
            "startIndex": start_index,
            "outputFormat": "application/json",
        }
        resp = session.get(NFHL_WFS, params=params, timeout=120, verify=False)
        resp.raise_for_status()

        # Try JSON; otherwise GML fallback via temp file
        try:
            data = resp.json()
            feats = data.get("features", [])
            if not feats:
                break
            gdf = gpd.GeoDataFrame.from_features(data, crs="EPSG:4326")
        except ValueError:
            # GML fallback
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".gml")
            tmp.write(resp.content); tmp.close()
            gdf = gpd.read_file(tmp.name)
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)

        gdf = gdf[gdf.geometry.notnull() & (~gdf.geometry.is_empty)]
        gdfs.append(gdf)
        if len(gdf) < page_size:
            break
        start_index += page_size

    return gpd.GeoDataFrame(pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def fetch_nfhl_rest(bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """
    FEMA NFHL REST fallback: MapServer/28 (Flood Hazard Zones) → GeoJSON with AOI bbox.
    [CITE: turn2search29, turn2search28]
    """
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
        resp = session.get(NFHL_REST_LAYER28 + "/query", params=params, timeout=120, verify=False)
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

    return gpd.GeoDataFrame(pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def fetch_nfhl_loma(bbox_4326: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """
    Fetch FEMA NFHL LOMA (Letters of Map Amendment) features from layer 5.
    Returns GeoDataFrame of LOMA features within bbox.
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
        resp = session.get(NFHL_REST_LAYER5 + "/query", params=params, timeout=120, verify=False)
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

    return gpd.GeoDataFrame(pd_concat(gdfs), crs="EPSG:4326") if gdfs else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

def overlay_parcel_nfhl(parcel_geom, nfhl_gdf: gpd.GeoDataFrame):
    """
    Returns (per_zone_gdf, union_geom) where:
      per_zone_gdf: each row is parcel∩NFHL feature with attributes preserved.
      union_geom: union of all overlaps (can be None if no overlap).
    """
    # Filter candidates quickly by bbox
    if nfhl_gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), None

    # Keep only features that really intersect the parcel
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

    # Union of the intersected parts (for a single WKT)
    union_geom = unary_union(list(per_zone.geometry))
    return per_zone, union_geom


def pd_concat(parts: List[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    import pandas as pd
    return pd.concat(parts, ignore_index=True)


# ========= MAIN =========

def main():
    # -------- Step 1: Query ReportAll by address or parcel id --------
    if INPUT_MODE == "address":
        if ADDRESS_Q:
            resp = query_reportall_by_address(REPORTALL_CLIENT_OR_TOKEN, q=ADDRESS_Q)
        else:
            resp = query_reportall_by_address(REPORTALL_CLIENT_OR_TOKEN,
                                              address=_required(ADDRESS, "ADDRESS"),
                                              region=_required(REGION, "REGION"))
    elif INPUT_MODE == "parcel_id":
        resp = query_reportall_by_parcel_id(REPORTALL_CLIENT_OR_TOKEN,
                                            parcel_id=_required(PARCEL_ID, "PARCEL_ID"),
                                            region=_required(PARCEL_REGION, "PARCEL_REGION"))
    else:
        raise ValueError("INPUT_MODE must be 'address' or 'parcel_id'.")

    # -------- Step 2: Extract WKT polygon --------
    parcel_wkt, rec = _parse_first_geom_as_wkt(resp)  # includes geom_as_wkt in SRID 4326  [CITE: turn5search1]
    parcel_geom = shapely_wkt.loads(parcel_wkt)

    if parcel_geom and (not parcel_geom.is_empty):
        with open(OUT_PARCEL_WKT, "w") as f:
            f.write(parcel_geom.wkt)
        print(f"[OK] Wrote parcel WKT: {OUT_PARCEL_WKT}")
    else:
        print("[INFO] No parcel geometry to write.")

    # -------- Step 3: Determine AOI and fetch NFHL flood zones --------
    bbox = _bbox_from_geom(parcel_geom, pad_meters=2.0)  # tiny pad to ensure capture
    if USE_WFS:
        nfhl = fetch_nfhl_wfs(bbox)   # WFS 2.0.0 (S_FLD_HAZ_AR)  [CITE: turn2search13, turn2search21]
        if nfhl.empty:
            # fallback if WFS blocked by network/driver
            nfhl = fetch_nfhl_rest(bbox)  # [CITE: turn2search29, turn2search28]
    else:
        nfhl = fetch_nfhl_rest(bbox)      # [CITE: turn2search29, turn2search28]

    # -------- Step 4: Spatial overlay (intersection) → WKT outputs --------
    per_zone, union_geom = overlay_parcel_nfhl(parcel_geom, nfhl)

    # Output (A): per‑zone overlaps → CSV with WKT
    frames = []
    # transformer to compute areas in square meters (project to EPSG:3857)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    # Parcel-level overlaps
    if not per_zone.empty:
        p = per_zone.copy()
        p["overlap_wkt"] = p.geometry.to_wkt()
        p["src"] = "parcel"
        p["building_index"] = None
        frames.append(p)

    # Building footprints (if present in the ReportAll response)
    buildings = rec.get("buildings_poly") or []
    for bi, b in enumerate(buildings):
        # building entry may be a dict with 'geom_as_wkt' or a raw WKT string
        if isinstance(b, dict):
            bwkt = b.get("geom_as_wkt") or b.get("wkt") or None
        else:
            bwkt = b
        if not bwkt:
            continue
        try:
            bgeom = shapely_wkt.loads(bwkt)
        except Exception:
            continue

        per_bld, _ = overlay_parcel_nfhl(bgeom, nfhl)
        if per_bld.empty:
            continue
        pb = per_bld.copy()
        pb["overlap_wkt"] = pb.geometry.to_wkt()
        pb["src"] = "building"
        pb["building_index"] = bi
        # compute building footprint area (m^2) and overlap area (m^2)
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

        pb["bldg_area_m2"] = b_area
        pb["bldg_overlap_area_m2"] = overlap_area
        # Include building attributes (prefix keys with 'bldg_') if provided
        if isinstance(b, dict):
            for bk, bv in b.items():
                if bk in ("geom_as_wkt", "wkt"):
                    continue
                try:
                    pb[f"bldg_{bk}"] = bv
                except Exception:
                    pb[f"bldg_{bk}"] = str(bv)
            # also record original building WKT
            pb["bldg_geom_wkt"] = bwkt
        frames.append(pb)

    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        # keep some common NFHL fields if present, plus any building attributes
        nfhl_keep = [c for c in ["FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE"] if c in all_df.columns]
        bldg_cols = [c for c in all_df.columns if c.startswith("bldg_")]
        cols = nfhl_keep + bldg_cols + ["src", "building_index", "overlap_wkt"]
        all_df[cols].to_csv(OUT_OVERLAP_CSV, index=False)
        print(f"[OK] Wrote per-zone overlaps: {OUT_OVERLAP_CSV}  (rows={len(all_df)})")
    else:
        print("[INFO] No FEMA NFHL overlaps found for this parcel or its buildings.")

    # Output (B): single union geometry → WKT
    if union_geom and (not union_geom.is_empty):
        with open(OUT_OVERLAP_WKT, "w") as f:
            f.write(union_geom.wkt)
        print(f"[OK] Wrote union overlap WKT: {OUT_OVERLAP_WKT}")
    else:
        print("[INFO] No union overlap geometry to write.")

    # -------- Step 5: LOMA detection --------
    # Get address coordinates (parcel centroid)
    addr_lon, addr_lat = parcel_geom.centroid.x, parcel_geom.centroid.y
    print(f"\n[LOMA] Address coordinates: ({addr_lat:.6f}, {addr_lon:.6f})")

    # Query nearby parcels (0.2 mile radius)
    nearby_parcels = query_reportall_nearby_parcels(REPORTALL_CLIENT_OR_TOKEN, addr_lon, addr_lat, radius_miles=0.05)
    print(f"[LOMA] Found {len(nearby_parcels)} nearby parcels within 0.2 miles")

    if nearby_parcels:
        # Build bbox from all nearby parcels
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
            print(f"[LOMA] Built bbox from {len(all_geoms)} parcel geometries")
            print(f"[LOMA] LOMA search bbox: {loma_bbox}")
            # Query LOMA features in the bbox
            lomas = fetch_nfhl_loma(loma_bbox)
            print(f"[LOMA] Found {len(lomas)} LOMA features in bbox")

            if not lomas.empty:
                # Rank LOMAs by distance to address point
                address_point = shapely_wkt.loads(f"POINT({addr_lon} {addr_lat})")
                lomas = lomas.copy()
                lomas["distance_m"] = lomas.geometry.apply(lambda g: address_point.distance(g) * 111_320.0 if g else None)
                lomas = lomas.sort_values("distance_m")

                # Write LOMA results to CSV
                cols = ["distance_m"]
                cols.extend([c for c in lomas.columns if c not in ["geometry", "distance_m"]])
                lomas[cols].to_csv(OUT_LOMA_CSV, index=False)
                print(f"[OK] Wrote {len(lomas)} ranked LOMAs: {OUT_LOMA_CSV}")
            else:
                print("[INFO] No LOMA features found in nearby area.")
        else:
            print("[INFO] Could not parse nearby parcel geometries for LOMA bbox.")
    else:
        print("[INFO] No nearby parcels found for LOMA search.")


if __name__ == "__main__":
    main()
