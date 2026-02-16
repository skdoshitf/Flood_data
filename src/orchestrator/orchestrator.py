"""
Main orchestrator for coordinating agents in flood zone determination workflow.
"""

import time
from typing import Dict, Any, Optional
from pathlib import Path

from src.agents import AddressVerificationAgent, FloodZoneAgent
from src.models.orchestrator_models import OrchestratorRequest, OrchestratorResult
from src.models.agent_models import AddressVerificationResult, FloodZoneResult
from src.orchestrator.process_def import ProcessDefinition, ProcessStep
from src.orchestrator.nl_parser import NLQueryParser
from src.utils.cache import CacheManager
from src.utils.logger import setup_logger


class FloodZoneOrchestrator:
    """Main orchestrator coordinating agents for flood zone determination."""
    
    def __init__(self,
                 reportall_key: str,
                 use_wfs: bool = False,
                 output_dir: Optional[str] = None,
                 cache_manager: Optional[CacheManager] = None,
                 cache_enabled: bool = True):
        """
        Initialize orchestrator.
        
        Args:
            reportall_key: ReportAll API client key
            use_wfs: If True, use WFS endpoint for FEMA; otherwise use REST
            output_dir: Directory for output files (default: current directory)
            cache_manager: Optional CacheManager instance
            cache_enabled: Whether caching is enabled
        """
        # Setup cache
        if cache_manager:
            self.cache = cache_manager
        elif cache_enabled:
            self.cache = CacheManager()
        else:
            self.cache = None
        
        # Initialize agents with caching
        from src.integrations.reportall_client import ReportAllClient
        from src.integrations.fema_client import FEMAClient
        
        reportall_client = ReportAllClient(
            reportall_key,
            cache_manager=self.cache,
            cache_enabled=cache_enabled
        )
        fema_client = FEMAClient(
            use_wfs=use_wfs,
            cache_manager=self.cache,
            cache_enabled=cache_enabled
        )
        
        # Create agents (they'll use the clients internally)
        self.agent1 = AddressVerificationAgent(reportall_key)
        self.agent1.reportall_client = reportall_client
        
        self.agent2 = FloodZoneAgent(use_wfs=use_wfs)
        self.agent2.fema_client = fema_client
        
        self.nl_parser = NLQueryParser()
        self.process = ProcessDefinition()
        self.output_dir = Path(output_dir) if output_dir else Path(".")
        self.reportall_key = reportall_key
        
        # Setup logger
        self.logger = setup_logger("orchestrator")
        
        # Execution state
        self.logs: list[str] = []
        self.current_step: Optional[ProcessStep] = None
    
    def log(self, message: str) -> None:
        """Add log message."""
        log_entry = f"[Orchestrator] {message}"
        self.logs.append(log_entry)
        print(log_entry)
    
    def execute(self, request: OrchestratorRequest) -> OrchestratorResult:
        """
        Execute the complete workflow.
        
        Args:
            request: OrchestratorRequest with input parameters
            
        Returns:
            OrchestratorResult with aggregated results
        """
        start_time = time.time()
        self.logs.clear()
        self.log("Starting orchestrator execution")
        
        try:
            # Step 1: Parse input
            params = self._parse_input(request)
            
            # Step 2: Invoke Agent 1 - Address Verification
            agent1_result = self._invoke_agent1(params, request)
            
            # Step 3: Validate Agent 1 result
            if not self._validate_agent1_result(agent1_result):
                return self._create_error_result(
                    request,
                    agent1_result,
                    None,
                    "Agent 1 validation failed: address verification incomplete or failed",
                    start_time
                )
            
            # Step 4: Invoke Agent 2 - Flood Zone Determination
            agent2_input = self._prepare_agent2_input(agent1_result, request)
            agent2_result = self._invoke_agent2(agent2_input, request)
            
            # Step 5: Aggregate results
            result = self._aggregate_results(request, agent1_result, agent2_result, start_time)
            
            # Step 6: Generate outputs
            self._generate_outputs(result)
            
            self.log("Orchestrator execution completed successfully")
            return result
            
        except Exception as e:
            self.log(f"Orchestrator execution failed: {e}")
            return self._create_error_result(
                request,
                None,
                None,
                f"Orchestrator error: {str(e)}",
                start_time
            )
    
    def _parse_input(self, request: OrchestratorRequest) -> Dict[str, Any]:
        """Step 1: Parse input (NL or structured)."""
        self.current_step = ProcessStep.PARSE_INPUT
        self.log("Parsing input...")
        
        if request.natural_language_query:
            self.log(f"Parsing natural language query: {request.natural_language_query}")
            parsed = self.nl_parser.parse(request.natural_language_query)
            
            # Validate parsed result
            is_valid, error_msg = self.nl_parser.validate_parsed(parsed)
            if not is_valid:
                raise ValueError(f"NL parsing failed: {error_msg}")
            
            # Merge with request config
            params = {
                "mode": parsed.get("mode", "address"),
                "q": parsed.get("q") or request.address,
                "address": parsed.get("address"),
                "region": parsed.get("region") or request.region,
                "parcel_id": parsed.get("parcel_id") or request.parcel_id,
                "parcel_region": parsed.get("region") or request.region,
            }
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            # Add configuration from request
            params["include_loma"] = parsed.get("include_loma", request.include_loma)
            params["include_buildings"] = parsed.get("include_buildings", request.include_buildings)
        else:
            # Use structured parameters
            self.log("Using structured parameters")
            params = {
                "mode": "parcel_id" if request.parcel_id else "address",
                "q": request.address,
                "address": request.address,
                "region": request.region,
                "parcel_id": request.parcel_id,
                "parcel_region": request.region,
                "include_loma": request.include_loma,
                "include_buildings": request.include_buildings,
            }
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
        
        self.log(f"Parsed parameters: mode={params.get('mode')}")
        return params
    
    def _invoke_agent1(self, params: Dict[str, Any], request: OrchestratorRequest) -> Dict[str, Any]:
        """Step 2: Invoke Agent 1 with retry logic."""
        self.current_step = ProcessStep.INVOKE_AGENT1
        self.log("Invoking Agent 1: Address Verification")
        
        retry_policy = self.process.get_retry_policy(ProcessStep.INVOKE_AGENT1)
        max_retries = retry_policy["max_retries"]
        retry_delay = retry_policy["retry_delay"]
        
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = self.agent1.execute(params)
                self.log(f"Agent 1 completed successfully (attempt {attempt + 1})")
                return result
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                
                if attempt < max_retries and error_type in retry_policy["retry_on"]:
                    self.log(f"Agent 1 failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying...")
                    time.sleep(retry_delay)
                else:
                    self.log(f"Agent 1 failed after {attempt + 1} attempts: {e}")
                    raise
        
        # Should not reach here, but just in case
        raise last_error or RuntimeError("Agent 1 execution failed")
    
    def _validate_agent1_result(self, agent1_result: Dict[str, Any]) -> bool:
        """Step 3: Validate Agent 1 result."""
        self.current_step = ProcessStep.VALIDATE_AGENT1_RESULT
        self.log("Validating Agent 1 result...")
        
        if not agent1_result:
            self.log("Agent 1 result is empty")
            return False
        
        verification_status = agent1_result.get("verification_status")
        if verification_status == "failed":
            self.log("Agent 1 verification status: failed")
            return False
        
        parcel_wkt = agent1_result.get("parcel_wkt")
        if not parcel_wkt:
            self.log("Agent 1 result missing parcel_wkt")
            return False
        
        self.log(f"Agent 1 validation passed: status={verification_status}")
        return True
    
    def _prepare_agent2_input(self, agent1_result: Dict[str, Any], request: OrchestratorRequest) -> Dict[str, Any]:
        """Prepare input for Agent 2 from Agent 1 result."""
        return {
            "parcel_wkt": agent1_result["parcel_wkt"],
            "parcel_centroid": agent1_result.get("parcel_centroid"),
            "buildings": agent1_result.get("buildings", []),
            "include_loma": request.include_loma,
            "loma_radius_miles": request.loma_radius_miles,
            "reportall_client_key": self.reportall_key,
        }
    
    def _invoke_agent2(self, agent2_input: Dict[str, Any], request: OrchestratorRequest) -> Dict[str, Any]:
        """Step 4: Invoke Agent 2 with retry logic."""
        self.current_step = ProcessStep.INVOKE_AGENT2
        self.log("Invoking Agent 2: Flood Zone Determination")
        
        retry_policy = self.process.get_retry_policy(ProcessStep.INVOKE_AGENT2)
        max_retries = retry_policy["max_retries"]
        retry_delay = retry_policy["retry_delay"]
        
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = self.agent2.execute(agent2_input)
                self.log(f"Agent 2 completed successfully (attempt {attempt + 1})")
                return result
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                
                if attempt < max_retries and error_type in retry_policy["retry_on"]:
                    self.log(f"Agent 2 failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying...")
                    time.sleep(retry_delay)
                else:
                    self.log(f"Agent 2 failed after {attempt + 1} attempts: {e}")
                    raise
        
        # Should not reach here
        raise last_error or RuntimeError("Agent 2 execution failed")
    
    def _aggregate_results(self,
                          request: OrchestratorRequest,
                          agent1_result: Optional[Dict[str, Any]],
                          agent2_result: Optional[Dict[str, Any]],
                          start_time: float) -> OrchestratorResult:
        from src.models import Address
        """Step 5: Aggregate results from both agents."""
        self.current_step = ProcessStep.AGGREGATE_RESULTS
        self.log("Aggregating results...")
        
        execution_time = time.time() - start_time
        
        # Convert dict results to model objects
        address_verification = None
        if agent1_result:
            try:
                address_verification = AddressVerificationResult(**agent1_result)
            except Exception as e:
                self.log(f"Error converting agent1 result: {e}")
                # Create minimal result
                address_verification = self._create_minimal_address_result(
                    address=Address(),
                    address_type="Unknown",
                    confidence=0.0,
                    routing="Unknown",
                    parcel_wkt="",
                    parcel_centroid=(0.0, 0.0),
                    parcel_record={},
                    verification_status="failed",
                    logs=self.logs
                )
        
        flood_zone = None
        if agent2_result:
            try:
                flood_zone = FloodZoneResult(**agent2_result)
            except Exception as e:
                self.log(f"Error converting agent2 result: {e}")
                # Create minimal result
                flood_zone = FloodZoneResult(
                    flood_zones=[],
                    in_flood_zone=False,
                    query_bbox=None,
                    nfhl_features_count=0,
                    logs=self.logs,
                    error=str(e)
                )
        
        # Determine overall status
        if address_verification and flood_zone:
            if address_verification.verification_status == "verified" and not flood_zone.error:
                status = "success"
            elif address_verification.verification_status == "incomplete" or flood_zone.error:
                status = "partial"
            else:
                status = "failed"
        else:
            status = "failed"
        
        result = OrchestratorResult(
            request=request,
            address_verification=address_verification or self._create_minimal_address_result(),
            flood_zone=flood_zone or FloodZoneResult(
                flood_zones=[],
                in_flood_zone=False,
                query_bbox=None,
                nfhl_features_count=0
            ),
            status=status,
            execution_time_seconds=execution_time
        )
        
        # Combine logs
        if address_verification:
            result.address_verification.logs.extend(self.logs)
        if flood_zone:
            flood_zone.logs.extend(self.logs)
        
        self.log(f"Results aggregated: status={status}, time={execution_time:.2f}s")
        return result
    
    def _generate_outputs(self, result: OrchestratorResult) -> None:
        """Step 6: Generate output files."""
        self.current_step = ProcessStep.GENERATE_OUTPUTS
        self.log("Generating output files...")
        
        output_files = {}
        
        try:
            # Write parcel geometry
            if result.address_verification.parcel_wkt:
                parcel_file = self.output_dir / "parcel_geom.wkt"
                parcel_file.write_text(result.address_verification.parcel_wkt)
                output_files["parcel_geom.wkt"] = str(parcel_file)
                self.log(f"Wrote parcel geometry: {parcel_file}")
            
            # Write flood zone overlaps
            if result.flood_zone.flood_zones:
                import pandas as pd
                overlap_file = self.output_dir / "overlap_by_zone.csv"
                
                # Convert flood zones to DataFrame
                df_data = []
                for zone in result.flood_zone.flood_zones:
                    row = {k: v for k, v in zone.items() if k != "overlap_wkt"}
                    row["overlap_wkt"] = zone.get("overlap_wkt", "")
                    df_data.append(row)
                
                if df_data:
                    df = pd.DataFrame(df_data)
                    df.to_csv(overlap_file, index=False)
                    output_files["overlap_by_zone.csv"] = str(overlap_file)
                    self.log(f"Wrote flood zone overlaps: {overlap_file}")
            
            # Write union overlap
            if result.flood_zone.union_overlap_wkt:
                union_file = self.output_dir / "overlap_union.wkt"
                union_file.write_text(result.flood_zone.union_overlap_wkt)
                output_files["overlap_union.wkt"] = str(union_file)
                self.log(f"Wrote union overlap: {union_file}")
            
            # Write LOMA results
            if result.flood_zone.loma_features:
                import pandas as pd
                loma_file = self.output_dir / "loma_results.csv"
                df = pd.DataFrame(result.flood_zone.loma_features)
                df.to_csv(loma_file, index=False)
                output_files["loma_results.csv"] = str(loma_file)
                self.log(f"Wrote LOMA results: {loma_file}")
            
            result.output_files = output_files
            
        except Exception as e:
            self.log(f"Error generating output files: {e}")
            # Don't fail the whole process if file writing fails
    
    def _create_minimal_address_result(self) -> AddressVerificationResult:
        """Create minimal AddressVerificationResult."""
        # Import Address from models package (which re-exports from models.py)
        from src.models import Address
        
        return AddressVerificationResult(
            address=Address(),
            address_type="Unknown",
            confidence=0.0,
            routing="Unknown",
            parcel_wkt="",
            parcel_centroid=(0.0, 0.0),
            parcel_record={},
            verification_status="failed"
        )
    
    def _create_error_result(self,
                            request: OrchestratorRequest,
                            agent1_result: Optional[Dict[str, Any]],
                            agent2_result: Optional[Dict[str, Any]],
                            error_msg: str,
                            start_time: float) -> OrchestratorResult:
        """Create error result when execution fails."""
        execution_time = time.time() - start_time
        
        # Create minimal results
        address_verification = self._create_minimal_address_result()
        address_verification.logs = self.logs + [error_msg]
        
        if agent1_result:
            try:
                address_verification = AddressVerificationResult(**agent1_result)
            except Exception:
                pass
        
        flood_zone = FloodZoneResult(
            flood_zones=[],
            in_flood_zone=False,
            query_bbox=None,
            nfhl_features_count=0,
            logs=self.logs + [error_msg],
            error=error_msg
        )
        
        if agent2_result:
            try:
                flood_zone = FloodZoneResult(**agent2_result)
            except Exception:
                pass
        
        return OrchestratorResult(
            request=request,
            address_verification=address_verification,
            flood_zone=flood_zone,
            status="failed",
            execution_time_seconds=execution_time,
            error=error_msg
        )

