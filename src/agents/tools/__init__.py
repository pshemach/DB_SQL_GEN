from src.agents.tools.adhoc_query import adhoc_query
from src.agents.tools.ask_user import ask_user
from src.agents.tools.compare import compare
from src.agents.tools.diagnose_gap import diagnose_gap
from src.agents.tools.forecast import forecast
from src.agents.tools.get_kpi import get_kpi
from src.agents.tools.rank_actions import rank_actions
from src.agents.tools.resolve_entity import resolve_entity
from src.agents.tools.segment import segment
from src.agents.tools.simulate import simulate
from src.agents.tools.transform_results import transform_results

ANALYST_TOOLS = [
    resolve_entity,
    get_kpi,
    diagnose_gap,
    compare,
    forecast,
    segment,
    simulate,
    rank_actions,
    transform_results,
    adhoc_query,
    ask_user,
]

__all__ = ["ANALYST_TOOLS"]
