import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools.spatial_registry import SpatialRegistry, _normalize_name


class SpatialRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = SpatialRegistry()

    def test_normalize_name(self):
        self.assertEqual(_normalize_name("Sector 17, Chandigarh Boundary"), "sector 17 chandigarh")
        self.assertEqual(_normalize_name("Central Park Polygon"), "central park")
        self.assertEqual(_normalize_name("Commercial Area"), "commercial")

    def test_register_and_metrics(self):
        # A 1km x 1km square around (0, 0)
        poly = {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]
            ],
        }
        res = self.registry.register_or_get("Test Square", poly, source="user_draw")
        self.assertEqual(res["status"], "created")
        self.assertFalse(res["is_duplicate"])
        self.assertEqual(res["layer_name"], "Test Square")

        p = self.registry.get_polygon("Test Square")
        self.assertIsNotNone(p)
        self.assertGreater(p.area_hectares, 0)
        self.assertGreater(p.area_km2, 0)
        self.assertAlmostEqual(p.centroid["lng"], 0.005, places=3)
        self.assertAlmostEqual(p.centroid["lat"], 0.005, places=3)

    def test_deduplication_by_spatial_iou(self):
        # Base polygon
        poly1 = {
            "type": "Polygon",
            "coordinates": [
                [[10.0, 10.0], [10.01, 10.0], [10.01, 10.01], [10.0, 10.01], [10.0, 10.0]]
            ],
        }
        res1 = self.registry.register_or_get("Parcel Alpha", poly1, source="ai_draw")
        self.assertEqual(res1["status"], "created")

        # Almost identical polygon (95%+ overlap) with different name
        poly2 = {
            "type": "Polygon",
            "coordinates": [
                [[10.0, 10.0], [10.0101, 10.0], [10.0101, 10.0101], [10.0, 10.0101], [10.0, 10.0]]
            ],
        }
        res2 = self.registry.register_or_get("New Parcel Attempt", poly2, source="osm_boundary")
        self.assertEqual(res2["status"], "existing")
        self.assertTrue(res2["is_duplicate"])
        self.assertEqual(res2["layer_name"], "Parcel Alpha")
        self.assertGreaterEqual(res2["iou"], 0.90)

    def test_deduplication_by_name(self):
        poly1 = {
            "type": "Polygon",
            "coordinates": [
                [[20.0, 20.0], [20.01, 20.0], [20.01, 20.01], [20.0, 20.01], [20.0, 20.0]]
            ],
        }
        self.registry.register_or_get("Downtown Sector", poly1)

        # Same normalized name
        res = self.registry.register_or_get("Downtown Sector Boundary", poly1)
        self.assertEqual(res["status"], "existing")
        self.assertTrue(res["is_duplicate"])
        self.assertEqual(res["layer_name"], "Downtown Sector")

    def test_distinct_polygons_not_deduplicated(self):
        poly1 = {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]
            ],
        }
        poly2 = {
            "type": "Polygon",
            "coordinates": [
                [[50.0, 50.0], [50.01, 50.0], [50.01, 50.01], [50.0, 50.01], [50.0, 50.0]]
            ],
        }
        res1 = self.registry.register_or_get("Zone A", poly1)
        res2 = self.registry.register_or_get("Zone B", poly2)
        self.assertEqual(res1["status"], "created")
        self.assertEqual(res2["status"], "created")
        self.assertEqual(len(self.registry.list_polygons()), 2)

    def test_check_overlap_and_land_budget(self):
        poly1 = {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [0.02, 0.0], [0.02, 0.02], [0.0, 0.02], [0.0, 0.0]]
            ],
        }
        self.registry.register_or_get("Residential Zone", poly1, properties={"zone_code": "R1"})

        # Partially overlapping query polygon
        query_poly = {
            "type": "Polygon",
            "coordinates": [
                [[0.01, 0.01], [0.03, 0.01], [0.03, 0.03], [0.01, 0.03], [0.01, 0.01]]
            ],
        }
        overlaps = self.registry.check_overlap(query_poly)
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["name"], "Residential Zone")
        self.assertGreater(overlaps[0]["overlap_pct"], 0)

        # Land budget
        budget = self.registry.calculate_land_budget()
        self.assertEqual(budget["total_polygons"], 1)
        self.assertIn("R1", budget["breakdown"])
        self.assertEqual(budget["breakdown"]["R1"]["share_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
