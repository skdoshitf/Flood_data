# Flood Data - Address Verification & Flood Zone Determination

This project implements a multi-agent system for **Address Verification** and **Flood Zone Determination** using BPMN-aligned state machines and spatial analysis.

## Current Implementation

### Base State Machine (BPMN-aligned)
A minimal, runnable Python implementation that mirrors BPMN for **Address Verification** using a simple state machine.

### Structure
```
src/
  models.py              # Address & Evidence dataclasses
  dmn/
    classify.py          # DMN-equivalent: address classification
    confidence.py        # DMN-equivalent: confidence scoring & routing
  state_machine.py       # Orchestrates states matching BPMN steps
main.py                  # Demo scenarios
Parcel_search_flood_zone.py  # Flood zone determination script
```

### Run Current Implementation
```bash
# Address verification demo
python3 main.py --scenario standard

# Flood zone determination (standalone)
python3 Parcel_search_flood_zone.py
```

## Multi-Agent Architecture ✅

A multi-agent system that combines address verification with flood zone determination:

- **Agent 1**: Address Verification & Polygon Extraction (ReportAll API) ✅
- **Agent 2**: Flood Zone Determination & LOMA Detection (FEMA APIs) ✅
- **Orchestrator**: Coordinates agents, handles natural language queries ✅
- **Caching Layer**: Reduces API calls and improves performance ✅
- **Web API**: REST API for integration ✅
- **Configuration Management**: Centralized config with file/env support ✅

### Quick Start

#### Command Line
```bash
# Natural language query
python orchestrator_main.py --query "Check flood zone for 1137 Barnett street, johnstown, pa"

# Structured address
python orchestrator_main.py --address "1137 Barnett street, johnstown, pa"

# Parcel ID
python orchestrator_main.py --parcel-id "766620-1420" --region "King County, Washington"
```

#### Web API
```bash
# Start API server
python api_server.py

# Query via API
curl -X POST http://localhost:5000/api/v1/flood-zone \
  -H "Content-Type: application/json" \
  -d '{"query": "Check flood zone for 1137 Barnett street, johnstown, pa"}'
```

### Configuration

Create `config.json` from `config.example.json` or use environment variables:
```bash
export REPORTALL_CLIENT_KEY="your_key"
export CACHE_ENABLED="true"
export CACHE_TTL="3600"
```

### Testing

Run all tests:
```bash
python -m pytest tests/ -v
```

## Documentation

📋 **See [PHASE1_IMPLEMENTATION_SUMMARY.md](PHASE1_IMPLEMENTATION_SUMMARY.md) for Phase 1 details.**  
📋 **See [PHASE2_IMPLEMENTATION_SUMMARY.md](PHASE2_IMPLEMENTATION_SUMMARY.md) for Phase 2 details.**  
📋 **See [PHASE3_IMPLEMENTATION_SUMMARY.md](PHASE3_IMPLEMENTATION_SUMMARY.md) for Phase 3 details.**

## Next Steps
- Replace placeholders in `state_machine.py` with actual integrations (county portal, ROD, GIS, queues).
- Connect to a real DMN engine (e.g., Camunda) or keep these Python DMN-equivalents for unit tests.
- Add message events to loop back when **customer info** arrives.
- Persist decision/evidence logs for audit and learning.
