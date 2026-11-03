"""Recreate the explicitly public staged demo without keys or model requests."""
import hashlib
from functools import lru_cache
import io
import json
from pathlib import Path
import time

from .images import prepare_image
from .models import Step

DEMO_SCENARIOS = {
    "reception": ("showme-reception-demo-v1", "guide.json"),
    "storage-tags": ("showme-storage-tags-demo-v1", "storage-tags.json"),
}


@lru_cache(maxsize=1)
def staged_photo_hashes(asset_dir):
    """Recognize these explicitly public AI demo photos by canonical content."""
    directory = Path(asset_dir)
    guide = json.loads((directory / "guide.json").read_text())
    return frozenset(hashlib.sha256(prepare_image(io.BytesIO((directory / step["file"]).read_bytes()))[1]).hexdigest()
                     for step in guide["steps"])


def seed_demo(store, asset_dir, *, scenario="reception"):
    guide_id, guide_file = DEMO_SCENARIOS[scenario]
    asset_dir = Path(asset_dir)
    source = json.loads((asset_dir / guide_file).read_text())
    with store.connect() as db:
        existing = db.execute("SELECT share_id FROM revisions WHERE guide_id=? AND source_version=1", (guide_id,)).fetchone()
    if existing:
        share_id = existing["share_id"]
    else:
        # Validate all input and prepare all photos before making a new draft.
        photos, steps = [], []
        for index, item in enumerate(source["steps"], 1):
            image, canonical = prepare_image(io.BytesIO((asset_dir / item["file"]).read_bytes()))
            digest = hashlib.sha256(canonical).hexdigest()
            photo_id = "demo-" + digest[:24]
            metadata = {"id": photo_id, "filename": item["file"], "width": image.width,
                        "height": image.height, "sha256": digest,
                        "credit": "AI 연출 시연 사진 · 실제 행사 현장 아님", "source_url": ""}
            photos.append((photo_id, metadata, canonical))
            steps.append(Step(id=f"demo-step-{index}", photo_id=photo_id, operator_note=item["note"],
                              title=item["title"], instruction=item["instruction"],
                              completion_check=item["completion_check"], highlights=item["approved_highlights"],
                              reviewed=True).model_dump())
        document = {"id": guide_id, "version": 1, "title": source["title"], "goal": source["goal"],
                    "steps": steps, "updated_at": time.time()}
        for photo_id, metadata, canonical in photos:
            path = store.photos / (photo_id + ".jpg")
            if path.exists():
                if path.read_bytes() != canonical:
                    raise ValueError("기존 데모 사진과 내용이 달라 덮어쓰지 않았습니다.")
            else:
                path.write_bytes(canonical)
        with store.connect() as db:
            for photo_id, metadata, canonical in photos:
                db.execute("INSERT OR IGNORE INTO photos VALUES(?,?)", (photo_id, json.dumps(metadata, ensure_ascii=False)))
            db.execute("INSERT OR IGNORE INTO guides VALUES(?,?,?)", (guide_id, 1, json.dumps(document, ensure_ascii=False)))
        share_id = store.publish(guide_id, 1)["share_id"]
    (store.directory / "demo-share-id.txt").write_text(share_id + "\n")
    return "/learn/" + share_id
