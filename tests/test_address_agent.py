"""
Unit tests for Address Verification Agent.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from src.agents.address_agent import AddressVerificationAgent
from src.models import Address


class TestAddressVerificationAgent(unittest.TestCase):
    """Test cases for AddressVerificationAgent."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.agent = AddressVerificationAgent(reportall_client_key="test_key")
    
    def test_validate_input_address_mode(self):
        """Test input validation for address mode."""
        # Valid address input
        valid_input = {
            "mode": "address",
            "q": "1137 Barnett street, johnstown, pa"
        }
        self.assertTrue(self.agent.validate_input(valid_input))
        
        # Valid address with separate fields
        valid_input2 = {
            "mode": "address",
            "address": "1137 Barnett street",
            "region": "johnstown, pa"
        }
        self.assertTrue(self.agent.validate_input(valid_input2))
        
        # Invalid - missing mode
        invalid_input = {
            "q": "1137 Barnett street, johnstown, pa"
        }
        self.assertFalse(self.agent.validate_input(invalid_input))
        
        # Invalid - missing address
        invalid_input2 = {
            "mode": "address"
        }
        self.assertFalse(self.agent.validate_input(invalid_input2))
    
    def test_validate_input_parcel_mode(self):
        """Test input validation for parcel_id mode."""
        # Valid parcel_id input
        valid_input = {
            "mode": "parcel_id",
            "parcel_id": "766620-1420",
            "region": "King County, Washington"
        }
        self.assertTrue(self.agent.validate_input(valid_input))
        
        # Invalid - missing parcel_id
        invalid_input = {
            "mode": "parcel_id",
            "region": "King County, Washington"
        }
        self.assertFalse(self.agent.validate_input(invalid_input))
    
    @patch('src.agents.address_agent.ReportAllClient')
    def test_execute_address_mode(self, mock_client_class):
        """Test execution with address mode."""
        # Mock ReportAll response
        mock_response = {
            "status": "OK",
            "results": [{
                "geom_as_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
                "street_number": "1137",
                "street_name": "Barnett",
                "city": "Johnstown",
                "state": "PA",
                "zip": "15901"
            }]
        }
        
        mock_client = Mock()
        mock_client.query_by_address.return_value = mock_response
        mock_client_class.return_value = mock_client
        mock_client_class.parse_first_parcel.return_value = (
            "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            mock_response["results"][0]
        )
        
        # Reinitialize agent to use mocked client
        agent = AddressVerificationAgent(reportall_client_key="test_key")
        agent.reportall_client = mock_client
        
        input_data = {
            "mode": "address",
            "q": "1137 Barnett street, johnstown, pa"
        }
        
        result = agent.execute(input_data)
        
        # Verify result structure
        self.assertIn("address", result)
        self.assertIn("parcel_wkt", result)
        self.assertIn("parcel_centroid", result)
        self.assertIn("verification_status", result)
        self.assertEqual(result["address_type"], "Standard")
    
    @patch('src.agents.address_agent.ReportAllClient')
    def test_execute_parcel_mode(self, mock_client_class):
        """Test execution with parcel_id mode."""
        # Mock ReportAll response
        mock_response = {
            "status": "OK",
            "results": [{
                "geom_as_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
                "parcel_id": "766620-1420"
            }]
        }
        
        mock_client = Mock()
        mock_client.query_by_parcel_id.return_value = mock_response
        mock_client_class.return_value = mock_client
        mock_client_class.parse_first_parcel.return_value = (
            "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            mock_response["results"][0]
        )
        
        agent = AddressVerificationAgent(reportall_client_key="test_key")
        agent.reportall_client = mock_client
        
        input_data = {
            "mode": "parcel_id",
            "parcel_id": "766620-1420",
            "region": "King County, Washington"
        }
        
        result = agent.execute(input_data)
        
        # Verify result structure
        self.assertIn("parcel_wkt", result)
        self.assertIn("parcel_centroid", result)
    
    def test_build_address_from_record(self):
        """Test building Address object from record."""
        record = {
            "street_number": "1137",
            "street_name": "Barnett",
            "city": "Johnstown",
            "state": "PA",
            "zip": "15901"
        }
        
        input_data = {}
        address = self.agent._build_address_from_record(record, input_data)
        
        self.assertEqual(address.streetNumber, "1137")
        self.assertEqual(address.streetName, "Barnett")
        self.assertEqual(address.city, "Johnstown")
        self.assertEqual(address.state, "PA")
        self.assertEqual(address.zip, "15901")
    
    def test_extract_buildings(self):
        """Test extracting buildings from record."""
        record = {
            "buildings_poly": [
                {
                    "geom_as_wkt": "POLYGON((-78.9 40.3, -78.9 40.31, -78.89 40.31, -78.89 40.3, -78.9 40.3))",
                    "building_id": "B001"
                }
            ]
        }
        
        buildings = self.agent._extract_buildings(record)
        
        self.assertEqual(len(buildings), 1)
        self.assertIn("geom_wkt", buildings[0])
        self.assertEqual(buildings[0]["building_index"], 0)


if __name__ == "__main__":
    unittest.main()

