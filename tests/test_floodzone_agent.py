"""
Unit tests for Flood Zone Agent.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import geopandas as gpd
from shapely.geometry import Polygon, Point

from src.agents.floodzone_agent import FloodZoneAgent


class TestFloodZoneAgent(unittest.TestCase):
    """Test cases for FloodZoneAgent."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.agent = FloodZoneAgent(use_wfs=False)
    
    def test_validate_input(self):
        """Test input validation."""
        # Valid input
        valid_input = {
            "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))"
        }
        self.assertTrue(self.agent.validate_input(valid_input))
        
        # Invalid - missing parcel_wkt
        invalid_input = {
            "parcel_centroid": (-78.85, 40.35)
        }
        self.assertFalse(self.agent.validate_input(invalid_input))
    
    @patch('src.agents.floodzone_agent.FEMAClient.overlay_parcel_floodzones')
    @patch('src.agents.floodzone_agent.FEMAClient')
    def test_execute_no_flood_zones(self, mock_client_class, mock_overlay):
        """Test execution when no flood zones are found."""
        # Mock FEMA client
        mock_client = Mock()
        mock_client.fetch_flood_zones.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        mock_client_class.return_value = mock_client
        
        # Mock static method
        mock_overlay.return_value = (
            gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"),
            None
        )
        
        agent = FloodZoneAgent(use_wfs=False)
        agent.fema_client = mock_client
        
        input_data = {
            "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            "include_loma": False
        }
        
        result = agent.execute(input_data)
        
        # Verify result
        self.assertFalse(result["in_flood_zone"])
        self.assertEqual(len(result["flood_zones"]), 0)
        self.assertIsNone(result["union_overlap_wkt"])
    
    @patch('src.agents.floodzone_agent.FEMAClient.overlay_parcel_floodzones')
    @patch('src.agents.floodzone_agent.FEMAClient')
    def test_execute_with_flood_zones(self, mock_client_class, mock_overlay):
        """Test execution when flood zones are found."""
        # Create mock flood zone geometry
        flood_zone_geom = Polygon([
            (-78.9, 40.3),
            (-78.9, 40.4),
            (-78.8, 40.4),
            (-78.8, 40.3),
            (-78.9, 40.3)
        ])
        
        # Create GeoDataFrame with flood zone
        nfhl_gdf = gpd.GeoDataFrame({
            "FLD_ZONE": ["AE"],
            "ZONE_SUBTY": ["Base Flood Elevation"],
            "SFHA_TF": ["T"]
        }, geometry=[flood_zone_geom], crs="EPSG:4326")
        
        # Create parcel geometry (overlaps with flood zone)
        parcel_geom = Polygon([
            (-78.89, 40.31),
            (-78.89, 40.39),
            (-78.81, 40.39),
            (-78.81, 40.31),
            (-78.89, 40.31)
        ])
        
        # Mock intersection result
        intersection_geom = parcel_geom.intersection(flood_zone_geom)
        per_zone = gpd.GeoDataFrame({
            "FLD_ZONE": ["AE"],
            "ZONE_SUBTY": ["Base Flood Elevation"],
            "SFHA_TF": ["T"]
        }, geometry=[intersection_geom], crs="EPSG:4326")
        
        # Mock FEMA client
        mock_client = Mock()
        mock_client.fetch_flood_zones.return_value = nfhl_gdf
        mock_client_class.return_value = mock_client
        
        # Mock static method
        mock_overlay.return_value = (per_zone, intersection_geom)
        
        agent = FloodZoneAgent(use_wfs=False)
        agent.fema_client = mock_client
        
        input_data = {
            "parcel_wkt": parcel_geom.wkt,
            "include_loma": False
        }
        
        result = agent.execute(input_data)
        
        # Verify result
        self.assertTrue(result["in_flood_zone"])
        self.assertEqual(len(result["flood_zones"]), 1)
        self.assertEqual(result["primary_zone"], "AE")
        self.assertIsNotNone(result["union_overlap_wkt"])
    
    @patch('src.agents.floodzone_agent.FEMAClient.overlay_parcel_floodzones')
    @patch('src.agents.floodzone_agent.FEMAClient')
    def test_execute_with_buildings(self, mock_client_class, mock_overlay):
        """Test execution with building footprints."""
        # Mock empty flood zones
        mock_client = Mock()
        mock_client.fetch_flood_zones.return_value = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        mock_client_class.return_value = mock_client
        
        # Mock static method
        mock_overlay.return_value = (
            gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"),
            None
        )
        
        agent = FloodZoneAgent(use_wfs=False)
        agent.fema_client = mock_client
        
        building_geom = Polygon([
            (-78.89, 40.31),
            (-78.89, 40.32),
            (-78.88, 40.32),
            (-78.88, 40.31),
            (-78.89, 40.31)
        ])
        
        input_data = {
            "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            "buildings": [
                {
                    "building_index": 0,
                    "geom_wkt": building_geom.wkt
                }
            ],
            "include_loma": False
        }
        
        result = agent.execute(input_data)
        
        # Verify building processing (even if no overlaps)
        self.assertIn("building_overlaps", result)
        # Building overlaps should be empty if no flood zones found
        self.assertEqual(len(result["building_overlaps"]), 0)


if __name__ == "__main__":
    unittest.main()

