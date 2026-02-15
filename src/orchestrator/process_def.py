"""
Process definition for orchestrator workflow.
Defines the sequence of steps for the multi-agent process.
"""

from enum import Enum
from typing import List


class ProcessStep(Enum):
    """Enumeration of process steps."""
    PARSE_INPUT = "parse_input"
    INVOKE_AGENT1 = "invoke_agent1"
    VALIDATE_AGENT1_RESULT = "validate_agent1_result"
    INVOKE_AGENT2 = "invoke_agent2"
    AGGREGATE_RESULTS = "aggregate_results"
    GENERATE_OUTPUTS = "generate_outputs"


class ProcessDefinition:
    """BPMN-like process definition for orchestrator."""
    
    def __init__(self):
        """Initialize process definition with default workflow."""
        self.steps = [
            ProcessStep.PARSE_INPUT,
            ProcessStep.INVOKE_AGENT1,
            ProcessStep.VALIDATE_AGENT1_RESULT,
            ProcessStep.INVOKE_AGENT2,
            ProcessStep.AGGREGATE_RESULTS,
            ProcessStep.GENERATE_OUTPUTS,
        ]
    
    def get_workflow(self) -> List[ProcessStep]:
        """
        Get the ordered list of process steps.
        
        Returns:
            List of ProcessStep enums in execution order
        """
        return self.steps.copy()
    
    def get_step_name(self, step: ProcessStep) -> str:
        """
        Get human-readable name for a process step.
        
        Args:
            step: ProcessStep enum
            
        Returns:
            Human-readable step name
        """
        return step.value.replace("_", " ").title()
    
    def can_skip_step(self, step: ProcessStep) -> bool:
        """
        Determine if a step can be skipped based on conditions.
        
        Args:
            step: ProcessStep enum
            
        Returns:
            True if step can be conditionally skipped
        """
        # Some steps might be skippable based on configuration
        # For now, all steps are required
        return False
    
    def get_retry_policy(self, step: ProcessStep) -> dict:
        """
        Get retry policy for a specific step.
        
        Args:
            step: ProcessStep enum
            
        Returns:
            Dictionary with retry configuration:
            {
                "max_retries": int,
                "retry_delay": float (seconds),
                "retry_on": List[str] (error types to retry on)
            }
        """
        # Default retry policy
        default_policy = {
            "max_retries": 2,
            "retry_delay": 1.0,
            "retry_on": ["ConnectionError", "TimeoutError", "HTTPError"]
        }
        
        # Custom policies per step
        policies = {
            ProcessStep.INVOKE_AGENT1: {
                "max_retries": 3,
                "retry_delay": 2.0,
                "retry_on": ["ConnectionError", "TimeoutError", "HTTPError", "RuntimeError"]
            },
            ProcessStep.INVOKE_AGENT2: {
                "max_retries": 3,
                "retry_delay": 2.0,
                "retry_on": ["ConnectionError", "TimeoutError", "HTTPError"]
            }
        }
        
        return policies.get(step, default_policy)

