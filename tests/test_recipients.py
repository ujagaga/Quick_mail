"""Run with: python -m unittest discover -s tests -v"""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
import unittest
from unittest.mock import patch


class RecipientHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = ModuleType('config')
        for name, value in dict(
            SMTP_SERVER='localhost', SMTP_PORT=25, SMTP_USER='sender@example.com',
            SMTP_PASS='', DB_FILE=str(Path(self.temp.name) / 'users.db'),
            ADMIN_EMAIL='admin@example.com', MIN_WAIT_TIME=120,
            FLASK_APP_SECRET_KEY='test', CLIENT_SECRETS_FILE='missing-test-oauth.json',
            USE_MANUAL_OAUTH=True,
        ).items():
            setattr(config, name, value)
        self.modules = patch.dict(sys.modules, {'config': config})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        root = Path(__file__).resolve().parents[1]
        for name in ('helper', 'index'):
            spec = importlib.util.spec_from_file_location(name, root / f'{name}.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        self.mail = patch.object(self.helper, 'send_email').start()
        self.addCleanup(patch.stopall)
        self.helper.init_db()
        self.helper.add_user('user@example.com', 'token')
        self.helper.update_user('user@example.com', status='guest')
        self.user = self.helper.get_user_from_db(token='token')
        self.index.app.config.update(TESTING=True)
        self.client = self.index.app.test_client()
        self.delivery = patch.object(self.index, 'send_email').start()

    def send(self, recipients, method='post'):
        with sqlite3.connect(self.helper.DB_FILE) as conn:
            conn.execute('UPDATE users SET timestamp = 0')
        fields = dict(token='token', to=recipients, sub='Subject', msg='Message')
        if method == 'get':
            return self.client.get('/send', query_string=fields)
        return self.client.post('/send', data=fields)

    def count(self):
        return self.helper.get_user_from_db(token='token')['recipient_count']

    def test_limit_allows_tenth_and_existing_but_refuses_eleventh(self):
        self.assertEqual(self.send(','.join(f'r{i}@example.com' for i in range(9))).status_code, 200)
        self.assertEqual(self.send('r9@example.com', 'get').status_code, 200)
        self.assertEqual(self.count(), 10)
        self.delivery.reset_mock()
        self.assertEqual(self.send('r0@example.com,new@example.com').status_code, 403)
        self.delivery.assert_not_called()
        self.assertEqual(self.count(), 10)
        self.assertEqual(self.send('R0@example.com').status_code, 200)
        self.assertEqual(self.count(), 10)

    def test_batch_is_atomic_and_addresses_are_deduplicated(self):
        self.assertEqual(self.send(','.join(f'r{i}@example.com' for i in range(11))).status_code, 403)
        self.assertEqual(self.count(), 0)
        self.delivery.assert_not_called()
        self.assertEqual(self.send(' A@example.com,a@example.com,invalid').status_code, 200)
        self.assertEqual(self.count(), 1)
        self.delivery.assert_called_once()
        self.assertEqual(self.send('invalid').status_code, 400)
        self.assertEqual(self.count(), 1)

    def test_accounts_are_independent_and_delete_cleans_history(self):
        self.helper.reserve_recipients(self.user['id'], ['one@example.com'])
        self.helper.add_user('other@example.com', 'other')
        other = self.helper.get_user_from_db(email='other@example.com', include_pending=True)
        self.assertEqual(other['recipient_count'], 0)
        self.helper.delete_user(self.user['email'])
        with sqlite3.connect(self.helper.DB_FILE) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM user_recipients').fetchone()[0], 0)

    def test_concurrent_reservations_cannot_exceed_limit(self):
        self.helper.reserve_recipients(self.user['id'], [f'r{i}@example.com' for i in range(9)])
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda address: self.helper.reserve_recipients(self.user['id'], [address]),
                ['a@example.com', 'b@example.com'],
            ))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.count(), 10)

    def test_migration_preserves_users_and_history_survives_reinitialization(self):
        with sqlite3.connect(self.helper.DB_FILE) as conn:
            conn.execute('DROP TABLE user_recipients')
        self.helper.init_db()
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.helper.get_user_from_db(token='token')['id'], self.user['id'])
        self.helper.reserve_recipients(self.user['id'], ['one@example.com'])
        self.helper.init_db()
        self.assertEqual(self.count(), 1)

    def test_admin_reset_clears_only_selected_account_and_restores_capacity(self):
        self.helper.reserve_recipients(self.user['id'], [f'r{i}@example.com' for i in range(10)])
        admin = self.helper.get_user_from_db(email='admin@example.com')
        self.helper.reserve_recipients(admin['id'], ['admin-recipient@example.com'])
        before = self.helper.get_user_from_db(token='token')
        with self.client.session_transaction() as session:
            session['email'] = admin['email']
        self.assertIn(b'Reset recipients', self.client.get('/admin').data)
        with self.client.session_transaction() as session:
            csrf = session['admin_csrf_token']
        response = self.client.post('/admin', data=dict(
            cmd='reset_recipients', email=self.user['email'], csrf_token=csrf,
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'0 / 10', response.data)
        after = self.helper.get_user_from_db(token='token')
        for field in ('token', 'status', 'timestamp'):
            self.assertEqual(before[field], after[field])
        self.assertEqual(self.helper.get_user_from_db(email=admin['email'])['recipient_count'], 1)
        self.assertEqual(self.send('new@example.com').status_code, 200)

    def test_reset_requires_admin_and_valid_form_token(self):
        self.helper.reserve_recipients(self.user['id'], ['one@example.com'])
        fields = dict(cmd='reset_recipients', email=self.user['email'])
        self.assertEqual(self.client.post('/admin', data=fields).status_code, 302)
        with self.client.session_transaction() as session:
            session['email'] = self.user['email']
        self.assertEqual(self.client.post('/admin', data=fields).status_code, 302)
        with self.client.session_transaction() as session:
            session['email'] = 'admin@example.com'
        self.assertEqual(self.client.post('/admin', data=fields).status_code, 400)
        self.client.get('/admin', query_string=fields)
        self.assertEqual(self.count(), 1)

    def test_admin_displays_count(self):
        self.helper.reserve_recipients(self.user['id'], ['one@example.com', 'two@example.com'])
        with self.client.session_transaction() as session:
            session['email'] = 'admin@example.com'
        response = self.client.get('/admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Recipients used', response.data)
        self.assertIn(b'2 / 10', response.data)


if __name__ == '__main__':
    unittest.main()
