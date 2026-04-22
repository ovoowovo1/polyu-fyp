import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


class MainAppTests(unittest.TestCase):
    def test_default_static_dir_points_to_backend_static_folder(self):
        static_dir = Path(main._default_static_dir()).resolve()
        self.assertEqual(static_dir.parts[-3:], ("backend", "RAG_python-quiz", "static"))

    def test_create_startup_handler_calls_vector_index_setup(self):
        with patch("main.pg_service.setup_vector_index") as setup_vector_index:
            handler = main._create_startup_handler()
            handler()

        setup_vector_index.assert_called_once_with()

    def test_create_app_mounts_static_and_registers_startup_event(self):
        settings = SimpleNamespace(cors_origins=["http://localhost:5173"], port=3000)
        with tempfile.TemporaryDirectory() as tmpdir:
            app = main.create_app(settings=settings, static_dir=tmpdir)

        routes = {route.path for route in app.routes}
        self.assertIn("/files", routes)
        self.assertNotIn("/neo4j/files", routes)
        self.assertIn("/static", routes)
        self.assertTrue(any(handler.__name__ == "on_startup" for handler in app.router.on_startup))

    def test_main_entrypoint_runs_uvicorn_with_expected_host_and_port(self):
        settings = SimpleNamespace(cors_origins=["*"], port=4321)
        module_path = Path(main.__file__)

        with patch("app.config.get_settings", return_value=settings), patch("uvicorn.run") as uvicorn_run:
            runpy.run_path(str(module_path), run_name="__main__")

        uvicorn_run.assert_called_once_with("main:app", host="0.0.0.0", port=4321, reload=True)
