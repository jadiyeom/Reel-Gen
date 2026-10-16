import io
import json
import os
import shutil
import tempfile
import unittest
from PIL import Image

from pipeline.thumbnails import (
    get_thumbnails,
    save_thumbnail,
    delete_thumbnail,
    set_primary_thumbnail,
    get_primary_thumbnail_path,
    find_thumbnail_path,
    ALLOWED_THUMBNAIL_EXTS,
)
from dashboard.app import app


def _create_sample_image(format="PNG", size=(1080, 1920), color=(245, 166, 35)):
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf.getvalue()


class ThumbnailsPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manifest_path = os.path.join(self.temp_dir, "manifest.json")
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump({"topic": "Thumbnail Test Reel"}, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_retrieve_thumbnails(self):
        png_bytes = _create_sample_image("PNG", (1080, 1920))
        jpg_bytes = _create_sample_image("JPEG", (720, 1280), color=(50, 100, 200))

        # Save thumbnail 1
        res1 = save_thumbnail(self.temp_dir, 1, png_bytes, original_filename="thumb1.png")
        t1 = res1["slot_1"]
        self.assertTrue(t1["exists"])
        self.assertEqual(t1["slot"], 1)
        self.assertEqual(t1["width"], 1080)
        self.assertEqual(t1["height"], 1920)
        self.assertTrue(t1["is_primary"])
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "thumbnails", t1["filename"])))

        # Save thumbnail 2
        res2 = save_thumbnail(self.temp_dir, 2, jpg_bytes, original_filename="variant.jpg")
        t2 = res2["slot_2"]
        self.assertTrue(t2["exists"])
        self.assertEqual(t2["slot"], 2)
        self.assertEqual(t2["width"], 720)
        self.assertEqual(t2["height"], 1280)
        self.assertFalse(t2["is_primary"])  # Slot 1 was primary

        # Verify get_thumbnails
        thumbs = get_thumbnails(self.temp_dir)
        self.assertTrue(thumbs["slot_1"]["exists"])
        self.assertTrue(thumbs["slot_2"]["exists"])
        self.assertEqual(thumbs["primary_slot"], 1)
        self.assertEqual(thumbs["primary_info"]["slot"], 1)
        self.assertEqual(thumbs["count"], 2)

    def test_set_primary_thumbnail(self):
        png_bytes = _create_sample_image("PNG")
        save_thumbnail(self.temp_dir, 1, png_bytes)
        save_thumbnail(self.temp_dir, 2, png_bytes)

        # Switch primary to slot 2
        updated = set_primary_thumbnail(self.temp_dir, 2)
        self.assertEqual(updated["primary_slot"], 2)
        self.assertTrue(updated["slot_2"]["is_primary"])
        self.assertFalse(updated["slot_1"]["is_primary"])

        primary_path = get_primary_thumbnail_path(self.temp_dir)
        self.assertIsNotNone(primary_path)
        self.assertTrue("thumbnail_2" in primary_path.name)

    def test_delete_thumbnail(self):
        png_bytes = _create_sample_image("PNG")
        save_thumbnail(self.temp_dir, 1, png_bytes)
        save_thumbnail(self.temp_dir, 2, png_bytes)

        # Delete slot 1
        updated = delete_thumbnail(self.temp_dir, 1)
        self.assertFalse(updated["slot_1"]["exists"])
        self.assertTrue(updated["slot_2"]["exists"])
        # Slot 2 should automatically become the primary thumbnail
        self.assertEqual(updated["primary_slot"], 2)
        self.assertTrue(updated["slot_2"]["is_primary"])

        # Check file deleted from disk
        self.assertIsNone(find_thumbnail_path(self.temp_dir, 1))

    def test_invalid_slot_and_corrupt_data(self):
        with self.assertRaises(ValueError):
            save_thumbnail(self.temp_dir, 3, b"data")

        with self.assertRaises(ValueError):
            save_thumbnail(self.temp_dir, 1, b"not an image", original_filename="fake.png")


class ThumbnailsDashboardAPITests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Create a test video folder in output/ with valid YYYY-MM-DD-slug name and script.json
        self.vid = "2026-10-15-test-thumb-reel"
        self.video_dir = os.path.join("output", self.vid)
        os.makedirs(self.video_dir, exist_ok=True)
        with open(os.path.join(self.video_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump({"topic": "API Test Video", "scenes": []}, f)
        with open(os.path.join(self.video_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"topic": "API Test Video"}, f)

    def tearDown(self):
        shutil.rmtree(self.video_dir, ignore_errors=True)

    def test_thumbnail_upload_api_and_media_routes(self):
        img_bytes = _create_sample_image("PNG", (1080, 1920))

        # Upload slot 1 via POST
        data = {
            "thumbnail": (io.BytesIO(img_bytes), "cover.png")
        }
        res = self.client.post(f"/api/video/{self.vid}/thumbnail/1", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data["ok"])
        self.assertEqual(json_data["thumbnail"]["slot"], 1)

        # Query GET /api/video/<vid>/thumbnails
        res_get = self.client.get(f"/api/video/{self.vid}/thumbnails")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn("slot_1", res_get.get_json())
        self.assertTrue(res_get.get_json()["slot_1"]["exists"])

        # Query GET /media/<vid>/thumbnail/1
        res_media = self.client.get(f"/media/{self.vid}/thumbnail/1")
        self.assertEqual(res_media.status_code, 200)
        self.assertEqual(res_media.content_type, "image/png")
        res_media.close()

        # Query GET /download/<vid>/thumbnail/1
        res_dl = self.client.get(f"/download/{self.vid}/thumbnail/1")
        self.assertEqual(res_dl.status_code, 200)
        self.assertIn("attachment", res_dl.headers.get("Content-Disposition", ""))
        res_dl.close()

        # Set primary slot 1 explicitly
        res_prim = self.client.post(f"/api/video/{self.vid}/thumbnail/primary", json={"slot": 1})
        self.assertEqual(res_prim.status_code, 200)

        # Delete slot 1 via DELETE
        res_del = self.client.delete(f"/api/video/{self.vid}/thumbnail/1")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["ok"])

        # Query after delete
        res_media_after = self.client.get(f"/media/{self.vid}/thumbnail/1")
        self.assertEqual(res_media_after.status_code, 404)


if __name__ == "__main__":
    unittest.main()
