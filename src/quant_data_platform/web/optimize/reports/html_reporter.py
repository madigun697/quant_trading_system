"""HTML report generation for factor weight optimization results."""

from jinja2 import Environment, FileSystemLoader
from datetime import date
from pathlib import Path

REPORT_TEMPLATE_DIR = Path(__file__).parent
REPORT_HTML_TEMPLATE = "optimizer_report.html"


def generate_html_report(
    optimization_result: dict,
    preset_name: str = "Value Quality",
) -> str:
    """
    Generate an HTML report from optimization results.
    
    Args:
        optimization_result: The report dict from FactorOptimizer.generate_report()
        preset_name: Name of the strategy preset
        
    Returns:
        HTML report as a string
    """
    env = Environment(loader=FileSystemLoader(REPORT_TEMPLATE_DIR))
    template = env.get_template(REPORT_HTML_TEMPLATE)
    
    # Extract max sharpe for scaling
    max_sharpe = max(
        (config["sharpe_ratio"] for config in optimization_result.get("ranked_configurations", [])),
        default=0.0,
    )
    
    # Render template
    html = template.render(
        timestamp=optimization_result.get("timestamp", date.today().isoformat()),
        best_config=optimization_result.get("best_config", {}),
        ranked_configurations=optimization_result.get("ranked_configurations", []),
        recommendations=optimization_result.get("recommendations", []),
        warnings=optimization_result.get("warnings", []),
        preset_name=preset_name,
        max_sharpe=max_sharpe,
    )
    
    return html
