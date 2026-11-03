from collections import defaultdict, deque
import hashlib
import io
import inspect
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
import warnings

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .images import prepare_image
from .models import AskQuestion, CreateGuide, Login, ResolveGap, SaveGuide, SelectObject, Step, Version
from .answer_policy import approved_context, operational_question, question_intent
from .demo import staged_photo_hashes
from .segmentation import segment_object, validate_selection
from .store import Store
from .vision import VisionError, generate_step, validate_answer, invalid_model_response
from .reasoning import answer_with_reasoning, RuleAssessment
from .deployment import public_origin

ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = 10 * 1024 * 1024


def create_app(data_dir=None, author_password=None, generator=None, answerer=None, segmenter=None):
    load_dotenv(ROOT / ".env.local", override=False)
    store = Store(data_dir or os.getenv("SHOWME_DATA_DIR", str(ROOT / "state")))
    password_path = store.directory / "author-password.txt"
    password = author_password or os.getenv("SHOWME_AUTHOR_PASSWORD", "").strip()
    if not password:
        if not password_path.exists():
            with password_path.open("x") as f:
                f.write(secrets.token_urlsafe(18) + "\n")
            password_path.chmod(0o600)
        password = password_path.read_text().strip()
    generator = generator or generate_step
    answerer = answerer or answer_with_reasoning
    answer_parameters = inspect.signature(answerer).parameters
    accepts_intent = "intent" in answer_parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in answer_parameters.values())
    segmenter = segmenter or segment_object
    app = FastAPI(title="ShowMe", docs_url=None, redoc_url=None, openapi_url=None)
    configured_origin = public_origin(os.getenv("SHOWME_PUBLIC_ORIGIN", ""))
    hosts = ["127.0.0.1", "localhost", "testserver", "[::1]"]
    if configured_origin:
        hosts.append(configured_origin.hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    daily_limit = int(os.getenv("SHOWME_AI_DAILY_LIMIT", "0"))
    if daily_limit < 0:
        raise ValueError("SHOWME_AI_DAILY_LIMIT must be nonnegative.")
    app.state.store = store
    busy = set()
    lock = threading.Lock()
    login_attempts = defaultdict(deque)
    question_attempts = defaultdict(deque)
    question_busy = set()

    def reserve_budget():
        if not store.reserve_ai_request(daily_limit):
            raise HTTPException(429, "오늘의 AI 사용 한도에 도달했어요. 승인된 설명은 계속 읽을 수 있습니다.")

    def acquire_learner_slot(request, share_id, step_id):
        address = request.client.host if request.client else "local"
        slot = (address, share_id, step_id)
        now = time.monotonic()
        with lock:
            attempts = question_attempts[address]
            while attempts and attempts[0] < now - 3600:
                attempts.popleft()
            if len(attempts) >= 60 or sum(t > now - 60 for t in attempts) >= 10:
                raise HTTPException(429, "요청이 많아 잠시 쉬고 있습니다. 조금 뒤 다시 시도해 주세요.")
            if slot in question_busy:
                raise HTTPException(409, "이 단계의 물체 선택 또는 답변을 기다리는 중입니다.")
            if len(busy) + len(question_busy) >= 2:
                raise HTTPException(429, "다른 AI 요청을 처리 중입니다. 잠시 뒤 다시 시도해 주세요.")
            reserve_budget()
            attempts.append(now)
            question_busy.add(slot)
        return slot

    def learner_error(exc):
        store.record_model_failure(exc.diagnostics)
        if exc.code in {"missing_key", "configuration", "authentication", "billing", "permission"}:
            return HTTPException(502, {"code": "temporarily_unavailable",
                "message": "지금은 AI 기능을 사용할 수 없습니다. 승인된 설명을 먼저 확인하고 담당자에게 알려 주세요."})
        return HTTPException(502, {"code": exc.code, "message": str(exc)})

    @app.middleware("http")
    async def protect_origin(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                    origin and urlsplit(origin).netloc != request.headers.get("host")):
                return JSONResponse({"detail": "다른 사이트에서 보낸 변경 요청은 허용되지 않습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        if configured_origin:
            response.headers["Strict-Transport-Security"] = "max-age=86400"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    def author(request: Request):
        if not store.is_author(request.cookies.get("showme_session")):
            raise HTTPException(401, "작성자 로그인이 필요합니다.")

    def photo_response(photo_id):
        metadata = store.photo(photo_id)
        return FileResponse(store.photos / (photo_id + ".jpg"), media_type="image/jpeg")

    def register_image(data, filename, credit="", source_url=""):
        if not data or len(data) > MAX_UPLOAD:
            raise HTTPException(413, "사진은 10MB 이하로 선택해 주세요.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as img:
                    if img.format not in {"JPEG", "PNG", "WEBP"}:
                        raise HTTPException(415, "JPEG, PNG, WebP 사진을 선택해 주세요.")
                    img.verify()
                image, canonical = prepare_image(io.BytesIO(data))
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(415, "사진을 읽을 수 없습니다. 다른 사진을 선택해 주세요.") from None
        photo_id = uuid4().hex
        metadata = {"id": photo_id, "filename": Path(filename or "photo").name,
                    "width": image.width, "height": image.height,
                    "sha256": hashlib.sha256(canonical).hexdigest(), "credit": credit, "source_url": source_url}
        (store.photos / (photo_id + ".jpg")).write_bytes(canonical)
        with store.connect() as db:
            db.execute("INSERT INTO photos VALUES(?,?)", (photo_id, json.dumps(metadata, ensure_ascii=False)))
        return metadata

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/demo")
    def demo_link():
        path = store.directory / "demo-share-id.txt"
        if not path.exists():
            return {"url": None}
        share_id = path.read_text().strip()
        try:
            store.revision(share_id)
        except HTTPException:
            return {"url": None}
        return {"url": "/learn/" + share_id}

    @app.get("/demo")
    def demo_page():
        url = demo_link()["url"]
        if not url:
            raise HTTPException(404, "시연 안내서가 아직 준비되지 않았습니다.")
        return RedirectResponse(url)

    @app.get("/api/session")
    def session(request: Request):
        return {"author": store.is_author(request.cookies.get("showme_session"))}

    @app.post("/api/session")
    def login(payload: Login, request: Request, response: Response):
        address = request.client.host if request.client else "local"
        now = time.monotonic()
        with lock:
            attempts = login_attempts[address]
            while attempts and attempts[0] < now - 60:
                attempts.popleft()
            if len(attempts) >= 8:
                raise HTTPException(429, "잠시 기다린 뒤 다시 로그인해 주세요.")
            attempts.append(now)
        if not secrets.compare_digest(payload.password.encode(), password.encode()):
            raise HTTPException(401, "비밀번호가 맞지 않습니다.")
        response.set_cookie("showme_session", store.create_session(), httponly=True,
                            samesite="strict", secure=bool(configured_origin) or request.url.scheme == "https", max_age=86400)
        return {"author": True}

    @app.delete("/api/session")
    def logout(request: Request, response: Response):
        token = request.cookies.get("showme_session", "")
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie("showme_session")
        return {"author": False}

    @app.post("/api/photos", dependencies=[Depends(author)])
    async def upload(file: UploadFile = File(...)):
        # Read at most the allowed size plus one byte rather than the whole file.
        data = await file.read(MAX_UPLOAD + 1)
        await file.close()
        return register_image(data, file.filename)

    @app.post("/api/photos/sample", dependencies=[Depends(author)])
    def sample():
        path = ROOT / "public/demo/sample-notepad.jpg"
        if not path.exists():
            raise HTTPException(404, "샘플 사진이 없습니다. 직접 사진을 등록해 주세요.")
        return register_image(path.read_bytes(), "notepad.jpg", "Eric Bailey / Wikimedia Commons / CC0 1.0",
                              "https://commons.wikimedia.org/wiki/File:Laptop_picture_with_notepad.jpg")

    @app.get("/api/photos/{photo_id}", dependencies=[Depends(author)])
    def private_photo(photo_id: str):
        return photo_response(photo_id)

    @app.get("/api/guides", dependencies=[Depends(author)])
    def list_guides():
        with store.connect() as db:
            rows = db.execute("SELECT document FROM guides ORDER BY rowid DESC").fetchall()
        return [store.draft(json.loads(row[0])["id"]) for row in rows]

    @app.post("/api/guides", dependencies=[Depends(author)])
    def create_guide(payload: CreateGuide):
        guide_id = uuid4().hex
        document = {"id": guide_id, "title": payload.title, "goal": payload.goal,
                    "version": 1, "steps": [], "updated_at": time.time()}
        with store.connect() as db:
            db.execute("INSERT INTO guides VALUES(?,?,?)", (guide_id, 1, json.dumps(document, ensure_ascii=False)))
        return document

    @app.get("/api/guides/{guide_id}", dependencies=[Depends(author)])
    def get_guide(guide_id: str):
        return store.draft(guide_id)

    @app.get("/api/guides/{guide_id}/learning-gaps", dependencies=[Depends(author)])
    def learning_gaps(guide_id: str):
        return store.learning_gaps(guide_id)

    @app.post("/api/guides/{guide_id}/learning-gaps/{gap_id}/resolve", dependencies=[Depends(author)])
    def resolve_gap(guide_id: str, gap_id: str, payload: ResolveGap):
        return store.resolve_gap(guide_id, gap_id, payload.resolved)

    @app.put("/api/guides/{guide_id}", dependencies=[Depends(author)])
    def save_guide(guide_id: str, payload: SaveGuide):
        previous = store.draft(guide_id)
        data = {"title": payload.title, "goal": payload.goal, "steps": payload.ordered_steps()}
        old_positions = {s["id"]: (i, s) for i, s in enumerate(previous["steps"])}
        global_change = previous["title"] != data["title"] or previous["goal"] != data["goal"]
        for position, step in enumerate(data["steps"]):
            if step["photo_id"]:
                store.photo(step["photo_id"])
            old_position, old_step = old_positions.get(step["id"], (-1, {}))
            old_content = {k: v for k, v in old_step.items() if k != "reviewed"}
            new_content = {k: v for k, v in step.items() if k != "reviewed"}
            if global_change or old_position != position or old_content != new_content:
                step["reviewed"] = False
        document = dict(previous, **data)
        return store.save(guide_id, payload.version, document)

    @app.post("/api/guides/{guide_id}/steps/{step_id}/generate", dependencies=[Depends(author)])
    def generate(guide_id: str, step_id: str, payload: Version):
        draft = store.draft(guide_id)
        if draft["version"] != payload.version:
            raise HTTPException(409, "최신 내용을 먼저 저장해 주세요.")
        step = next((s for s in draft["steps"] if s["id"] == step_id), None)
        if step is None:
            raise HTTPException(404, "단계를 찾을 수 없습니다.")
        if not step["photo_id"] or not step["operator_note"].strip():
            raise HTTPException(422, "사진과 행동 메모를 먼저 등록해 주세요.")
        photo = store.photo(step["photo_id"])
        with lock:
            if guide_id in busy:
                raise HTTPException(409, "이미 이 안내서의 설명을 만들고 있습니다.")
            if len(busy) + len(question_busy) >= 2:
                raise HTTPException(429, "다른 설명을 생성 중입니다. 잠시 뒤 다시 시도해 주세요.")
            busy.add(guide_id)
        try:
            reserve_budget()
            generated, metrics = generator(photo, (store.photos / (photo["id"] + ".jpg")).read_bytes(),
                                           draft["title"], draft["goal"], step["operator_note"])
            from .models import GeneratedStep
            try:
                generated = GeneratedStep.model_validate(generated).model_dump()
            except ValidationError:
                raise VisionError("invalid_response", "AI 응답 형식을 확인하지 못했습니다. 기존 내용은 유지됩니다.") from None
            if generated["photo_id"] != photo["id"]:
                raise VisionError("invalid_response", "사진 연결을 확인하지 못했습니다. 기존 내용은 유지됩니다.")
            draft["steps"] = [dict(s, **generated, reviewed=False) if s["id"] == step_id else s
                              for s in draft["steps"]]
            draft.setdefault("generations", {})[step_id] = metrics
            return store.save(guide_id, payload.version, draft)
        except VisionError as exc:
            store.record_model_failure(exc.diagnostics)
            raise HTTPException(502, {"code": exc.code, "message": str(exc)}) from None
        finally:
            with lock:
                busy.discard(guide_id)

    @app.post("/api/guides/{guide_id}/publish", dependencies=[Depends(author)])
    def publish(guide_id: str, payload: Version):
        snapshot = store.publish(guide_id, payload.version)
        return {"share_id": snapshot["share_id"], "url": "/learn/" + snapshot["share_id"],
                "revision_number": snapshot["revision_number"]}

    @app.get("/api/learn/{share_id}")
    def learn(share_id: str):
        snapshot = store.revision(share_id)
        # The learner receives approved content, not private operator notes or usage data.
        steps = []
        for step in snapshot["steps"]:
            metadata = store.photo(step["photo_id"])
            steps.append({**{k: step[k] for k in ["id", "photo_id", "title", "instruction", "completion_check", "highlights"]},
                          "photo_credit": metadata.get("credit", ""),
                          "photo_origin": "staged_ai" if metadata.get("sha256") in staged_photo_hashes(ROOT / "public/demo/reception-setup") else None,
                          "photo_width": metadata["width"], "photo_height": metadata["height"]})
        result = {"title": snapshot["title"], "goal": snapshot["goal"],
                "revision_number": snapshot["revision_number"], "approved_at": snapshot["approved_at"],
                "share_id": share_id, "steps": steps}
        if len(steps) == 1:
            result["step"] = steps[0]  # Original published URLs/API consumers remain readable.
        return result

    @app.post("/api/learn/{share_id}/questions")
    def ask(share_id: str, payload: AskQuestion, request: Request):
        snapshot = store.revision(share_id)
        approved = next((s for s in snapshot["steps"] if s["id"] == payload.step_id), None)
        if approved is None:
            raise HTTPException(404, "이 승인본에 없는 단계입니다.")
        selection = store.selection(payload.selection_id, share_id, payload.step_id, approved["photo_id"]) if payload.selection_id else None
        intent = payload.intent
        if intent == "auto":
            intent = (store.clarification_intent(payload.clarification_of, share_id, payload.step_id, payload.selection_id)
                      if payload.clarification_of else question_intent(payload.question))
        elif intent == "appearance" and not payload.clarification_of and operational_question(payload.question):
            # Old tabs may keep an appearance choice after a quick question.
            intent = "procedure"
        history = store.clarification_history(payload.clarification_of, share_id, payload.step_id, payload.selection_id, intent) if payload.clarification_of else []
        recheck_of = None
        if payload.recheck_of:
            recheck_of = store.validate_recheck(payload.recheck_of, share_id, payload.step_id,
                                               payload.question, payload.selection_id, intent)
        elif history:
            recheck_of = store.clarification_recheck(payload.clarification_of)
        # Keep private notes and generation metadata out of the answering interface.
        step = {k: approved[k] for k in ("id", "title", "instruction", "completion_check", "highlights")}
        slot = acquire_learner_slot(request, share_id, payload.step_id)
        try:
            data = (store.photos / (approved["photo_id"] + ".jpg")).read_bytes()
            requested_intent = "auto" if payload.intent == "auto" and not payload.clarification_of else intent
            if accepts_intent:
                answer, metrics = answerer(data, step, payload.question, history, selection, intent=requested_intent)
            elif selection:
                # Compatibility for injected services implementing the original callback.
                answer, metrics = answerer(data, step, payload.question, history, selection)
            else:
                answer, metrics = answerer(data, step, payload.question, history)
            resolved_intent = metrics.get("resolved_intent", intent)
            if resolved_intent not in ("procedure", "appearance") or (payload.clarification_of and resolved_intent != intent):
                raise invalid_model_response("semantic_scope", "ShowMeSemanticAudit", reason="invalid_resolved_scope")
            intent = resolved_intent
            answer = validate_answer(answer, step, selection, intent)
            answer["approved_context"] = approved_context(step, answer["status"], intent)
            if metrics.get("assessment") is not None:
                try:
                    answer["assessment"] = RuleAssessment.model_validate(metrics["assessment"]).model_dump(exclude_none=True)
                except ValidationError as exc:
                    raise invalid_model_response("assessment", "ShowMeSemanticAudit", exc) from None
            turn_id = store.record_question(share_id, payload.step_id, payload.clarification_of, payload.question, answer, metrics, payload.selection_id, intent, recheck_of)
            return dict(answer, id=turn_id, step_id=payload.step_id, revision_number=snapshot["revision_number"], selection_id=payload.selection_id, intent=intent,
                        recovered_gap_id=store.recovered_gap(turn_id), recheck_of=recheck_of)
        except VisionError as exc:
            raise learner_error(exc) from None
        finally:
            with lock:
                question_busy.discard(slot)

    @app.post("/api/learn/{share_id}/selections")
    def select_object(share_id: str, payload: SelectObject, request: Request):
        snapshot = store.revision(share_id)
        step = next((s for s in snapshot["steps"] if s["id"] == payload.step_id), None)
        if step is None:
            raise HTTPException(404, "이 승인본에 없는 단계입니다.")
        metadata = store.photo(step["photo_id"])
        point = payload.point.model_dump()
        slot = acquire_learner_slot(request, share_id, payload.step_id)
        try:
            data = (store.photos / (step["photo_id"] + ".jpg")).read_bytes()
            selection, metrics = segmenter(data, metadata, point)
            selection = validate_selection(selection, metadata, point)
            if selection["status"] == "not_found":
                return dict(selection, step_id=payload.step_id,
                    message="선택한 지점에서 물체를 확인하지 못했습니다. 물체의 가운데를 다시 선택해 주세요.")
            return store.record_selection(share_id, payload.step_id, step["photo_id"], selection, metrics)
        except VisionError as exc:
            raise learner_error(exc) from None
        finally:
            with lock:
                question_busy.discard(slot)

    @app.get("/api/learn/{share_id}/steps/{step_id}/photo")
    def shared_step_photo(share_id: str, step_id: str):
        step = next((s for s in store.revision(share_id)["steps"] if s["id"] == step_id), None)
        if step is None:
            raise HTTPException(404, "이 승인본에 없는 단계입니다.")
        return photo_response(step["photo_id"])

    @app.get("/api/learn/{share_id}/photo")
    def shared_photo(share_id: str):
        return photo_response(store.revision(share_id)["steps"][0]["photo_id"])

    @app.get("/")
    @app.get("/learn/{share_id}")
    def page(share_id: str = ""):
        return FileResponse(ROOT / "web/index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
