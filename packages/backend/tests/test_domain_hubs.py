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

    async def test_edit_artifact_without_image(self):
        # Create test artifact first
        create_res = await self.utility_hub.execute("create_artifact", {
            "title": "Test Doc Without Image",
            "format": "markdown",
            "content": "# Test Doc\n\nInitial text."
        })
        self.assertEqual(create_res.status, "created")
        self.assertEqual(create_res.data.get("status"), "created")
        art_id = create_res.data["id"]

        # Edit without image
        edit_res = await self.utility_hub.execute("edit_artifact", {
            "id": art_id,
            "section_heading": "Test Section",
            "content": "Appended text content."
        })
        self.assertEqual(edit_res.status, "updated")
        self.assertEqual(edit_res.data.get("status"), "updated")
        self.assertEqual(edit_res.data.get("id"), art_id)

    async def test_edit_artifact_with_include_map_figure(self):
        # Create test artifact
        create_res = await self.utility_hub.execute("create_artifact", {
            "title": "Test Doc With Map Figure",
            "format": "markdown",
            "content": "# Test Doc Map\n\nInitial content."
        })
        art_id = create_res.data["id"]

        # Edit with include_map_figure=True and valid map_context
        edit_res = await self.utility_hub.execute("edit_artifact", {
            "id": art_id,
            "section_heading": "Fortis to PEC",
            "content": "Route description text.",
            "include_map_figure": True,
            "figure_caption": "Route Snapshot",
            "_map_context": {
                "center": [76.77, 30.73],
                "zoom": 13,
                "selected_features": []
            }
        })
        self.assertEqual(edit_res.status, "updated")
        self.assertEqual(edit_res.data.get("status"), "updated")
        self.assertEqual(edit_res.data.get("id"), art_id)

    async def test_edit_artifact_image_failure(self):
        # Create test artifact
        create_res = await self.utility_hub.execute("create_artifact", {
            "title": "Test Doc Image Failure",
            "format": "markdown",
            "content": "# Test Doc Fail\n\nInitial."
        })
        art_id = create_res.data["id"]

        # Edit requesting image when map export fails and no context available
        from unittest.mock import patch
        with patch("tools.export_engine.export_artifact_multi_format", side_effect=RuntimeError("Export canvas failed")):
            edit_res = await self.utility_hub.execute("edit_artifact", {
                "id": art_id,
                "section_heading": "Fortis to PEC",
                "content": "Route description text.",
                "include_map_figure": True,
                "_map_context": {"center": [76.77, 30.73]}
            })
            # Must return clean error dictionary rather than crashing with UnboundLocalError
            self.assertEqual(edit_res.status, "success")
            self.assertIn("error", edit_res.data)
            self.assertIn("Map image export failed", edit_res.data["error"])

    async def test_resolve_image_bytes_and_docx_embedding(self):
        import io
        import zipfile
        from PIL import Image
        from tools.export_engine import _resolve_image_bytes, generate_docx_export
        from tools.artifact_store import save_artifact, get_artifacts_dir

        # 1. Create a dummy JPEG image artifact
        img = Image.new("RGB", (300, 200), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        art = save_artifact(
            title="Regression Image",
            artifact_type="analysis",
            format="jpg",
            content="",
            file_bytes=buf.getvalue(),
            file_ext="jpg",
        )
        art_id = art["id"]

        # 2. Test _resolve_image_bytes with forward slash and backslash
        res_slash = _resolve_image_bytes(f"artifacts_store/{art_id}.jpg")
        res_bslash = _resolve_image_bytes(f"artifacts_store\\{art_id}.jpg")
        self.assertIsNotNone(res_slash)
        self.assertIsNotNone(res_bslash)
        self.assertEqual(len(res_slash), len(buf.getvalue()))
        self.assertEqual(len(res_bslash), len(buf.getvalue()))

        # 3. Test generate_docx_export embeds image into word/media/
        md = f"# Report Title\n\n![Figure: Route Snapshot](artifacts_store/{art_id}.jpg)\n*Route Snapshot*\n"
        docx_bytes = generate_docx_export("Report Title", md)
        z = zipfile.ZipFile(io.BytesIO(docx_bytes))
        media_files = [f for f in z.namelist() if f.startswith("word/media/")]
        self.assertTrue(len(media_files) > 0, "Image was not embedded in DOCX word/media/ container.")

        # 4. Test missing and invalid image references return None cleanly
        self.assertIsNone(_resolve_image_bytes(None))
        self.assertIsNone(_resolve_image_bytes(""))
        self.assertIsNone(_resolve_image_bytes("artifacts_store/non_existent_99999.jpg"))

    async def test_edit_image_artifact_rejection(self):
        import io
        from PIL import Image
        from tools.artifact_store import save_artifact

        # Create a JPG artifact
        img_jpg = Image.new("RGB", (100, 100), color=(255, 0, 0))
        buf_jpg = io.BytesIO()
        img_jpg.save(buf_jpg, format="JPEG")
        art_jpg = save_artifact(title="Sample JPG", artifact_type="analysis", format="jpg", content="", file_bytes=buf_jpg.getvalue(), file_ext="jpg")

        # Create a PNG artifact
        img_png = Image.new("RGBA", (100, 100), color=(0, 255, 0, 255))
        buf_png = io.BytesIO()
        img_png.save(buf_png, format="PNG")
        art_png = save_artifact(title="Sample PNG", artifact_type="analysis", format="png", content="", file_bytes=buf_png.getvalue(), file_ext="png")

        # Edit JPG artifact -> expect rejection error
        res_jpg = await self.utility_hub.execute("edit_artifact", {"id": art_jpg["id"], "content": "Text"})
        self.assertIn("error", res_jpg.data)
        self.assertIn("is an image artifact (JPG)", res_jpg.data["error"])

        # Edit PNG artifact -> expect rejection error
        res_png = await self.utility_hub.execute("edit_artifact", {"id": art_png["id"], "content": "Text"})
        self.assertIn("error", res_png.data)
        self.assertIn("is an image artifact (PNG)", res_png.data["error"])

    async def test_map_context_fallback_priority(self):
        # Create test document
        create_res = await self.utility_hub.execute("create_artifact", {
            "title": "Fallback Test Doc",
            "format": "markdown",
            "content": "# Fallback Doc\n"
        })
        art_id = create_res.data["id"]

        # Case A: Neither explicit _map_context nor _last_map_context exists -> clear error
        self.utility_hub.utility_server._last_map_context = {}
        res_no_ctx = await self.utility_hub.execute("edit_artifact", {
            "id": art_id,
            "include_map_figure": True,
            "_map_context": {}
        })
        self.assertIn("error", res_no_ctx.data)
        self.assertIn("No valid map context or active map view was available", res_no_ctx.data["error"])

        # Case B: Empty explicit _map_context, but valid self.utility_hub.utility_server._last_map_context exists -> fallback succeeds
        self.utility_hub.utility_server._last_map_context = {"center": [76.77, 30.73], "zoom": 13}
        res_fallback = await self.utility_hub.execute("edit_artifact", {
            "id": art_id,
            "section_heading": "Map Section",
            "content": "Section text.",
            "include_map_figure": True,
            "_map_context": {}
        })
        self.assertEqual(res_fallback.status, "updated")
        self.assertEqual(res_fallback.data.get("status"), "updated")

    async def test_edit_artifact_with_image_artifact_id(self):
        import io
        import zipfile
        from PIL import Image
        from tools.export_engine import export_artifact_multi_format
        from tools.artifact_store import save_artifact, get_artifacts_dir

        # 1. Create DOCX document artifact
        b_docx, _, _ = export_artifact_multi_format("Doc With Image ID", "# Doc Header\n", "docx")
        doc_art = save_artifact(title="Doc With Image ID", artifact_type="analysis", format="docx", content="# Doc Header\n", file_bytes=b_docx, file_ext="docx")
        doc_id = doc_art["id"]

        # 2. Create JPG image artifact
        img = Image.new("RGB", (200, 200), color=(50, 100, 150))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        img_art = save_artifact(title="Preset Route Image", artifact_type="analysis", format="jpg", content="", file_bytes=buf.getvalue(), file_ext="jpg")
        img_id = img_art["id"]

        # 3. Call edit_artifact with image_artifact_id without map context
        edit_res = await self.utility_hub.execute("edit_artifact", {
            "id": doc_id,
            "section_heading": "Fortis to PEC",
            "content": "Inserting existing image artifact.",
            "image_artifact_id": img_id,
            "_map_context": {}
        })
        self.assertEqual(edit_res.status, "updated")
        self.assertEqual(edit_res.data.get("status"), "updated")

        # 4. Verify image is physically embedded in word/media/
        docx_file = get_artifacts_dir() / f"{doc_id}.docx"
        z = zipfile.ZipFile(docx_file)
        media = [f for f in z.namelist() if f.startswith("word/media/")]
        self.assertTrue(len(media) > 0, "Image was not embedded into DOCX file via image_artifact_id")

    async def test_system_prompt_image_artifact_instruction(self):
        from routers.chat import SYSTEM_PROMPT
        self.assertIn("image_artifact_id", SYSTEM_PROMPT)
        self.assertIn("ALWAYS set `image_artifact_id=37`", SYSTEM_PROMPT)
        self.assertIn("NEVER use `include_map_figure=true` when inserting an existing saved image artifact", SYSTEM_PROMPT)

    async def test_system_prompt_geographic_interpretation_and_document_visualization(self):
        from routers.chat import SYSTEM_PROMPT
        # Rule 30 checks
        self.assertIn("GEOGRAPHIC INTERPRETATION & BOUNDARY CONTAINMENT FILTERING", SYSTEM_PROMPT)
        self.assertIn("resolve the place boundary and spatially filter the requested features to that boundary", SYSTEM_PROMPT)
        self.assertIn("Do NOT substitute a broad search extent, bounding box, viewport, or proximity search", SYSTEM_PROMPT)
        # Rule 31 checks
        self.assertIn("DOCUMENT VISUALIZATION & SECTION HEADING INDEPENDENCE", SYSTEM_PROMPT)
        self.assertIn("generate a separate distinct visual for each heading; do NOT combine or merge them", SYSTEM_PROMPT)
        self.assertIn("Do NOT carry unrelated layers, markers, or visualizations from one requested section into another", SYSTEM_PROMPT)
        # Rule 32 checks (Autonomous Execution)
        self.assertIn("AUTONOMOUS EXECUTION & IMPLICIT AUTHORIZATION", SYSTEM_PROMPT)
        self.assertIn("execute the necessary intermediate operations automatically before producing the requested artifact", SYSTEM_PROMPT)
        self.assertIn("Do NOT stop to ask the user to confirm that you should proceed", SYSTEM_PROMPT)
        self.assertIn("Do NOT ask the user to say 'proceed', 'yes', or otherwise confirm execution", SYSTEM_PROMPT)
        self.assertIn("The user's request to create the final artifact implicitly authorizes the necessary intermediate data retrieval", SYSTEM_PROMPT)
        # Rule 33 checks (Preserve Requested Outputs)
        self.assertIn("PRESERVE REQUESTED OUTPUTS & END-TO-END ARTIFACT COMPILATION", SYSTEM_PROMPT)
        self.assertIn("independently produce EACH requested output and maintain its geographic and semantic scope", SYSTEM_PROMPT)
        self.assertIn("Do NOT combine, omit, substitute, or simplify requested outputs merely for implementation convenience", SYSTEM_PROMPT)
        self.assertIn("generate all required underlying maps, plots, statistics, and other artifacts before assembling the document", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()

