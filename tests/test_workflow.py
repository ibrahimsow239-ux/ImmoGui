"""Tests HTTP avec deux comptes isolés et une base jetable."""
import copy
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from domain import normalize, rent_for_month


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='immogui-tests-')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{cls.port}'
        env = {k: v for k, v in os.environ.items() if not k.startswith('IMMOGUI_ACCOUNT_IMPORT')}
        env.update(HOST='127.0.0.1', PORT=str(cls.port), APP_ENV='development', DATABASE_PATH=cls.tmp.name+'/test.sqlite3')
        cls.log = open(cls.tmp.name+'/server.log', 'w')
        cls.process = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base+'/api/health', timeout=1).close()
                return
            except OSError:
                if cls.process.poll() is not None:
                    raise RuntimeError('Le serveur a quitté : '+Path(cls.tmp.name+'/server.log').read_text())
                time.sleep(.05)
        cls.tearDownClass()
        raise RuntimeError('Démarrage du serveur trop long')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    def client(self, email):
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.request(client, 'signup', {'name':'Partenaire de test', 'email':email, 'password':'mot-de-passe-de-test'})
        return client

    def request(self, client, path, data=None, expected=200):
        request = urllib.request.Request(self.base+'/api/'+path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Origin':self.base, 'Content-Type':'application/json'})
        try:
            response = client.open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expected, response.status)
            content = response.read()
            return content if response.headers.get_content_type() == 'application/pdf' else json.loads(content)

    def test_accounts_receipts_and_restore(self):
        alice = self.client('alice@example.invalid')
        bob = self.client('bob@example.invalid')
        data = {'properties':[{'id':'p','name':'Immeuble témoin','address':'Conakry','units':2,'type':'Appartements'}],
                'tenants':[{'id':'t','name':'Locataire témoin','phone':'620000000','property':'p','unit':'A01','rent':1000,'leaseStart':'2026-01-15'}],
                'payments':[], 'expenses':[]}
        result = self.request(alice, 'data', data)
        data = result['data']
        self.assertEqual(data['tenants'][0]['trackingStart'], '2026-01')
        data['payments'].append({'id':'versement-1','tenant':'t','amount':400,'date':'2026-01-16','month':'2026-01'})
        data = self.request(alice, 'data', data)['data']
        document = self.request(alice, 'backup')
        first_pdf = self.request(alice, 'receipts/versement-1')
        self.assertTrue(first_pdf.startswith(b'%PDF-1.4'))
        self.assertIn(b'Paiement partiel', first_pdf)
        self.assertIn(b'600 GNF', first_pdf)
        pdf = Path(self.tmp.name)/'receipt.pdf'
        pdf.write_bytes(first_pdf)
        text = subprocess.check_output(['pdftotext', str(pdf), '-']).decode()
        self.assertIn('Locataire témoin', text)
        self.assertIn('400 GNF', text)
        data['payments'].append({'id':'versement-2','tenant':'t','amount':600,'date':'2026-01-17','month':'2026-01'})
        data = self.request(alice, 'data', data)['data']
        self.assertEqual(self.request(alice, 'receipts/versement-1'), first_pdf)
        self.assertEqual(data['payments'][1]['receipt']['remaining'], 0)
        self.assertNotIn(b'Paiement partiel', self.request(alice, 'receipts/versement-2'))
        self.request(bob, 'receipts/versement-1', expected=404)
        self.request(urllib.request.build_opener(), 'receipts/versement-1', expected=401)
        # Les paiements ne peuvent pas être réécrits par une sauvegarde normale.
        changed = copy.deepcopy(data)
        changed['payments'][0]['amount'] = 200
        self.request(alice, 'data', changed, expected=400)
        changed = copy.deepcopy(data)
        changed['tenants'][0]['rentHistory'][0]['amount'] = 900
        changed['tenants'][0]['rent'] = 900
        self.request(alice, 'data', changed, expected=400)
        overpaid = copy.deepcopy(data)
        overpaid['payments'].append({'id':'too-much','tenant':'t','amount':1,'date':'2026-01-18','month':'2026-01'})
        self.request(alice, 'data', overpaid, expected=400)
        reordered = copy.deepcopy(data)
        reordered['payments'].reverse()
        self.request(alice, 'data', reordered, expected=400)
        # Un tarif futur conserve janvier et possède son mois d'effet.
        data['tenants'][0]['rent'] = 2000
        data['tenants'][0]['rentHistory'].append({'month':'2026-11','amount':2000})
        data = self.request(alice, 'data', data)['data']
        self.assertEqual(rent_for_month(data['tenants'][0], '2026-01'), 1000)
        self.assertEqual(rent_for_month(data['tenants'][0], '2026-11'), 2000)
        # Une sauvegarde ou un identifiant d'un autre compte ne donne aucun accès.
        versions = self.request(alice, 'backups')['backups']
        self.request(bob, 'restore', document, expected=400)
        self.request(bob, 'restore', {'backupId':versions[0]['id']}, expected=404)
        invalid = copy.deepcopy(document)
        invalid['data']['payments'][0]['tenant'] = 'inexistant'
        self.request(alice, 'restore', invalid, expected=400)
        self.assertEqual(len(self.request(alice, 'me')['data']['payments']), 2)
        self.request(alice, 'restore', document)
        self.assertEqual(len(self.request(alice, 'me')['data']['payments']), 1)
        self.assertEqual(self.request(bob, 'me')['data'], {'properties':[], 'tenants':[], 'payments':[], 'expenses':[]})
        before_restore = self.request(alice, 'backups')['backups'][0]
        self.assertEqual(before_restore['reason'], 'before-restore')
        self.request(alice, 'restore', {'backupId':before_restore['id']})
        self.assertEqual(len(self.request(alice, 'me')['data']['payments']), 2)
        self.request(alice, 'forgot-password', {'email':'alice@example.invalid'}, expected=503)
        self.request(alice, 'verify-email', {}, expected=503)

    def test_legacy_migration_is_saved_once(self):
        client = self.client('legacy@example.invalid')
        legacy = {'properties':[{'id':'p','name':'Bien ancien','address':'Conakry','type':'Maison','units':1}],
                  'tenants':[{'id':'t','name':'Locataire existant','property':'p','rent':1000}],
                  'payments':[{'id':'old-payment','tenant':'t','amount':500,'date':'2024-08-05','month':'2024-08'}],
                  'expenses':[]}
        with sqlite3.connect(self.tmp.name+'/test.sqlite3') as db:
            db.execute('UPDATE users SET data=? WHERE email=?', (json.dumps(legacy), 'legacy@example.invalid'))
        migrated = self.request(client, 'me')['data']
        self.assertNotIn('leaseStart', migrated['tenants'][0])
        self.assertEqual(migrated['tenants'][0]['trackingStart'], '2024-08')
        self.assertEqual(migrated['payments'], legacy['payments'])
        self.assertEqual(self.request(client, 'me')['data'], migrated)
        backups = self.request(client, 'backups')['backups']
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]['reason'], 'migration')
        # L'édition d'un ancien locataire sans téléphone ni numéro reste possible.
        migrated['tenants'][0]['phone'] = ''
        migrated['tenants'][0]['unit'] = ''
        self.request(client, 'data', migrated)

    def test_whole_month_and_legacy_tracking(self):
        t = {'rent':3100,'trackingStart':'2026-01','leaseStart':'2026-01-31','leaseEnd':'2026-02-01'}
        self.assertEqual(rent_for_month(t, '2026-01'), 3100)
        self.assertEqual(rent_for_month(t, '2026-02'), 3100)
        self.assertEqual(rent_for_month(t, '2026-03'), 0)
        old = {'properties':[], 'tenants':[{'id':'t','rent':1000}], 'payments':[{'tenant':'t','month':'2024-08','amount':500}], 'expenses':[]}
        migrated = normalize(old, today='2026-10-29')
        self.assertNotIn('leaseStart', migrated['tenants'][0])
        self.assertEqual(migrated['tenants'][0]['trackingStart'], '2024-08')
        self.assertEqual(migrated['payments'], old['payments'])
        self.assertEqual(normalize(migrated, today='2028-01-01'), migrated)
        self.assertEqual(rent_for_month(migrated['tenants'][0], '2024-07'), 0)


if __name__ == '__main__':
    unittest.main()
