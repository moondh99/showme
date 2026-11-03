import os
import shlex
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import test_app as fixtures
from showme.app import create_app
from showme.deployment import hosted_settings, public_origin
from showme.store import Store


class ConfigurationTests(unittest.TestCase):
    def test_hosted_config_requires_exact_https_origin_secrets_volume_and_positive_budget(self):
        valid = {'SHOWME_PUBLIC_ORIGIN':'https://showme.example.com', 'SHOWME_DATA_DIR':'/data',
                 'SHOWME_AUTHOR_PASSWORD':'test-password-long', 'MODEL_API_KEY':'fixture'}
        self.assertEqual(hosted_settings(valid)['daily_limit'],40)
        for key, value in [('SHOWME_PUBLIC_ORIGIN',''),('SHOWME_DATA_DIR','state'),
                           ('SHOWME_AUTHOR_PASSWORD','short'),('MODEL_API_KEY',''),
                           ('SHOWME_AI_DAILY_LIMIT','0')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                hosted_settings(dict(valid,**{key:value}))
        for value in ['http://showme.example.com','https://*.example.com',
                      'https://user:password@example.com','https://example.com/path',
                      'https://example.com?key=secret','https://example.com#fragment']:
            with self.subTest(value=value), self.assertRaises(ValueError):public_origin(value)

    def test_only_configured_host_is_added_and_session_is_secure_behind_https_proxy(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'SHOWME_PUBLIC_ORIGIN':'https://showme.example.com'}):
            app=create_app(directory,author_password='test-password')
            with TestClient(app,base_url='https://showme.example.com') as client:
                reply=client.post('/api/session',json={'password':'test-password'})
                self.assertEqual(reply.status_code,200)
                self.assertIn('Secure',reply.headers['set-cookie'])
                self.assertIn('HttpOnly',reply.headers['set-cookie'])
                self.assertEqual(client.get('/api/health').status_code,200)
                self.assertEqual(client.get('/api/health',headers={'host':'unrelated.example.com'}).status_code,400)
                self.assertEqual(client.post('/api/session',headers={'origin':'https://unrelated.example.com'},json={'password':'test-password'}).status_code,403)

    def test_budget_is_atomic_persists_restart_and_rolls_over_by_utc_day(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with ThreadPoolExecutor(max_workers=8) as pool:
                granted=list(pool.map(lambda _:store.reserve_ai_request(3),range(8)))
            self.assertEqual(granted.count(True),3)
            self.assertFalse(Store(directory).reserve_ai_request(3))
            with patch('showme.store.time.strftime',return_value='2099-01-01'):
                self.assertTrue(Store(directory).reserve_ai_request(3))


class BudgetAPITests(unittest.TestCase):
    setUp=fixtures.AppTests.setUp
    tearDown=fixtures.AppTests.tearDown
    generated=fixtures.AppTests.generated
    guide_with_photo=fixtures.AppTests.guide_with_photo
    save=fixtures.AppTests.save
    approve=fixtures.AppTests.approve

    def test_exhausted_budget_blocks_generation_selection_and_question_before_provider_but_keeps_reading(self):
        draft,pub=self.approve(self.generated())
        self.app.state.store.reserve_ai_request(1)
        with patch.dict(os.environ,{'SHOWME_AI_DAILY_LIMIT':'1'}):
            def forbidden(*args,**kwargs):self.fail('Exhausted budget must never call a model')
            app=create_app(self.temp.name,author_password='test-password',generator=forbidden,answerer=forbidden,segmenter=forbidden)
        with TestClient(app) as client:
            client.post('/api/session',json={'password':'test-password'})
            for path,payload in [(f"/api/guides/{draft['id']}/steps/step-1/generate",{'version':draft['version']}),
                (f"/api/learn/{pub['share_id']}/questions",{'step_id':'step-1','question':'사용해도 되나요?'}),
                (f"/api/learn/{pub['share_id']}/selections",{'step_id':'step-1','point':{'x':500,'y':500}})]:
                with self.subTest(path=path):self.assertEqual(client.post(path,json=payload).status_code,429)
            self.assertEqual(client.get('/api/learn/'+pub['share_id']).status_code,200)


class PackagedAssetsTests(unittest.TestCase):
    def test_sample_photo_and_public_demo_work_using_only_docker_copy_assets(self):
        # Reproduce the shipped file tree rather than accidentally using checkout-only assets.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as package, tempfile.TemporaryDirectory() as data:
            package = Path(package)
            for line in (root / 'Dockerfile').read_text().splitlines():
                if not line.startswith('COPY '):
                    continue
                _, source, destination = shlex.split(line)
                src, dest = root / source, package / destination.removeprefix('./')
                if src.is_dir():
                    shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__'))
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
            # The allowlist must admit both the ancestors and the shipped sample.
            allowed = (root / '.dockerignore').read_text().splitlines()
            for item in ['!public/', '!public/demo/', '!public/demo/sample-notepad.jpg']:
                self.assertIn(item, allowed)
            with patch('showme.app.ROOT', package):
                app = create_app(data, author_password='test-password')
                from showme.demo import seed_demo
                url = seed_demo(app.state.store, package / 'public/demo/reception-setup')
                with TestClient(app) as client:
                    self.assertEqual(client.post('/api/photos/sample').status_code, 401)
                    client.post('/api/session', json={'password':'test-password'})
                    result = client.post('/api/photos/sample')
                    self.assertEqual(result.status_code, 200, result.text)
                    photo = client.get('/api/photos/' + result.json()['id'])
                    self.assertEqual(photo.status_code, 200)
                    self.assertEqual(photo.headers['content-type'], 'image/jpeg')
                    public = client.get('/api' + url)
                    self.assertEqual(public.status_code, 200)
                    self.assertEqual(len(public.json()['steps']), 4)
                    storage_tags = seed_demo(app.state.store, package / 'public/demo/reception-setup', scenario='storage-tags')
                    response = client.get('/api' + storage_tags)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(response.json()['steps']), 1)
                    self.assertEqual(client.get('/static/research/sam-probe.html').status_code, 404)
