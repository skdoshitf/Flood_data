"""
Integration tests for orchestrator.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
from pathlib import Path

from src.orchestrator import FloodZoneOrchestrator
from src.models.orchestrator_models import OrchestratorRequest
from src.models.agent_models import AddressVerificationResult, FloodZoneResult


class TestOrchestrator(unittest.TestCase):
    """Integration tests for FloodZoneOrchestrator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = FloodZoneOrchestrator(
            reportall_key="test_key",
            use_wfs=False,
            output_dir=self.temp_dir
        )
    
    @patch('src.agents.address_agent.AddressVerificationAgent')
    @patch('src.agents.floodzone_agent.FloodZoneAgent')
    def test_execute_with_address(self, mock_floodzone_agent_class, mock_address_agent_class):
        """Test orchestrator execution with address input."""
        # Mock Agent 1
        mock_agent1 = Mock()
        mock_agent1.execute.return_value = {
            "address": {"streetNumber": "1137", "streetName": "Barnett", "city": "Johnstown", "state": "PA"},
            "address_type": "Standard",
            "confidence": 0.95,
            "routing": "Auto",
            "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            "parcel_centroid": (-78.85, 40.35),
            "parcel_record": {},
            "verification_status": "verified",
            "buildings": [],
            "logs": []
        }
        mock_address_agent_class.return_value = mock_agent1
        
        # Mock Agent 2
        mock_agent2 = Mock()
        mock_agent2.execute.return_value = {
            "flood_zones": [],
            "in_flood_zone": False,
            "primary_zone": None,
            "nfhl_features_count": 0,
            "query_bbox": (-78.91, 40.29, -78.79, 40.41),
            "logs": []
        }
        mock_floodzone_agent_class.return_value = mock_agent2
        
        # Create orchestrator with mocked agents
        orchestrator = FloodZoneOrchestrator(
            reportall_key="test_key",
            use_wfs=False,
            output_dir=self.temp_dir
        )
        orchestrator.agent1 = mock_agent1
        orchestrator.agent2 = mock_agent2
        
        # Execute
        request = OrchestratorRequest(
            address="1137 Barnett street, johnstown, pa"
        )
        result = orchestrator.execute(request)
        
        # Verify
        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.address_verification)
        self.assertIsNotNone(result.flood_zone)
        self.assertGreater(result.execution_time_seconds, 0)
        
        # Verify agents were called
        mock_agent1.execute.assert_called_once()
        mock_agent2.execute.assert_called_once()
    
    @patch('src.agents.address_agent.AddressVerificationAgent')
    @patch('src.agents.floodzone_agent.FloodZoneAgent')
    def test_execute_with_natural_language(self, mock_floodzone_agent_class, mock_address_agent_class):
        """Test orchestrator execution with natural language query."""
        # Mock Agent 1
        mock_agent1 = Mock()
        mock_agent1.execute.return_value = {
            "address": {"streetNumber": "1137", "streetName": "Barnett", "city": "Johnstown", "state": "PA"},
            "address_type": "Standard",
            "confidence": 0.95,
            "routing": "Auto",
            "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
            "parcel_centroid": (-78.85, 40.35),
            "parcel_record": {},
            "verification_status": "verified",
            "buildings": [],
            "logs": []
        }
        mock_address_agent_class.return_value = mock_agent1
        
        # Mock Agent 2
        mock_agent2 = Mock()
        mock_agent2.execute.return_value = {
            "flood_zones": [],
            "in_flood_zone": False,
            "primary_zone": None,
            "nfhl_features_count": 0,
            "query_bbox": (-78.91, 40.29, -78.79, 40.41),
            "logs": []
        }
        mock_floodzone_agent_class.return_value = mock_agent2
        
        orchestrator = FloodZoneOrchestrator(
            reportall_key="test_key",
            use_wfs=False,
            output_dir=self.temp_dir
        )
        orchestrator.agent1 = mock_agent1
        orchestrator.agent2 = mock_agent2
        
        # Execute with NL query
        request = OrchestratorRequest(
            natural_language_query="Check flood zone for 1137 Barnett street, johnstown, pa"
        )
        result = orchestrator.execute(request)
        
        # Verify
        self.assertEqual(result.status, "success")
        # Verify NL parsing was used
        self.assertIn("Parsing natural language query", str(orchestrator.logs))
    
    @patch('src.agents.address_agent.AddressVerificationAgent')
    def test_execute_agent1_failure(self, mock_address_agent_class):
        """Test orchestrator handling of Agent 1 failure."""
        # Mock Agent 1 to fail
        mock_agent1 = Mock()
        mock_agent1.execute.side_effect = RuntimeError("ReportAll API error")
        mock_address_agent_class.return_value = mock_agent1
        
        orchestrator = FloodZoneOrchestrator(
            reportall_key="test_key",
            use_wfs=False,
            output_dir=self.temp_dir
        )
        orchestrator.agent1 = mock_agent1
        
        request = OrchestratorRequest(
            address="1137 Barnett street, johnstown, pa"
        )
        result = orchestrator.execute(request)
        
        # Verify error handling
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
    
    @patch('src.agents.address_agent.AddressVerificationAgent')
    @patch('src.agents.floodzone_agent.FloodZoneAgent')
    def test_retry_logic(self, mock_floodzone_agent_class, mock_address_agent_class):
        """Test retry logic for agent failures."""
        # Mock Agent 1 to fail twice then succeed
        mock_agent1 = Mock()
        mock_agent1.execute.side_effect = [
            ConnectionError("Connection failed"),
            ConnectionError("Connection failed"),
            {
                "address": {"streetNumber": "1137", "streetName": "Barnett", "city": "Johnstown", "state": "PA"},
                "address_type": "Standard",
                "confidence": 0.95,
                "routing": "Auto",
                "parcel_wkt": "POLYGON((-78.9 40.3, -78.9 40.4, -78.8 40.4, -78.8 40.3, -78.9 40.3))",
                "parcel_centroid": (-78.85, 40.35),
                "parcel_record": {},
                "verification_status": "verified",
                "buildings": [],
                "logs": []
            }
        ]
        mock_address_agent_class.return_value = mock_agent1
        
        # Mock Agent 2
        mock_agent2 = Mock()
        mock_agent2.execute.return_value = {
            "flood_zones": [],
            "in_flood_zone": False,
            "primary_zone": None,
            "nfhl_features_count": 0,
            "query_bbox": (-78.91, 40.29, -78.79, 40.41),
            "logs": []
        }
        mock_floodzone_agent_class.return_value = mock_agent2
        
        orchestrator = FloodZoneOrchestrator(
            reportall_key="test_key",
            use_wfs=False,
            output_dir=self.temp_dir
        )
        orchestrator.agent1 = mock_agent1
        orchestrator.agent2 = mock_agent2
        
        request = OrchestratorRequest(
            address="1137 Barnett street, johnstown, pa"
        )
        result = orchestrator.execute(request)
        
        # Verify retry happened
        self.assertEqual(mock_agent1.execute.call_count, 3)
        self.assertEqual(result.status, "success")


if __name__ == "__main__":
    unittest.main()

