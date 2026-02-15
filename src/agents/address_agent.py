"""
Agent 1: Address Verification & Polygon Extraction
"""

from typing import Dict, Any, Optional
from shapely import wkt as shapely_wkt

from src.agents.base import BaseAgent
from src.models import Address, Evidence
from src.models.agent_models import AddressVerificationResult
from src.integrations.reportall_client import ReportAllClient
from src.state_machine import AddressVerificationSM, Context
from src.dmn.classify import classify


class AddressVerificationAgent(BaseAgent):
    """Agent 1: Address verification and polygon extraction using ReportAll API."""
    
    def __init__(self, reportall_client_key: str):
        """
        Initialize Address Verification Agent.
        
        Args:
            reportall_client_key: ReportAll API client key
        """
        super().__init__("AddressVerificationAgent")
        self.reportall_client = ReportAllClient(reportall_client_key)
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate input data."""
        # Must have either address or parcel_id
        has_address = bool(input_data.get("address") or input_data.get("q"))
        has_parcel_id = bool(input_data.get("parcel_id") and input_data.get("region"))
        has_mode = input_data.get("mode") in ["address", "parcel_id"]
        
        return (has_address or has_parcel_id) and has_mode
    
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute address verification and polygon extraction.
        
        Input:
            {
                "mode": "address" | "parcel_id",
                "address": str (optional, for address mode),
                "q": str (optional, full address string),
                "region": str (optional, for address mode),
                "parcel_id": str (optional, for parcel_id mode),
                "parcel_region": str (optional, for parcel_id mode)
            }
        
        Returns:
            AddressVerificationResult as dict
        """
        if not self.validate_input(input_data):
            raise ValueError("Invalid input: must provide address or parcel_id with mode")
        
        mode = input_data.get("mode")
        
        try:
            # Step 1: Query ReportAll API
            if mode == "address":
                q = input_data.get("q")
                address = input_data.get("address")
                region = input_data.get("region")
                
                self.log(f"Querying ReportAll by address: {q or address}")
                response = self.reportall_client.query_by_address(
                    q=q,
                    address=address,
                    region=region
                )
            else:  # parcel_id mode
                parcel_id = input_data.get("parcel_id")
                region = input_data.get("parcel_region") or input_data.get("region")
                
                self.log(f"Querying ReportAll by parcel ID: {parcel_id}")
                response = self.reportall_client.query_by_parcel_id(
                    parcel_id=parcel_id,
                    region=region
                )
            
            # Step 2: Extract parcel geometry
            parcel_wkt, parcel_record = ReportAllClient.parse_first_parcel(response)
            parcel_geom = shapely_wkt.loads(parcel_wkt)
            parcel_centroid = (parcel_geom.centroid.x, parcel_geom.centroid.y)
            
            self.log(f"Extracted parcel geometry: {len(parcel_wkt)} chars WKT")
            
            # Step 3: Build Address object from ReportAll record
            address_obj = self._build_address_from_record(parcel_record, input_data)
            
            # Step 4: Run address classification
            classification = classify(address_obj)
            self.log(f"Address classification: {classification.addressType} "
                    f"(variant: {classification.variant})")
            
            # Step 5: Run address verification state machine
            evidence = Evidence()
            context = Context(address=address_obj, evidence=evidence)
            state_machine = AddressVerificationSM(context)
            final_context = state_machine.run()
            
            # Step 6: Extract buildings if available
            buildings = self._extract_buildings(parcel_record)
            if buildings:
                self.log(f"Found {len(buildings)} building(s)")
            
            # Step 7: Build result
            result = AddressVerificationResult(
                address=final_context.address,
                address_type=final_context.classification.addressType if final_context.classification else "Unknown",
                confidence=final_context.confidence_result.normalized_score if final_context.confidence_result else 0.0,
                routing=final_context.confidence_result.routing if final_context.confidence_result else "Unknown",
                parcel_wkt=parcel_wkt,
                parcel_centroid=parcel_centroid,
                parcel_record=parcel_record,
                buildings=buildings,
                verification_status="verified" if final_context.confidence_result and final_context.confidence_result.normalized_score >= 0.6 else "incomplete",
                evidence=final_context.evidence,
                logs=self.logs + final_context.logs,
                classification_variant=classification.variant,
                classification_rationale=classification.rationale
            )
            
            self.log("Address verification completed successfully")
            return self._result_to_dict(result)
            
        except Exception as e:
            self.log(f"Error during address verification: {e}")
            # Return partial result with error
            error_result = AddressVerificationResult(
                address=Address(),
                address_type="Unknown",
                confidence=0.0,
                routing="Unknown",
                parcel_wkt="",
                parcel_centroid=(0.0, 0.0),
                parcel_record={},
                verification_status="failed",
                logs=self.logs + [f"ERROR: {str(e)}"]
            )
            return self._result_to_dict(error_result)
    
    def _build_address_from_record(self, record: Dict[str, Any], input_data: Dict[str, Any]) -> Address:
        """Build Address object from ReportAll record and input data."""
        # Try to extract from record first, fallback to input_data
        address = Address(
            streetNumber=record.get("street_number") or input_data.get("street_number"),
            streetName=record.get("street_name") or input_data.get("street_name"),
            direction=record.get("direction") or input_data.get("direction"),
            city=record.get("city") or input_data.get("city"),
            state=record.get("state") or input_data.get("state"),
            zip=record.get("zip") or input_data.get("zip"),
            subdivision=record.get("subdivision") or input_data.get("subdivision"),
            lot=record.get("lot") or input_data.get("lot"),
            block=record.get("block") or input_data.get("block"),
            str=record.get("str") or input_data.get("str"),
            drivingDirections=input_data.get("driving_directions"),
            poBox=input_data.get("po_box"),
            tbdStreet=input_data.get("tbd_street", False)
        )
        return address
    
    def _extract_buildings(self, record: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Extract building footprints from ReportAll record."""
        buildings = []
        buildings_poly = record.get("buildings_poly") or []
        
        for bi, b in enumerate(buildings_poly):
            if isinstance(b, dict):
                bwkt = b.get("geom_as_wkt") or b.get("wkt")
                if bwkt:
                    building_info = {
                        "building_index": bi,
                        "geom_wkt": bwkt,
                        **{k: v for k, v in b.items() if k not in ("geom_as_wkt", "wkt")}
                    }
                    buildings.append(building_info)
            elif isinstance(b, str):
                buildings.append({
                    "building_index": bi,
                    "geom_wkt": b
                })
        
        return buildings
    
    def _result_to_dict(self, result: AddressVerificationResult) -> Dict[str, Any]:
        """Convert AddressVerificationResult to dictionary."""
        from dataclasses import asdict
        return asdict(result)

