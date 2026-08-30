import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from domains import (
    DemographicsHub,
    EnvironmentHub,
    MobilityHub,
    PlacesHub,
    PlanningHub,
    ScenariosHub,
    SpatialHub,
    ToolResult,
    UtilityHub,
)


class DomainHubsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.spatial_hub = SpatialHub()
        self.mobility_hub = MobilityHub()
        self.environment_hub = EnvironmentHub()
        self.planning_hub = PlanningHub()
        self.demographics_hub = DemographicsHub()
        self.places_hub = PlacesHub()
        self.scenarios_hub = ScenariosHub()
        self.utility_hub = UtilityHub()

    def test_hub_instantiations_and_declarations(self):
        hubs = [
            self.spatial_hub,
            self.mobility_hub,
            self.environment_hub,
            self.planning_hub,
            self.demographics_hub,
            self.places_hub,
            self.scenarios_hub,
            self.utility_hub,
        ]

        for hub in hubs:
            with self.subTest(hub=hub.name):
                decls = hub.get_declarations()
                self.assertIsInstance(decls, list)
                self.assertGreater(len(decls), 0)
                for d in decls:
                    self.assertEqual(d["type"], "function")
                    self.assertIn("name", d["function"])
                    self.assertIn("description", d["function"])
                    self.assertIn("parameters", d["function"])

    async def test_spatial_hub_polygon_tools(self):
        # Register a test polygon
        poly = {
            "type": "Polygon",
            "coordinates": [
                [[76.7, 30.7], [76.8, 30.7], [76.8, 30.8], [76.7, 30.8], [76.7, 30.7]]
            ],
        }
        res: ToolResult = await self.spatial_hub.execute("check_polygon_overlap", {"coordinates": poly["coordinates"][0]})
        self.assertIsInstance(res, ToolResult)
        self.assertEqual(res.status, "success")

        # List polygons
        res2: ToolResult = await self.spatial_hub.execute("list_polygons", {})
        self.assertIsInstance(res2, ToolResult)
        self.assertEqual(res2.status, "success")

    async def test_utility_hub_distance_tool_result(self):
        res: ToolResult = await self.utility_hub.execute("measure_distance", {"points": [[0.0, 0.0], [0.01, 0.01]]})
        self.assertIsInstance(res, ToolResult)
        self.assertEqual(res.status, "success")
        self.assertIsNotNone(res.map_action)
        self.assertEqual(res.map_action["action"], "draw_distance_measurement")


if __name__ == "__main__":
    unittest.main()
