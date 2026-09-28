import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main


class FakeRouter:
    def predict(self, state, questions, model=None):
        assert state["message"]
        assert "decision" in questions
        return {
            "model": "laya-rl-agent",
            "answers": {"decision": {"choice": "yes", "probabilities": {"yes": 0.8, "no": 0.1, "unknown": 0.1},
                                      "confidence": 0.7, "answer_confidence": 0.8}},
            "usage": {"input_tokens": 12, "output_tokens": 0},
            "routing": {"model": "english"},
        }


class BrokenRouter:
    def predict(self, state, questions, model=None):
        raise RuntimeError("checkpoint missing")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db_patch = patch.object(main, "DB_PATH", root / "history.db")
        self.config_patch = patch.object(main, "CONFIG_PATH", root / "config.json")
        self.db_patch.start(); self.config_patch.start()
        self.addCleanup(self.db_patch.stop); self.addCleanup(self.config_patch.stop)
        main.CONFIG_PATH.write_text(json.dumps(main.DEFAULT_CONFIG), encoding="utf-8")
        main.initialize()

    def test_config_validation_and_save(self):
        updated = json.loads(json.dumps(main.DEFAULT_CONFIG))
        updated["questions"]["decision"]["instructions"] = "Is the request approved?"
        self.assertEqual(main.put_config(updated)["questions"]["decision"]["instructions"], "Is the request approved?")
        self.assertEqual(main.get_config(), updated)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0], 1)
        with self.assertRaises(HTTPException) as caught:
            main.put_config({"questions": {"bad": {"type": "choice", "criteria": {}}}})
        self.assertEqual(caught.exception.status_code, 400)

    def test_malformed_config_json_returns_400(self):
        with TestClient(main.app) as client:
            response = client.put("/api/config", content="{", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid JSON", response.json()["detail"])

    def test_classify_persists_history_and_dashboard(self):
        with patch.object(main, "get_router", return_value=FakeRouter()):
            first = main.classify(main.ClassifyRequest(message="First request"))
            main.classify(main.ClassifyRequest(message="Second request", conversationId=first["conversationId"]))
        chat = main.get_conversation(first["conversationId"])
        self.assertEqual(len(chat["messages"]), 4)
        self.assertEqual(chat["messages"][1]["response"]["choice"], "yes")
        self.assertEqual(chat["messages"][1]["response"]["config"], main.DEFAULT_CONFIG)
        self.assertEqual(len(main.list_conversations()), 1)
        dashboard = main.dashboard()
        self.assertEqual(dashboard["stats"]["total_requests"], 2)
        self.assertEqual(dashboard["stats"]["input_tokens"], 24)
        self.assertEqual(dashboard["choices"], [{"choice": "yes", "count": 2}])

    def test_failed_inference_is_recorded(self):
        with patch.object(main, "get_router", return_value=BrokenRouter()):
            with self.assertRaises(HTTPException) as caught:
                main.classify(main.ClassifyRequest(message="Trigger failure"))
        self.assertEqual(caught.exception.status_code, 503)
        detail = caught.exception.detail
        self.assertIn("checkpoint missing", detail["message"])
        chat = main.get_conversation(detail["conversationId"])
        self.assertEqual(chat["messages"][1]["response"]["status"], "error")
        self.assertEqual(main.dashboard()["stats"]["failed_requests"], 1)


if __name__ == "__main__":
    unittest.main()
