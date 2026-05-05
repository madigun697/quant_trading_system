"""JSON report generation for factor weight optimization results."""

import json
from datetime import date


def generate_json_report(
    optimization_result: dict,
    preset_name: str = "Value Quality",
    indent: int = 2,
) -> str:
    """
    Generate a JSON report from optimization results.
    
    Args:
        optimization_result: The report dict from FactorOptimizer.generate_report()
        preset_name: Name of the strategy preset
        indent: JSON indentation level
        
    Returns:
        JSON report as a string
    """
    report = {
        "preset_name": preset_name,
        "timestamp": date.today().isoformat(),
        "status": optimization_result.get("status"),
        "best_config": optimization_result.get("best_config"),
        "ranked_configurations": optimization_result.get("ranked_configurations", []),
        "recommendations": optimization_result.get("recommendations", []),
        "warnings": optimization_result.get("warnings", []),
    }
    
    return json.dumps(report, indent=indent, default=str)
