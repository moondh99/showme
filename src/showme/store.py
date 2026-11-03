"""SQLite-backed drafts and immutable approved snapshots."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time

from fastapi import HTTPException


def normalize_document(document):
    """Read old single-step documents without rewriting approved snapshots."""
    document = dict(document)
    if "steps" not in document:
        document["steps"] = [document["step"]] if document.get("step") else []
    document.pop("step", None)
    return document


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.photos = self.directory / "photos"
        self.photos.mkdir(exist_ok=True)
        self.db = self.directory / "showme.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS guides(id TEXT PRIMARY KEY, version INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(share_id TEXT PRIMARY KEY, guide_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL, document TEXT NOT NULL, UNIQUE(guide_id,source_version));
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS question_turns(id TEXT PRIMARY KEY, share_id TEXT NOT NULL,
                    step_id TEXT NOT NULL, parent_id TEXT, question TEXT NOT NULL,
                    answer TEXT NOT NULL, metrics TEXT NOT NULL, created_at REAL NOT NULL, selection_id TEXT);
                CREATE TABLE IF NOT EXISTS selections(id TEXT PRIMARY KEY, share_id TEXT NOT NULL,
                    step_id TEXT NOT NULL, photo_id TEXT NOT NULL, document TEXT NOT NULL,
                    metrics TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_gaps(id TEXT PRIMARY KEY, share_id TEXT NOT NULL,
                    step_id TEXT NOT NULL, question TEXT NOT NULL, created_at REAL NOT NULL,
                    resolved_at REAL);
                CREATE INDEX IF NOT EXISTS learning_gaps_pending ON learning_gaps(share_id,resolved_at,created_at);
                CREATE TABLE IF NOT EXISTS model_failures(id INTEGER PRIMARY KEY,
                    created_at REAL NOT NULL, diagnostic TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_request_budget(day TEXT PRIMARY KEY, requests INTEGER NOT NULL);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(question_turns)")}
            if "selection_id" not in columns:
                db.execute("ALTER TABLE question_turns ADD COLUMN selection_id TEXT")
            if "intent" not in columns:
                db.execute("ALTER TABLE question_turns ADD COLUMN intent TEXT NOT NULL DEFAULT 'procedure'")
            if "recheck_of" not in columns:
                db.execute("ALTER TABLE question_turns ADD COLUMN recheck_of TEXT")
            gap_columns = {row["name"] for row in db.execute("PRAGMA table_info(learning_gaps)")}
            for column in ("recovered_by", "recovery_answer"):
                if column not in gap_columns:
                    db.execute(f"ALTER TABLE learning_gaps ADD COLUMN {column} TEXT")
            # Preserve existing pending work before the 24-hour conversation cleanup.
            # INSERT OR IGNORE must not reopen work the author already completed.
            for row in db.execute("SELECT id,share_id,step_id,question,answer,created_at,recheck_of FROM question_turns").fetchall():
                try:
                    missing = json.loads(row["answer"]).get("status") == "insufficient_information"
                except (ValueError, AttributeError):
                    missing = False
                if missing and not row["recheck_of"]:
                    db.execute("INSERT OR IGNORE INTO learning_gaps(id,share_id,step_id,question,created_at) VALUES(?,?,?,?,?)",
                               tuple(row[k] for k in ("id","share_id","step_id","question","created_at")))
        self.db.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def reserve_ai_request(self, limit):
        """Count attempted operations atomically; retained across service restarts.

        One operation is a generation, selection or question (up to two model
        calls). This is a request cap, not a dollar or token spending guarantee.
        """
        if limit == 0:
            return True
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT requests FROM ai_request_budget WHERE day=?", (day,)).fetchone()
            if row and row["requests"] >= limit:
                return False
            db.execute("INSERT INTO ai_request_budget VALUES(?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1", (day,))
            db.execute("DELETE FROM ai_request_budget WHERE day<?", (day,))
        return True

    def record_model_failure(self, diagnostic):
        """Persist sanitized error metadata only; no question, image or reply body.

        Keep a bounded local history so restarting does not erase the only clue.
        """
        if not diagnostic:
            return
        with self.connect() as db:
            db.execute("INSERT INTO model_failures(created_at,diagnostic) VALUES(?,?)",
                       (time.time(), json.dumps(diagnostic)))
            db.execute("DELETE FROM model_failures WHERE created_at<?", (time.time()-30*86400,))
            db.execute("DELETE FROM model_failures WHERE id NOT IN (SELECT id FROM model_failures ORDER BY id DESC LIMIT 200)")

    def photo(self, photo_id):
        with self.connect() as db:
            row = db.execute("SELECT metadata FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            raise HTTPException(404, "사진을 찾을 수 없습니다.")
        return json.loads(row["metadata"])

    def draft(self, guide_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM guides WHERE id=?", (guide_id,)).fetchone()
            revision = db.execute("SELECT share_id,document FROM revisions WHERE guide_id=? ORDER BY rowid DESC LIMIT 1", (guide_id,)).fetchone()
        if not row:
            raise HTTPException(404, "안내서를 찾을 수 없습니다.")
        document = normalize_document(json.loads(row["document"]))
        document["latest_publication"] = ({"url": "/learn/" + revision["share_id"],
            "revision_number": json.loads(revision["document"])["revision_number"]} if revision else None)
        photos = {s["photo_id"]: self.photo(s["photo_id"]) for s in document["steps"] if s["photo_id"]}
        document["photo_credits"] = {id: photo.get("credit", "") for id, photo in photos.items()}
        document["photo_dimensions"] = {id: {"width": photo["width"], "height": photo["height"]}
                                        for id, photo in photos.items()}
        document.pop("photo_credit", None)
        return document

    def save(self, guide_id, expected_version, document):
        document = dict(normalize_document(document), version=expected_version + 1, updated_at=time.time())
        with self.connect() as db:
            changed = db.execute("UPDATE guides SET version=?,document=? WHERE id=? AND version=?",
                (document["version"], json.dumps(document, ensure_ascii=False), guide_id, expected_version)).rowcount
            if not changed:
                raise HTTPException(409, "다른 변경이 저장됐습니다. 현재 내용을 복사한 뒤 안내서를 다시 열어 주세요.")
        return self.draft(guide_id)

    def publish(self, guide_id, version):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version,document FROM guides WHERE id=?", (guide_id,)).fetchone()
            if not row:
                raise HTTPException(404, "안내서를 찾을 수 없습니다.")
            if row["version"] != version:
                raise HTTPException(409, "내용이 변경됐습니다. 최신 초안을 검토해 주세요.")
            doc = normalize_document(json.loads(row["document"]))
            if not 1 <= len(doc["steps"]) <= 6:
                raise HTTPException(422, "사진을 1~6장 등록하고 단계를 검토해 주세요.")
            for position, step in enumerate(doc["steps"], 1):
                if not step["photo_id"] or not all(step.get(k, "").strip() for k in ["title", "instruction", "completion_check"]):
                    raise HTTPException(422, f"{position}단계의 사진·제목·설명·완료 확인을 채워 주세요.")
                if not step["reviewed"] or step["missing_information"]:
                    raise HTTPException(422, f"{position}단계의 확인할 내용을 보완하고 검토를 완료해 주세요.")
            existing = db.execute("SELECT document FROM revisions WHERE guide_id=? AND source_version=?", (guide_id, version)).fetchone()
            if existing:
                return normalize_document(json.loads(existing[0]))
            share_id = secrets.token_urlsafe(18)
            count = db.execute("SELECT COUNT(*) FROM revisions WHERE guide_id=?", (guide_id,)).fetchone()[0]
            snapshot = dict(doc, share_id=share_id, revision_number=count + 1, approved_at=time.time())
            db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (share_id, guide_id, version, json.dumps(snapshot, ensure_ascii=False)))
        return snapshot

    def revision(self, share_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM revisions WHERE share_id=?", (share_id,)).fetchone()
        if not row:
            raise HTTPException(404, "승인된 안내서를 찾을 수 없습니다.")
        return normalize_document(json.loads(row[0]))

    def create_session(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?)", (hashlib.sha256(token.encode()).hexdigest(), time.time() + 86400))
        return token

    def clarification_history(self, turn_id, share_id, step_id, selection_id=None, intent="procedure"):
        history = []
        with self.connect() as db:
            while turn_id:
                row = db.execute("SELECT * FROM question_turns WHERE id=? AND share_id=? AND step_id=? AND selection_id IS ? AND intent=? AND created_at>?",
                    (turn_id, share_id, step_id, selection_id, intent, time.time() - 86400)).fetchone()
                if not row:
                    raise HTTPException(404, "이 확인 대화를 열 수 없습니다. 새 질문으로 보내 주세요.")
                answer = json.loads(row["answer"])
                if answer["status"] != "needs_clarification":
                    raise HTTPException(422, "이미 답변한 질문입니다. 새 질문으로 보내 주세요.")
                history.append({"question": row["question"], "response": answer})
                if len(history) >= 6:
                    raise HTTPException(422, "확인 대화가 길어졌습니다. 대상을 구체적으로 적어 새 질문을 보내 주세요.")
                turn_id = row["parent_id"]
        return list(reversed(history))

    def clarification_intent(self, turn_id, share_id, step_id, selection_id=None):
        with self.connect() as db:
            row = db.execute("SELECT intent FROM question_turns WHERE id=? AND share_id=? AND step_id=? AND selection_id IS ? AND created_at>?",
                (turn_id, share_id, step_id, selection_id, time.time() - 86400)).fetchone()
        if not row:
            raise HTTPException(404, "이 확인 대화를 열 수 없습니다. 새 질문으로 보내 주세요.")
        return row["intent"]

    def validate_recheck(self, turn_id, share_id, step_id, question, selection_id, intent):
        """A public learner can recover only this exact scoped, recent refusal."""
        if intent != "procedure":
            raise HTTPException(422, "재확인은 승인 규칙에서 확인해 주세요.")
        with self.connect() as db:
            row = db.execute("""SELECT answer,question,recheck_of FROM question_turns
                WHERE id=? AND share_id=? AND step_id=? AND selection_id IS ? AND created_at>?""",
                (turn_id, share_id, step_id, selection_id, time.time()-86400)).fetchone()
        if not row:
            raise HTTPException(404, "재확인할 질문을 찾을 수 없습니다. 새 질문으로 보내 주세요.")
        if row["question"] != question or json.loads(row["answer"])["status"] != "insufficient_information":
            raise HTTPException(422, "동일한 미해결 질문만 재확인할 수 있습니다.")
        # Failed retries belong to the original durable gap, not a new gap.
        return row["recheck_of"] or turn_id

    def clarification_recheck(self, parent_id):
        # Caller has already validated the entire scoped clarification chain.
        with self.connect() as db:
            row = db.execute("SELECT recheck_of FROM question_turns WHERE id=?", (parent_id,)).fetchone()
        if not row:
            raise HTTPException(404, "이 확인 대화를 열 수 없습니다. 새 질문으로 보내 주세요.")
        return row["recheck_of"]

    def recovered_gap(self, turn_id):
        with self.connect() as db:
            row = db.execute("SELECT id FROM learning_gaps WHERE recovered_by=?", (turn_id,)).fetchone()
        return row["id"] if row else None

    def record_question(self, share_id, step_id, parent_id, question, answer, metrics, selection_id=None, intent="procedure", recheck_of=None):
        turn_id = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("DELETE FROM question_turns WHERE created_at<?", (time.time() - 86400,))
            db.execute("INSERT INTO question_turns(id,share_id,step_id,parent_id,question,answer,metrics,created_at,selection_id,intent,recheck_of) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (turn_id, share_id, step_id, parent_id, question, json.dumps(answer, ensure_ascii=False), json.dumps(metrics), time.time(), selection_id, intent, recheck_of))
            if answer["status"] == "insufficient_information" and not recheck_of:
                db.execute("INSERT INTO learning_gaps(id,share_id,step_id,question,created_at) VALUES(?,?,?,?,?)",
                    (turn_id, share_id, step_id, question, time.time()))
            if recheck_of and intent == "procedure" and answer["status"] == "answered":
                # Persist recovery evidence with the durable gap, independent of
                # expiring conversations. Do not overwrite an author's resolution.
                db.execute("""UPDATE learning_gaps SET resolved_at=?,recovered_by=?,recovery_answer=?
                    WHERE id=? AND share_id=? AND step_id=? AND resolved_at IS NULL""",
                    (time.time(), turn_id, json.dumps(answer, ensure_ascii=False), recheck_of, share_id, step_id))
        return turn_id

    def learning_gaps(self, guide_id):
        """Pending author work is independent of conversation age and success volume."""
        self.draft(guide_id)
        with self.connect() as db:
            rows = db.execute("""SELECT q.id,q.question,q.step_id,q.created_at,r.document
                FROM learning_gaps q JOIN revisions r ON q.share_id=r.share_id
                WHERE r.guide_id=? AND q.resolved_at IS NULL ORDER BY q.created_at DESC,q.id""",
                (guide_id,)).fetchall()
        gaps = []
        for row in rows:
            step = next((s for s in normalize_document(json.loads(row["document"]))["steps"] if s["id"] == row["step_id"]), {})
            gaps.append({"id": row["id"], "question": row["question"], "step_id": row["step_id"],
                         "step_title": step.get("title", "이전 단계"), "created_at": row["created_at"]})
        return gaps

    def resolve_gap(self, guide_id, gap_id, resolved):
        with self.connect() as db:
            changed = db.execute("""UPDATE learning_gaps SET resolved_at=? WHERE id=? AND share_id IN
                (SELECT share_id FROM revisions WHERE guide_id=?)""",
                (time.time() if resolved else None, gap_id, guide_id)).rowcount
        if not changed:
            raise HTTPException(404, "이 안내서의 보완 질문을 찾을 수 없습니다.")
        return {"id": gap_id, "resolved": resolved}

    def record_selection(self, share_id, step_id, photo_id, document, metrics):
        selection_id = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("DELETE FROM selections WHERE created_at<?", (time.time() - 86400,))
            db.execute("INSERT INTO selections VALUES(?,?,?,?,?,?,?)", (selection_id, share_id, step_id, photo_id,
                json.dumps(document), json.dumps(metrics), time.time()))
        return dict(document, id=selection_id, step_id=step_id)

    def selection(self, selection_id, share_id, step_id, photo_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM selections WHERE id=? AND share_id=? AND step_id=? AND photo_id=? AND created_at>?",
                (selection_id, share_id, step_id, photo_id, time.time() - 86400)).fetchone()
        if not row:
            raise HTTPException(404, "선택한 물체를 확인할 수 없습니다. 현재 사진에서 다시 선택해 주세요.")
        return dict(json.loads(row[0]), id=selection_id)

    def is_author(self, token):
        if not token:
            return False
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM sessions WHERE token_hash=? AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return bool(row)
