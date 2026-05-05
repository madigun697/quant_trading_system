"""CSV report generation for factor weight optimization results."""

import csv
import io


def generate_csv_report(
    optimization_result: dict,
) -> str:
    """
    Generate a CSV report from optimization results.
    
    Args:
        optimization_result: The report dict from FactorOptimizer.generate_report()
        
    Returns:
        CSV report as a string
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Rank",
        "Configuration",
        "Description",
        "Sharpe Ratio",
        "Total Return",
        "Win Rate",
        "Rationale",
    ])
    
    # Rows
    for config in optimization_result.get("ranked_configurations", []):
        writer.writerow([
            config.get("rank"),
            config.get("config_name"),
            config.get("config_description"),
            f"{config.get('sharpe_ratio', 0.0):.3f}",
            f"{config.get('total_return', 0.0):.3f}",
            f"{config.get('win_rate', 0.0):.3f}",
            config.get("rationale", ""),
        ])
    
    # Warnings section
    if optimization_result.get("warnings"):
        writer.writerow([])
        writer.writerow(["Warnings"])
        for warning in optimization_result.get("warnings", []):
            writer.writerow([warning])
    
    return output.getvalue()
