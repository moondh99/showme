import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from showme.app import create_app
from showme.models import Step
from showme.vision import VisionError


def fixture_generator(photo, data, title, goal, note):
    return {"photo_id": photo["id"], "title": "펜 준비하기", "instruction": note,
            "completion_check": "펜이 노트 위에 있는지 확인합니다.",
            "highlights": [{"label": "펜", "box": [100, 200, 400, 700], "origin": "model"}],
            "missing_information": []}, {"model": "fixture-not-real-api", "elapsed_seconds": .01, "usage": {}}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, author_password="test-password", generator=fixture_generator)
        self.client = TestClient(self.app)
        self.assertEqual(self.client.post('/api/session', json={"password": "test-password"}).status_code, 200)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def guide_with_photo(self):
        data = io.BytesIO()
        Image.new('RGB', (120, 80), 'white').save(data, format='JPEG')
        photo = self.client.post('/api/photos', files={'file': ('photo.jpg', data.getvalue(), 'image/jpeg')}).json()
        draft = self.client.post('/api/guides', json={"title": "테스트 안내서", "goal": "서명 준비"}).json()
        draft['steps'].append(Step().model_dump())
        draft['steps'][0].update(photo_id=photo['id'], operator_note="검은 펜을 노트 위에 준비합니다.")
        return self.save(draft).json()

    def save(self, draft):
        return self.client.put('/api/guides/' + draft['id'], json={k: draft[k] for k in ['title', 'goal', 'version', 'steps']})

    def generated(self):
        draft = self.guide_with_photo()
        r = self.client.post(f"/api/guides/{draft['id']}/steps/step-1/generate", json={"version": draft['version']})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def approve(self, draft):
        draft['steps'][0]['reviewed'] = True
        draft = self.save(draft).json()
        r = self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']})
        self.assertEqual(r.status_code, 200, r.text)
        return draft, r.json()

    def test_end_to_end_edit_review_publish_and_public_isolation(self):
        draft = self.generated()
        draft['steps'][0]['instruction'] = '수정한 설명: 펜을 노트 오른쪽에 놓습니다.'
        draft['steps'][0]['highlights'][0].update(box=[200, 200, 500, 700], origin='author')
        draft['steps'][0]['reviewed'] = True
        draft = self.save(draft).json()
        self.assertFalse(draft['steps'][0]['reviewed'], 'Editing cannot silently approve a step')
        draft, publication = self.approve(draft)
        with TestClient(self.app) as anon:
            self.assertEqual(anon.get('/api/guides/' + draft['id']).status_code, 401)
            self.assertEqual(anon.put('/api/guides/' + draft['id'], json={}).status_code, 401)
            self.assertEqual(anon.get('/api/photos/' + draft['steps'][0]['photo_id']).status_code, 401)
            public = anon.get('/api/learn/' + publication['share_id']).json()
            self.assertEqual(public['steps'][0]['instruction'], draft['steps'][0]['instruction'])
            self.assertEqual(public['steps'][0]['highlights'][0]['box'], [200, 200, 500, 700])
            self.assertNotIn('operator_note', public['steps'][0])
            self.assertNotIn('generation', public)
            self.assertEqual(anon.get('/api/learn/' + publication['share_id'] + '/photo').status_code, 200)
            self.assertEqual(anon.get('/api/learn/nonexistent/photo').status_code, 404)
        # Publishing the same draft version twice is idempotent.
        duplicate = self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).json()
        self.assertEqual(duplicate['share_id'], publication['share_id'])
        draft['steps'][0]['instruction'] = '다음 초안의 다른 설명'
        self.save(draft)
        self.assertEqual(self.client.get('/api/learn/' + publication['share_id']).json()['steps'][0]['instruction'], public['steps'][0]['instruction'])
        self.assertTrue(self.client.get('/api/guides/' + draft['id']).json()['latest_publication'])

    def test_unreviewed_draft_cannot_be_published(self):
        draft = self.generated()
        self.assertEqual(self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).status_code, 422)

    def test_stale_save_does_not_overwrite_current_draft(self):
        draft = self.guide_with_photo()
        stale = copy.deepcopy(draft)
        draft['title'] = '현재 버전'
        self.assertEqual(self.save(draft).status_code, 200)
        stale['title'] = '오래된 버전'
        self.assertEqual(self.save(stale).status_code, 409)
        self.assertEqual(self.client.get('/api/guides/' + draft['id']).json()['title'], '현재 버전')

    def test_generation_after_a_concurrent_edit_is_rejected(self):
        draft = self.guide_with_photo()
        def concurrent(photo, data, title, goal, note):
            changed = copy.deepcopy(draft)
            changed['steps'][0]['operator_note'] = '생성 중에 바꾼 새 메모'
            self.app.state.store.save(draft['id'], draft['version'], changed)
            return fixture_generator(photo, data, title, goal, note)
        self.app = create_app(self.temp.name, author_password='test-password', generator=concurrent)
        with TestClient(self.app) as client:
            client.post('/api/session', json={'password': 'test-password'})
            r = client.post(f"/api/guides/{draft['id']}/steps/step-1/generate", json={'version': draft['version']})
            self.assertEqual(r.status_code, 409)
            saved = client.get('/api/guides/' + draft['id']).json()
            self.assertEqual(saved['steps'][0]['operator_note'], '생성 중에 바꾼 새 메모')
            self.assertEqual(saved['steps'][0]['instruction'], '')

    def test_timeout_preserves_existing_content(self):
        draft = self.generated()
        def fail(*args):
            raise VisionError('timeout', '시간 초과')
        app = create_app(self.temp.name, author_password='test-password', generator=fail)
        with TestClient(app) as client:
            client.post('/api/session', json={'password': 'test-password'})
            r = client.post(f"/api/guides/{draft['id']}/steps/step-1/generate", json={'version': draft['version']})
            self.assertEqual(r.status_code, 502)
            self.assertEqual(client.get('/api/guides/' + draft['id']).json()['steps'][0], draft['steps'][0])

    def test_restart_keeps_snapshot_and_photo(self):
        draft, publication = self.approve(self.generated())
        with TestClient(create_app(self.temp.name, author_password='test-password', generator=fixture_generator)) as restarted:
            self.assertEqual(restarted.get('/api/learn/' + publication['share_id']).json()['steps'][0]['instruction'], draft['steps'][0]['instruction'])
            self.assertEqual(restarted.get('/api/learn/' + publication['share_id'] + '/photo').status_code, 200)

    def test_bad_upload_bad_coordinates_and_csrf_are_rejected(self):
        self.assertEqual(self.client.post('/api/photos', files={'file': ('fake.jpg', b'not an image', 'image/jpeg')}).status_code, 415)
        draft = self.guide_with_photo()
        draft['steps'][0]['highlights'] = [{'label': 'bad', 'box': [900, 0, 100, 10]}]
        self.assertEqual(self.save(draft).status_code, 422)
        response = self.client.post('/api/guides', json={'title': 'CSRF'}, headers={'Origin': 'https://unrelated.example'})
        self.assertEqual(response.status_code, 403)


    def six_steps(self, generated=False):
        draft = self.guide_with_photo()
        first = copy.deepcopy(draft['steps'][0])
        draft['steps'] = [dict(copy.deepcopy(first), id=f'step-{i}', operator_note=f'{i}단계 행동 메모') for i in range(1, 7)]
        draft = self.save(draft).json()
        if generated:
            for step_id in [step['id'] for step in draft['steps']]:
                r = self.client.post(f"/api/guides/{draft['id']}/steps/{step_id}/generate", json={'version': draft['version']})
                self.assertEqual(r.status_code, 200, r.text)
                draft = r.json()
        return draft

    def test_six_steps_publish_reorder_and_snapshot_photo_scope(self):
        draft = self.six_steps(generated=True)
        for step in draft['steps']:
            step['reviewed'] = True
        draft = self.save(draft).json()
        old_order = [s['id'] for s in draft['steps']]
        pub = self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).json()
        draft['steps'][0], draft['steps'][1] = draft['steps'][1], draft['steps'][0]
        draft = self.save(draft).json()
        self.assertEqual([s['reviewed'] for s in draft['steps']], [False, False, True, True, True, True])
        self.assertEqual(self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).status_code, 422)
        old_public = self.client.get('/api/learn/' + pub['share_id']).json()
        self.assertEqual([s['id'] for s in old_public['steps']], old_order)
        for step in draft['steps']:
            step['reviewed'] = True
        draft = self.save(draft).json()
        new_pub = self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).json()
        self.assertNotEqual(pub['share_id'], new_pub['share_id'])
        self.assertEqual([s['id'] for s in self.client.get('/api/learn/' + new_pub['share_id']).json()['steps']], [s['id'] for s in draft['steps']])
        self.assertEqual(self.client.get('/api/learn/' + new_pub['share_id'] + '/steps/step-6/photo').status_code, 200)
        self.assertEqual(self.client.get('/api/learn/' + new_pub['share_id'] + '/steps/unapproved-step/photo').status_code, 404)

    def test_seventh_step_and_duplicate_ids_never_overwrite_draft(self):
        draft = self.six_steps()
        original_version = draft['version']
        seventh = copy.deepcopy(draft['steps'][0]); seventh['id'] = 'step-7'
        draft['steps'].append(seventh)
        self.assertEqual(self.save(draft).status_code, 422)
        self.assertEqual(self.client.get('/api/guides/' + draft['id']).json()['version'], original_version)
        draft['steps'].pop()
        draft['steps'][1]['id'] = draft['steps'][0]['id']
        self.assertEqual(self.save(draft).status_code, 422)
        self.assertEqual(len(self.client.get('/api/guides/' + draft['id']).json()['steps']), 6)

    def test_generation_and_edit_only_invalidate_the_target_step(self):
        draft = self.six_steps(generated=True)
        for step in draft['steps']:
            step['reviewed'] = True
        draft = self.save(draft).json()
        untouched = copy.deepcopy(draft['steps'][0])
        draft['steps'][2]['instruction'] = '3단계만 수동 수정'
        draft = self.save(draft).json()
        self.assertEqual([s['reviewed'] for s in draft['steps']], [True, True, False, True, True, True])
        draft = self.client.post(f"/api/guides/{draft['id']}/steps/step-3/generate", json={'version': draft['version']}).json()
        self.assertEqual(draft['steps'][0], untouched)
        self.assertEqual(draft['steps'][2]['operator_note'], '3단계 행동 메모')
        self.assertNotEqual(draft['steps'][2]['instruction'], '3단계만 수동 수정')

    def test_removal_preserves_old_snapshot_and_resets_shifted_steps(self):
        draft = self.six_steps(generated=True)
        for step in draft['steps']:
            step['reviewed'] = True
        draft = self.save(draft).json()
        pub = self.client.post('/api/guides/' + draft['id'] + '/publish', json={'version': draft['version']}).json()
        draft['steps'].pop(2)
        draft = self.save(draft).json()
        self.assertEqual([s['reviewed'] for s in draft['steps']], [True, True, False, False, False])
        public = self.client.get('/api/learn/' + pub['share_id']).json()
        self.assertEqual(len(public['steps']), 6)
        self.assertEqual(self.client.get('/api/learn/' + pub['share_id'] + '/steps/step-3/photo').status_code, 200)

    def test_legacy_document_read_does_not_rewrite_original_snapshot(self):
        import json
        draft, pub = self.approve(self.generated())
        store = self.app.state.store
        with store.connect() as db:
            raw_draft = json.loads(db.execute('SELECT document FROM guides WHERE id=?', (draft['id'],)).fetchone()[0])
            raw_draft['step'] = raw_draft.pop('steps')[0]
            db.execute('UPDATE guides SET document=? WHERE id=?', (json.dumps(raw_draft), draft['id']))
            raw_pub = json.loads(db.execute('SELECT document FROM revisions WHERE share_id=?', (pub['share_id'],)).fetchone()[0])
            raw_pub['step'] = raw_pub.pop('steps')[0]
            original = json.dumps(raw_pub)
            db.execute('UPDATE revisions SET document=? WHERE share_id=?', (original, pub['share_id']))
        loaded = self.client.get('/api/guides/' + draft['id']).json()
        self.assertEqual(len(loaded['steps']), 1)
        public = self.client.get('/api/learn/' + pub['share_id']).json()
        self.assertEqual(public['step']['instruction'], raw_pub['step']['instruction'])
        self.assertEqual(public['steps'][0]['id'], 'step-1')
        self.assertEqual(self.client.get('/api/learn/' + pub['share_id'] + '/photo').status_code, 200)
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT document FROM revisions WHERE share_id=?', (pub['share_id'],)).fetchone()[0], original)

    def test_failed_step_keeps_successful_steps_and_can_be_retried(self):
        draft = self.six_steps()
        calls = []
        def fail_third(photo, data, title, goal, note):
            calls.append(note)
            if note == '3단계 행동 메모':
                raise VisionError('timeout', '시간 초과')
            return fixture_generator(photo, data, title, goal, note)
        app = create_app(self.temp.name, author_password='test-password', generator=fail_third)
        with TestClient(app) as client:
            client.post('/api/session', json={'password': 'test-password'})
            for i in range(1, 4):
                response = client.post(f"/api/guides/{draft['id']}/steps/step-{i}/generate", json={'version': draft['version']})
                if i < 3:
                    self.assertEqual(response.status_code, 200); draft = response.json()
                else:
                    self.assertEqual(response.status_code, 502)
            saved = client.get('/api/guides/' + draft['id']).json()
            self.assertEqual([bool(s['instruction']) for s in saved['steps']], [True, True, False, False, False, False])
            retry = client.post(f"/api/guides/{draft['id']}/steps/step-4/generate", json={'version': saved['version']})
            self.assertEqual(retry.status_code, 200, 'Failure must release the in-flight lock')
        self.assertEqual(len(calls), 4)

    def test_global_changes_reset_every_review_and_empty_guide_cannot_publish(self):
        blank = self.client.post('/api/guides', json={'title': '빈 안내서'}).json()
        self.assertEqual(self.client.post('/api/guides/' + blank['id'] + '/publish', json={'version': blank['version']}).status_code, 422)
        draft = self.six_steps(generated=True)
        for step in draft['steps']:
            step['reviewed'] = True
        draft = self.save(draft).json()
        draft['goal'] = '모든 단계에 적용되는 새 목표'
        draft = self.save(draft).json()
        self.assertFalse(any(s['reviewed'] for s in draft['steps']))


if __name__ == '__main__':
    unittest.main()
