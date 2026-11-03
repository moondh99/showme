import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from PIL import Image

SPEC = importlib.util.spec_from_file_location(
    "meta_vision", Path(__file__).resolve().parents[1] / "scripts/meta_vision.py")
vision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision)


def found():
    return {"image_id": "photo-1", "status": "found", "scene_description": "접수대",
            "answer": "오른쪽 트레이입니다.", "evidence": "현장등록 표지",
            "objects": [{"label": "트레이", "box": [500, 200, 900, 700]}],
            "clarification_question": ""}


class GroundingTests(unittest.TestCase):
    def test_invalid_locations_never_render(self):
        for box in [[-1, 0, 10, 10], [0, 0, 1001, 10], [50, 0, 10, 100],
                    [0, 0, 0, 10], [True, 0, 10, 10], [0.1, 0, 10, 10]]:
            with self.subTest(box=box), self.assertRaises(ValueError):
                vision.pixel_box(box, (800, 600))

    def test_missing_or_ambiguous_target_cannot_have_box(self):
        for status in ["not_found", "needs_clarification"]:
            result = found()
            result["status"] = status
            result["clarification_question"] = "어느 트레이인가요?" if status == "needs_clarification" else ""
            with self.subTest(status=status), self.assertRaises(ValueError):
                vision.validate_result(result, "photo-1")

    def test_wrong_image_and_missing_clarification_are_rejected(self):
        with self.assertRaises(ValueError):
            vision.validate_result(found(), "different-image")
        result = found()
        result.update(status="needs_clarification", objects=[])
        with self.assertRaises(ValueError):
            vision.validate_result(result, "photo-1")

    def test_exif_rotation_is_applied_to_sent_and_rendered_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rotated.jpg"
            image = Image.new("RGB", (120, 80), "white")
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            prepared, data = vision.prepare_image(path)
            self.assertEqual(prepared.size, (80, 120))
            self.assertEqual(prepared.getexif().get(274), None)
            overlay = Path(folder) / "overlay.png"
            vision.render_overlay(prepared, found()["objects"], overlay)
            with Image.open(overlay) as rendered:
                self.assertEqual(rendered.size, prepared.size)
                self.assertEqual(rendered.getpixel((40, 40)), (239, 68, 68))

    def test_secrets_and_image_payloads_are_not_saved(self):
        cleaned = vision.redact({"Authorization": "Bearer secret-key", "text":
                                "secret-key data:image/jpeg;base64,ABCDEF"}, "secret-key")
        serialized = json.dumps(cleaned)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("ABCDEF", serialized)

    def test_evaluation_labels_are_not_part_of_model_input(self):
        payload = vision.make_payload(b"jpeg-data", "photo-1", "Where?", "operator note", "model")
        self.assertNotIn("expected", json.dumps(payload))
        self.assertEqual(payload["messages"][1]["content"][1]["image_url"]["url"],
                         "data:image/jpeg;base64,anBlZy1kYXRh")

    def test_successful_transport_still_needs_manual_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "photo.jpg"
            Image.new("RGB", (200, 100), "white").save(path)
            args = type("Args", (), {"image": str(path), "question": "트레이?", "note": "",
                                      "prepare_only": False, "expected_status": "found",
                                      "expected_box": [500, 200, 900, 700]})()
            response = Mock(status_code=200, headers={})
            response.json.return_value = {"model": "test-model", "usage": {"total_tokens": 10},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(found())}}]}
            with patch.object(vision, "RESULTS", Path(folder) / "results"), \
                    patch.object(vision, "settings", return_value=("test-key", "https://api.meta.ai/v1", "test-model")), \
                    patch.object(vision.requests, "post", return_value=response) as post:
                self.assertEqual(vision.run(args), 0)
                self.assertFalse(post.call_args.kwargs["allow_redirects"])
            record = json.loads(next((Path(folder) / "results").glob("*/run.json")).read_text())
            self.assertEqual(record["review"]["verdict"], "pending")
            self.assertEqual(record["box_iou"], 1.0)

    def test_api_error_is_recorded_without_secret_leak(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "photo.jpg"
            Image.new("RGB", (200, 100), "white").save(path)
            args = type("Args", (), {"image": str(path), "question": "트레이?", "note": "",
                                      "prepare_only": False, "expected_status": None,
                                      "expected_box": None})()
            response = Mock(status_code=401, headers={}, text="Bearer test-key")
            with patch.object(vision, "RESULTS", Path(folder) / "results"), \
                    patch.object(vision, "settings", return_value=("test-key", "https://api.meta.ai/v1", "test-model")), \
                    patch.object(vision.requests, "post", return_value=response):
                self.assertEqual(vision.run(args), 1)
            saved = next((Path(folder) / "results").glob("*/run.json")).read_text()
            self.assertNotIn("test-key", saved)
            self.assertEqual(json.loads(saved)["execution_status"], "failed")


if __name__ == "__main__":
    unittest.main()
