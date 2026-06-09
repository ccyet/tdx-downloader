from __future__ import annotations

from fastapi import FastAPI

from .catalog import register_catalog_routes
from .config import register_config_routes
from .download import register_download_routes
from .health import register_health_routes
from .native import register_native_routes
from .research_cross_section import register_research_cross_section_routes
from .research_history import register_research_history_routes
from .research_review import register_research_review_routes
from .review_ai import register_review_ai_routes
from .tasks import register_tasks_routes
from .trading_calendar import register_trading_calendar_routes


def register_routes(app: FastAPI) -> None:
    register_health_routes(app)
    register_trading_calendar_routes(app)
    register_config_routes(app)
    register_catalog_routes(app)
    register_download_routes(app)
    register_research_history_routes(app)
    register_research_cross_section_routes(app)
    register_research_review_routes(app)
    register_review_ai_routes(app)
    register_native_routes(app)
    register_tasks_routes(app)
