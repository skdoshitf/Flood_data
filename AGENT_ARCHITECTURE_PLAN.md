# Multi-Agent System Architecture Plan
## Flood Zone Determination with Address Verification

## Overview

This document outlines the architecture for a multi-agent system that combines:
1. **Address Verification** with polygon extraction (Agent 1)
2. **Flood Zone Determination** with LOMA detection (Agent 2)
3. **Orchestrator** that coordinates agents and handles natural language queries

---

## 1. Architecture Components

### 1.1 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                             │
│  - Natural Language Query Parser                            │
│  - Process Definition (BPMN-like workflow)                │
│  - Agent Coordination & State Management                    │
│  - Result Aggregation                                       │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌──────────────────┐              ┌──────────────────┐
│   AGENT 1        │              │   AGENT 2        │
│ Address          │              │ Flood Zone       │
│ Verification     │              │ Determination    │
│                  │              │                  │
│ - ReportAll API  │              │ - FEMA NFHL API  │
│ - Polygon Extract│              │ - LOMA Detection │
│ - Address Classify│             │ - Spatial Overlay│
└──────────────────┘              └──────────────────┘
```

### 1.2 Component Responsibilities

#### **Orchestrator**
- **Input Processing**: Parse natural language queries or structured parameters
- **Workflow Management**: Define and execute process flow (sequential/parallel)
- **Agent Invocation**: Coordinate Agent 1 → Agent 2 execution
- **Data Transformation**: Convert outputs between agents
- **Error Handling**: Retry logic, fallbacks, error propagation
- **Result Aggregation**: Combine results from both agents

#### **Agent 1: Address Verification & Polygon Extraction**
- **Address Classification**: Use existing DMN classification logic
- **ReportAll API Integration**: Query by address or parcel ID
- **Polygon Extraction**: Extract WKT geometry from ReportAll response
- **Address Validation**: Verify address completeness and confidence
- **Output**: Validated address + parcel geometry (WKT)

#### **Agent 2: Flood Zone Determination & LOMA**
- **Flood Zone Query**: Query FEMA NFHL flood zones using parcel geometry
- **Spatial Overlay**: Intersect parcel with flood zones
- **LOMA Detection**: Query and rank nearby LOMA features
- **Building Analysis**: Analyze building footprints if available
- **Output**: Flood zone classification + LOMA presence + overlap details

---

## 2. Data Models

### 2.1 Orchestrator Input

```python
@dataclass
class OrchestratorRequest:
    """Input to orchestrator - supports both structured and natural language"""
    # Natural language query
    natural_language_query: Optional[str] = None
    
    # Structured parameters (alternative to NL)
    address: Optional[str] = None
    parcel_id: Optional[str] = None
    region: Optional[str] = None
    
    # Configuration
    include_loma: bool = True
    include_buildings: bool = True
    use_wfs: bool = False
```

### 2.2 Agent 1 Output

```python
@dataclass
class AddressVerificationResult:
    """Output from Agent 1"""
    # Address details
    address: Address  # from src/models.py
    address_type: str  # "Standard", "Incomplete", "Non-standard"
    confidence: float  # 0.0-1.0
    routing: str  # "Auto", "HITL", etc.
    
    # Geometry
    parcel_wkt: str  # WKT geometry of parcel
    parcel_centroid: Tuple[float, float]  # (lon, lat)
    parcel_record: Dict[str, Any]  # Full ReportAll record
    
    # Buildings (if available)
    buildings: List[Dict[str, Any]]  # Building footprints with geometry
    
    # Metadata
    verification_status: str  # "verified", "incomplete", "failed"
    evidence: Evidence  # from src/models.py
    logs: List[str]
```

### 2.3 Agent 2 Output

```python
@dataclass
class FloodZoneResult:
    """Output from Agent 2"""
    # Flood zone classification
    flood_zones: List[Dict[str, Any]]  # Per-zone overlaps with attributes
    union_overlap_wkt: Optional[str]  # Union of all overlaps
    
    # LOMA information
    loma_features: List[Dict[str, Any]]  # Ranked by distance
    nearest_loma_distance_m: Optional[float]
    
    # Building analysis
    building_overlaps: List[Dict[str, Any]]  # Per-building flood zone overlaps
    
    # Summary
    in_flood_zone: bool
    primary_zone: Optional[str]  # e.g., "AE", "X"
    zone_subtype: Optional[str]
    
    # Metadata
    query_bbox: Tuple[float, float, float, float]
    nfhl_features_count: int
    logs: List[str]
```

### 2.4 Orchestrator Output

```python
@dataclass
class OrchestratorResult:
    """Final aggregated result"""
    # Request info
    request: OrchestratorRequest
    
    # Agent results
    address_verification: AddressVerificationResult
    flood_zone: FloodZoneResult
    
    # Summary
    status: str  # "success", "partial", "failed"
    execution_time_seconds: float
    
    # Files generated
    output_files: Dict[str, str]  # filename -> path
```

---

## 3. Agent Interfaces

### 3.1 Agent Base Interface

```python
from abc import ABC, abstractmethod
from typing import Protocol

class Agent(Protocol):
    """Base protocol for all agents"""
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent logic and return result"""
        ...
    
    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """Validate input before execution"""
        ...
```

### 3.2 Agent 1: AddressVerificationAgent

```python
class AddressVerificationAgent:
    """Agent 1: Address verification and polygon extraction"""
    
    def __init__(self, reportall_client_key: str):
        self.client_key = reportall_client_key
        self.state_machine = None  # AddressVerificationSM instance
    
    def execute(self, request: Dict[str, Any]) -> AddressVerificationResult:
        """
        Input: {
            "address": str or Address object,
            "parcel_id": Optional[str],
            "region": Optional[str],
            "mode": "address" | "parcel_id"
        }
        
        Process:
        1. Parse/validate input address
        2. Run address classification (DMN)
        3. Query ReportAll API
        4. Extract parcel geometry
        5. Run address verification state machine
        6. Return result with geometry
        """
        ...
```

### 3.3 Agent 2: FloodZoneAgent

```python
class FloodZoneAgent:
    """Agent 2: Flood zone determination and LOMA detection"""
    
    def __init__(self, use_wfs: bool = False):
        self.use_wfs = use_wfs
    
    def execute(self, request: Dict[str, Any]) -> FloodZoneResult:
        """
        Input: {
            "parcel_wkt": str,
            "parcel_centroid": Tuple[float, float],
            "buildings": List[Dict],
            "include_loma": bool,
            "loma_radius_miles": float
        }
        
        Process:
        1. Build AOI bbox from parcel geometry
        2. Query FEMA NFHL flood zones (WFS or REST)
        3. Perform spatial overlay (intersection)
        4. Query LOMA features if requested
        5. Analyze building footprints if available
        6. Return flood zone classification + LOMA
        """
        ...
```

---

## 4. Orchestrator Design

### 4.1 Natural Language Query Parser

```python
class NLQueryParser:
    """Parse natural language queries into structured parameters"""
    
    def parse(self, query: str) -> Dict[str, Any]:
        """
        Examples:
        - "Check flood zone for 1137 Barnett street, johnstown, pa"
        - "What's the flood risk at parcel 766620-1420 in King County?"
        - "Verify address and get flood zone info for 100 Main St, Seattle, WA"
        
        Returns structured dict with:
        - address/parcel_id
        - region
        - flags (include_loma, etc.)
        """
        # Use regex + keyword matching for MVP
        # Can be enhanced with LLM/NLP later
        ...
```

### 4.2 Process Definition

```python
class ProcessDefinition:
    """BPMN-like process definition for orchestrator"""
    
    STEPS = [
        "parse_input",
        "invoke_agent1",  # Address verification
        "validate_agent1_result",
        "invoke_agent2",  # Flood zone determination
        "aggregate_results",
        "generate_outputs"
    ]
    
    def get_workflow(self) -> List[str]:
        """Return ordered list of steps"""
        return self.STEPS
```

### 4.3 Orchestrator Implementation

```python
class FloodZoneOrchestrator:
    """Main orchestrator coordinating agents"""
    
    def __init__(self, 
                 reportall_key: str,
                 use_wfs: bool = False):
        self.agent1 = AddressVerificationAgent(reportall_key)
        self.agent2 = FloodZoneAgent(use_wfs)
        self.nl_parser = NLQueryParser()
        self.process = ProcessDefinition()
    
    def execute(self, request: OrchestratorRequest) -> OrchestratorResult:
        """
        Main execution flow:
        1. Parse input (NL or structured)
        2. Invoke Agent 1 → get address + geometry
        3. Invoke Agent 2 → get flood zone + LOMA
        4. Aggregate results
        5. Generate output files
        6. Return combined result
        """
        start_time = time.time()
        
        # Step 1: Parse input
        params = self._parse_input(request)
        
        # Step 2: Agent 1 - Address Verification
        agent1_result = self.agent1.execute(params)
        
        # Step 3: Validate Agent 1 result
        if not agent1_result.verification_status == "verified":
            # Handle incomplete/failed cases
            ...
        
        # Step 4: Agent 2 - Flood Zone Determination
        agent2_input = {
            "parcel_wkt": agent1_result.parcel_wkt,
            "parcel_centroid": agent1_result.parcel_centroid,
            "buildings": agent1_result.buildings,
            "include_loma": request.include_loma
        }
        agent2_result = self.agent2.execute(agent2_input)
        
        # Step 5: Aggregate & generate outputs
        result = self._aggregate_results(request, agent1_result, agent2_result)
        result.execution_time_seconds = time.time() - start_time
        
        return result
```

---

## 5. File Structure

```
Flood_data/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # Agent base protocol
│   │   ├── address_agent.py     # Agent 1 implementation
│   │   └── floodzone_agent.py   # Agent 2 implementation
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # Main orchestrator
│   │   ├── nl_parser.py         # Natural language parser
│   │   └── process_def.py       # Process definition
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── agent_models.py      # Agent input/output models
│   │   └── orchestrator_models.py
│   │
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── reportall_client.py  # ReportAll API wrapper
│   │   └── fema_client.py       # FEMA API wrapper
│   │
│   ├── dmn/                      # Existing (keep as-is)
│   ├── models.py                 # Existing (keep as-is)
│   └── state_machine.py          # Existing (keep as-is)
│
├── Parcel_search_flood_zone.py   # Reference (can be refactored)
├── main.py                       # Existing (keep for backward compat)
├── orchestrator_main.py          # New: Orchestrator entry point
└── AGENT_ARCHITECTURE_PLAN.md    # This document
```

---

## 6. Implementation Phases

### Phase 1: Core Agent Structure
- [ ] Create agent base protocol
- [ ] Implement Agent 1 (address verification + ReportAll)
- [ ] Implement Agent 2 (flood zone + LOMA)
- [ ] Create data models for agent communication
- [ ] Unit tests for each agent

### Phase 2: Orchestrator Foundation
- [ ] Create orchestrator class
- [ ] Implement process definition
- [ ] Basic agent coordination (sequential execution)
- [ ] Error handling and retry logic
- [ ] Integration tests

### Phase 3: Natural Language Support
- [ ] Implement NL query parser (regex-based MVP)
- [ ] Support common query patterns
- [ ] Integration with orchestrator
- [ ] Optional: LLM-based parsing enhancement

### Phase 4: Integration & Refinement
- [ ] Refactor Parcel_search_flood_zone.py logic into Agent 2
- [ ] Integrate existing state machine into Agent 1
- [ ] Output file generation
- [ ] Logging and observability
- [ ] Documentation

### Phase 5: Enhancement (Optional)
- [ ] Parallel agent execution (if applicable)
- [ ] Caching layer for API calls
- [ ] Advanced NL parsing with LLM
- [ ] Web API wrapper
- [ ] Dashboard/UI

---

## 7. Example Usage

### 7.1 Structured Input

```python
from src.orchestrator.orchestrator import FloodZoneOrchestrator
from src.models.orchestrator_models import OrchestratorRequest

orchestrator = FloodZoneOrchestrator(
    reportall_key="Wtn9iKgWVx",
    use_wfs=False
)

request = OrchestratorRequest(
    address="1137 Barnett street, johnstown, pa",
    include_loma=True,
    include_buildings=True
)

result = orchestrator.execute(request)
print(f"Status: {result.status}")
print(f"Flood Zone: {result.flood_zone.primary_zone}")
print(f"LOMA Found: {len(result.flood_zone.loma_features) > 0}")
```

### 7.2 Natural Language Input

```python
request = OrchestratorRequest(
    natural_language_query="Check flood zone for 1137 Barnett street, johnstown, pa"
)

result = orchestrator.execute(request)
```

### 7.3 CLI Usage

```bash
# Structured input
python orchestrator_main.py --address "1137 Barnett street, johnstown, pa"

# Natural language
python orchestrator_main.py --query "What's the flood risk at 1137 Barnett street, johnstown, pa?"

# Parcel ID
python orchestrator_main.py --parcel-id "766620-1420" --region "King County, Washington"
```

---

## 8. Key Design Decisions

### 8.1 Agent Independence
- Agents are independent and can be tested/executed separately
- Clear input/output contracts
- No direct dependencies between agents

### 8.2 Orchestrator as Coordinator
- Orchestrator handles workflow, not business logic
- Agents contain domain-specific logic
- Easy to add new agents or modify workflow

### 8.3 Natural Language Parsing
- Start with simple regex/keyword matching
- Can be enhanced with LLM later without changing agent interfaces
- Fallback to structured input if NL parsing fails

### 8.4 Error Handling
- Each agent handles its own errors
- Orchestrator provides retry and fallback logic
- Graceful degradation (e.g., continue without LOMA if Agent 2 fails)

### 8.5 Backward Compatibility
- Keep existing `Parcel_search_flood_zone.py` as reference
- Existing `main.py` and state machine remain functional
- New orchestrator is additive, not replacement

---

## 9. Next Steps

1. **Review and approve this plan**
2. **Start Phase 1**: Create agent structure and data models
3. **Incremental development**: Build and test each component
4. **Integration**: Connect components and test end-to-end
5. **Documentation**: Update README with new architecture

---

## 10. Questions & Considerations

- **Caching**: Should we cache ReportAll/FEMA API responses?
- **Async**: Should agents execute asynchronously?
- **Persistence**: Should we store results in a database?
- **Monitoring**: What observability/metrics are needed?
- **LLM Integration**: When to add LLM-based NL parsing?

---

**Document Version**: 1.0  
**Last Updated**: 2024  
**Status**: Draft for Review

