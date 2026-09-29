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
        assert model == "english"
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


class FakeHttpResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


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

    def test_config_migration_and_crud(self):
        configs = main.list_configs()
        self.assertEqual(len(configs), 1)
        self.assertTrue(configs[0]["isActive"])
        self.assertEqual(configs[0]["defaultModelId"], "laya:english")
        updated = json.loads(json.dumps(main.DEFAULT_CONFIG))
        updated["questions"]["decision"]["instructions"] = "Is the request approved?"
        saved = main.update_config_profile(configs[0]["id"], main.ConfigProfileRequest(
            name="Approval", config=updated, defaultModelId="ollama:qwen3.5:4b", isActive=True,
        ))
        self.assertEqual(saved["name"], "Approval")
        self.assertEqual(saved["defaultModelId"], "ollama:qwen3.5:4b")
        self.assertEqual(main.get_config()["questions"]["decision"]["instructions"], "Is the request approved?")
        created = main.create_config_profile(main.ConfigProfileRequest(
            name="Copy", config=main.DEFAULT_CONFIG, defaultModelId="laya:english", isActive=False,
        ))
        self.assertEqual(len(main.list_configs()), 2)
        self.assertFalse(created["isActive"])
        self.assertEqual(main.delete_config_profile(created["id"]), {"ok": True})
        self.assertEqual(len(main.list_configs()), 1)
        with self.assertRaises(HTTPException) as active_delete:
            main.delete_config_profile(saved["id"])
        self.assertEqual(active_delete.exception.status_code, 400)
        with self.assertRaises(HTTPException) as caught:
            main.create_config_profile(main.ConfigProfileRequest(
                name="Bad", config=main.DEFAULT_CONFIG, defaultModelId="missing:model", isActive=False,
            ))
        self.assertEqual(caught.exception.status_code, 400)

    def test_malformed_config_json_returns_400(self):
        with TestClient(main.app) as client:
            response = client.put("/api/config", content="{", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid JSON", response.json()["detail"])

    def test_classify_uses_active_config_and_default_model(self):
        with patch.object(main, "get_router", return_value=FakeRouter()):
            first = main.classify(main.ClassifyRequest(message="First request"))
            main.classify(main.ClassifyRequest(message="Second request", conversationId=first["conversationId"]))
        chat = main.get_conversation(first["conversationId"])
        self.assertEqual(len(chat["messages"]), 4)
        response = chat["messages"][1]["response"]
        self.assertEqual(response["choice"], "yes")
        self.assertEqual(response["config"], main.DEFAULT_CONFIG)
        self.assertEqual(response["modelId"], "laya:english")
        self.assertEqual(response["provider"], "laya")
        dashboard = main.dashboard()
        self.assertEqual(dashboard["stats"]["total_requests"], 2)
        self.assertEqual(dashboard["stats"]["input_tokens"], 24)
        self.assertEqual(dashboard["choices"], [{"choice": "yes", "count": 2}])
        self.assertEqual(dashboard["models"][0]["id"], "laya:english")

    def test_classify_accepts_explicit_ollama_model(self):
        raw = {
            "message": {"content": json.dumps({
                "choice": "REQUEST_DISCOUNT", "confidence": 0.91,
                "probabilities": {"REQUEST_DISCOUNT": 0.91}, "reason": "too expensive",
            })},
            "prompt_eval_count": 100,
            "eval_count": 20,
        }
        with patch.object(main.urllib.request, "urlopen", return_value=FakeHttpResponse(raw)):
            result = main.classify(main.ClassifyRequest(message="It is too expensive", modelId="ollama:qwen3.5:4b"))
        response = result["response"]
        self.assertEqual(response["choice"], "REQUEST_DISCOUNT")
        self.assertEqual(response["provider"], "ollama")
        self.assertEqual(response["modelId"], "ollama:qwen3.5:4b")
        self.assertEqual(response["inputTokens"], 100)

    def test_ollama_errors_are_recorded(self):
        raw = {"message": {"content": '{"choice":"NOT_ALLOWED","confidence":0.8}'}}
        with patch.object(main.urllib.request, "urlopen", return_value=FakeHttpResponse(raw)):
            with self.assertRaises(HTTPException) as caught:
                main.classify(main.ClassifyRequest(message="Bad result", modelId="ollama:qwen3.5:4b"))
        self.assertEqual(caught.exception.status_code, 503)
        detail = caught.exception.detail
        self.assertIn("unknown choice", detail["message"])
        chat = main.get_conversation(detail["conversationId"])
        self.assertEqual(chat["messages"][1]["response"]["status"], "error")
        self.assertEqual(main.dashboard()["stats"]["failed_requests"], 1)

    def test_failed_laya_inference_is_recorded(self):
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
