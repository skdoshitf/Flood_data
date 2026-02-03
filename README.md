
# Base State Machine Implementation (BPMN-aligned)

This is a minimal, runnable Python implementation that mirrors your BPMN for **Address Verification** using a simple **state machine**.

## Structure
```
src/
  models.py              # Address & Evidence dataclasses
  dmn/
    classify.py          # DMN-equivalent: address classification
    confidence.py        # DMN-equivalent: confidence scoring & routing
  state_machine.py       # Orchestrates states matching BPMN steps
main.py                  # Demo scenarios
```

## Run
```bash
python3 src/main.py
```
You should see logs for three scenarios: Standard, Incomplete → research → routing, and Non-standard.

## Next steps
- Replace placeholders in `state_machine.py` with actual integrations (county portal, ROD, GIS, queues).
- Connect to a real DMN engine (e.g., Camunda) or keep these Python DMN-equivalents for unit tests.
- Add message events to loop back when **customer info** arrives.
- Persist decision/evidence logs for audit and learning.
