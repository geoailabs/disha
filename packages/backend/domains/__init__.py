"""
7+1 Domain Hub Architecture for Disha.

Exports BaseDomainHub, ToolResult, and all domain hubs:
- SpatialHub (Spatial geometry, boundaries, and polygon registry)
- MobilityHub (Transit, network routing, ITS, and OD demand)
- EnvironmentHub (GEE, weather, emissions, and terrain/solar)
- PlanningHub (Zoning, land budgeting, and plan digitization)
- DemographicsHub (Population, cohorts, and employment demand)
- PlacesHub (Google Places and Overture building footprints)
- ScenariosHub (Scenario alternatives and MCDA comparison)
- UtilityHub (Search, geocoding, distance, and artifacts)
"""

from domains.demographics_hub import DemographicsHub
from domains.environment_hub import EnvironmentHub
from domains.mobility_hub import MobilityHub
from domains.places_hub import PlacesHub
from domains.planning_hub import PlanningHub
from domains.protocol import BaseDomainHub, ToolResult
from domains.scenarios_hub import ScenariosHub
from domains.spatial_hub import SpatialHub
from domains.utility_hub import UtilityHub

__all__ = [
    "BaseDomainHub",
    "ToolResult",
    "SpatialHub",
    "MobilityHub",
    "EnvironmentHub",
    "PlanningHub",
    "DemographicsHub",
    "PlacesHub",
    "ScenariosHub",
    "UtilityHub",
]
