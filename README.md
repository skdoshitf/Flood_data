
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

### Quick Start

```bash
# Natural language query
python orchestrator_main.py --query "Check flood zone for 1137 Barnett street, johnstown, pa"

# Structured address
python orchestrator_main.py --address "1137 Barnett street, johnstown, pa"

# Parcel ID
python orchestrator_main.py --parcel-id "766620-1420" --region "King County, Washington"
```

📋 **See [AGENT_ARCHITECTURE_PLAN.md](AGENT_ARCHITECTURE_PLAN.md) for the complete architecture plan.**  
📋 **See [PHASE1_IMPLEMENTATION_SUMMARY.md](PHASE1_IMPLEMENTATION_SUMMARY.md) for Phase 1 details.**  
📋 **See [PHASE2_IMPLEMENTATION_SUMMARY.md](PHASE2_IMPLEMENTATION_SUMMARY.md) for Phase 2 details.**

## Next Steps
- Review and implement the multi-agent architecture plan
- Replace placeholders in `state_machine.py` with actual integrations (county portal, ROD, GIS, queues).
- Connect to a real DMN engine (e.g., Camunda) or keep these Python DMN-equivalents for unit tests.
- Add message events to loop back when **customer info** arrives.
- Persist decision/evidence logs for audit and learning.
