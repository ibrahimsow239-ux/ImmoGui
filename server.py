"""Serveur local immoGui : python3 server.py."""
import hashlib
import base64
import zlib
import hmac
import json
import os
from urllib.parse import urlsplit, unquote, parse_qs
import secrets
import sqlite3
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie
from domain import normalize, prepare_update, backup_document, restore_document, receipt_details, receipt_pdf

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('DATABASE_PATH', str(ROOT / 'immogui.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)
PRODUCTION = os.environ.get('APP_ENV') == 'production'
COOKIE_SECURITY = '; Secure' if PRODUCTION else ''
EMPTY = {k: [] for k in ('properties', 'tenants', 'payments', 'expenses')}

def connect():
    db = sqlite3.connect(DB)
    db.execute('PRAGMA foreign_keys=ON')
    return db

with connect() as db:
    db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL, data TEXT NOT NULL)')
    if 'role' not in {row[1] for row in db.execute('PRAGMA table_info(users)')}:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'partner'")
    db.execute('CREATE TABLE IF NOT EXISTS auth_attempts (key TEXT, created INTEGER)')
    db.execute('CREATE INDEX IF NOT EXISTS auth_attempts_lookup ON auth_attempts(key,created)')
    db.execute('CREATE TABLE IF NOT EXISTS backups (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created INTEGER NOT NULL, reason TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS backups_by_user ON backups(user_id,created)')
    db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL)')

def import_account_from_environment():
    payload = os.environ.get('IMMOGUI_ACCOUNT_IMPORT', '')
    if not payload:
        payload = ''.join(os.environ.get('IMMOGUI_ACCOUNT_IMPORT_' + str(i), '') for i in range(1, 17))
    if not payload:
        return
    source = json.loads(zlib.decompress(base64.b64decode(payload, validate=True)))
    if set(source) != {'name', 'email', 'salt', 'password', 'data', 'role'}:
        raise ValueError('Invalid account import')
    if source['role'] not in ('admin', 'partner') or not isinstance(json.loads(source['data']), dict):
        raise ValueError('Invalid imported account')
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS account_imports (fingerprint TEXT PRIMARY KEY)')
        if db.execute('SELECT 1 FROM account_imports WHERE fingerprint=?', (fingerprint,)).fetchone():
            print('Account import already completed.', flush=True)
            return
        if db.execute('SELECT 1 FROM users WHERE lower(email)=?', (source['email'].lower(),)).fetchone():
            raise ValueError('Account import refused: email already exists; no data changed')
        backup = sqlite3.connect(str(DB) + '.before-account-import')
        try:
            # A separate read connection avoids backing up an active write transaction.
            with connect() as original:
                original.backup(backup)
        finally:
            backup.close()
        db.execute('INSERT INTO users (name,email,salt,password,data,role) VALUES (?,?,?,?,?,?)',
                   tuple(source[key] for key in ('name','email','salt','password','data','role')))
        db.execute('INSERT INTO account_imports VALUES (?)', (fingerprint,))
    data = json.loads(source['data'])
    print('Account import completed: ' + json.dumps({key: len(data.get(key, [])) for key in EMPTY}), flush=True)

import_account_from_environment()

def snapshot(db, user_id, data, reason):
    db.execute('INSERT INTO backups VALUES (?,?,?,?,?)', (secrets.token_hex(16), user_id, time.time_ns(), reason, data))
    # Cinquante versions par compte, y compris la sauvegarde avant restauration.
    db.execute('DELETE FROM backups WHERE user_id=? AND id NOT IN (SELECT id FROM backups WHERE user_id=? ORDER BY created DESC LIMIT 50)', (user_id, user_id))


def account_data(user_id):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        raw = db.execute('SELECT data FROM users WHERE id=?', (user_id,)).fetchone()[0]
        data = normalize(json.loads(raw))
        if data != json.loads(raw):
            snapshot(db, user_id, raw, 'migration')
            db.execute('UPDATE users SET data=? WHERE id=?', (json.dumps(data), user_id))
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def reply(self, status, data, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def user(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
            token = cookies['session'].value
        except (KeyError, ValueError):
            return None
        with connect() as db:
            return db.execute('SELECT users.id, name, email, data, role FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()

    def do_HEAD(self):
        if self.path.split('?')[0] not in ('/', '/index.html', '/app.js', '/style.css', '/auth.js', '/assets/residence-immogui.jpg', '/assets/maisons-locatives.jpg'):
            return self.reply(404, {'error': 'Page introuvable.'})
        super().do_HEAD()

    def do_GET(self):
        if self.path == '/api/health':
            return self.reply(200, {'ok': True})
        if urlsplit(self.path).path == '/api/export/monthly.xlsx':
            user = self.user()
            if not user:
                return self.reply(401, {'error': 'Veuillez vous connecter.'})
            month = parse_qs(urlsplit(self.path).query).get('month', [''])[0]
            from excel_export import monthly_workbook
            try:
                content = monthly_workbook(account_data(user[0]), month, user[1])
            except ValueError as error:
                return self.reply(400, {'error': str(error)})
            self.send_response(200)
            self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Content-Disposition', 'attachment; filename="immogui-bilan-' + month + '.xlsx"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path == '/api/admin/users':
            user = self.user()
            if not user:
                return self.reply(401, {'error': 'Veuillez vous connecter.'})
            if user[4] != 'admin':
                return self.reply(403, {'error': 'Accès réservé à l’administrateur.'})
            with connect() as db:
                rows = db.execute('SELECT name,email FROM users ORDER BY id DESC').fetchall()
            return self.reply(200, {'users': [{'name': row[0], 'email': row[1]} for row in rows]})
        if self.path == '/api/me':
            user = self.user()
            return self.reply(200, {'user': {'name': user[1], 'email': user[2], 'role': user[4]}, 'data': account_data(user[0])} if user else {'user': None})
        if self.path in ('/api/backup', '/api/backups') or self.path.startswith('/api/receipts/'):
            user = self.user()
            if not user:
                return self.reply(401, {'error': 'Veuillez vous connecter.'})
            data = account_data(user[0])
            if self.path == '/api/backup':
                return self.reply(200, backup_document(data, user[2]))
            if self.path == '/api/backups':
                with connect() as db:
                    rows = db.execute('SELECT id,created,reason FROM backups WHERE user_id=? ORDER BY created DESC', (user[0],)).fetchall()
                return self.reply(200, {'backups': [{'id': row[0], 'created': row[1] // 1000000, 'reason': row[2]} for row in rows]})
            try:
                payment_id = unquote(self.path[len('/api/receipts/'):])
                receipt = receipt_details(data, payment_id)
            except KeyError:
                return self.reply(404, {'error': 'Paiement introuvable dans votre compte.'})
            content = receipt_pdf(receipt, user[1])
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(content)))
            filename = hashlib.sha256(payment_id.encode()).hexdigest()[:16]
            self.send_header('Content-Disposition', f'attachment; filename="recu-{filename}.pdf"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path.split('?')[0] not in ('/', '/index.html', '/app.js', '/style.css', '/auth.js', '/favicon.ico', '/assets/residence-immogui.jpg', '/assets/maisons-locatives.jpg'):
            return self.reply(404, {'error': 'Page introuvable.'})
        super().do_GET()

    def do_POST(self):
        origin = self.headers.get('Origin')
        expected_host = self.headers.get('Host', '')
        parsed_origin = urlsplit(origin or '')
        if not origin or parsed_origin.netloc != expected_host or parsed_origin.scheme not in (('https',) if PRODUCTION else ('http', 'https')):
            return self.reply(403, {'error': 'Origine non autorisée.'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 15000000:
                return self.reply(413, {'error': 'Requête trop volumineuse.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            return self.reply(400, {'error': 'Données invalides.'})
        if self.path in ('/api/forgot-password', '/api/verify-email'):
            return self.reply(503, {'error': 'L’envoi d’emails n’est pas encore activé. Aucun message n’a été envoyé.'})
        if self.path in ('/api/signup', '/api/login'):
            ip = self.headers.get('X-Forwarded-For', '').split(',')[-1].strip() if PRODUCTION else self.client_address[0]
            key = hashlib.sha256(ip.encode()).hexdigest()
            with connect() as db:
                db.execute('DELETE FROM auth_attempts WHERE created<?', (int(time.time()) - 900,))
                count = db.execute('SELECT COUNT(*) FROM auth_attempts WHERE key=?', (key,)).fetchone()[0]
                if count >= 20:
                    return self.reply(429, {'error': 'Trop de tentatives. Réessayez dans 15 minutes.'})
                db.execute('INSERT INTO auth_attempts VALUES (?,?)', (key, int(time.time())))
            email = str(body.get('email', '')).strip().lower()
            password = str(body.get('password', ''))
            if len(email) > 254 or '@' not in email or not 10 <= len(password) <= 256:
                return self.reply(400, {'error': 'Indiquez un email valide et un mot de passe de 10 à 256 caractères.'})
            with connect() as db:
                if self.path == '/api/signup':
                    name = str(body.get('name', '')).strip()
                    if not 1 <= len(name) <= 100:
                        return self.reply(400, {'error': 'Indiquez votre nom (100 caractères maximum).'})
                    salt = secrets.token_hex(16)
                    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
                    try:
                        cursor = db.execute('INSERT INTO users (name,email,salt,password,data) VALUES (?,?,?,?,?)', (name, email, salt, digest, json.dumps(EMPTY)))
                    except sqlite3.IntegrityError:
                        return self.reply(409, {'error': 'Cet email possède déjà un compte. Connectez-vous.'})
                    user_id = cursor.lastrowid
                else:
                    user = db.execute('SELECT id,salt,password FROM users WHERE email=?', (email,)).fetchone()
                    salt = user[1] if user else 'invalid-account-salt'
                    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
                    if not user or not hmac.compare_digest(digest, user[2]):
                        return self.reply(401, {'error': 'Email ou mot de passe incorrect.'})
                    user_id = user[0]
                token = secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
                db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 86400))
            return self.reply(200, {'ok': True}, f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400' + COOKIE_SECURITY)
        user = self.user()
        if not user:
            return self.reply(401, {'error': 'Veuillez vous reconnecter.'})
        if self.path == '/api/logout':
            with connect() as db:
                db.execute('DELETE FROM sessions WHERE user_id=?', (user[0],))
            return self.reply(200, {'ok': True}, 'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + COOKIE_SECURITY)
        if self.path in ('/api/data', '/api/restore'):
            try:
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    raw = db.execute('SELECT data FROM users WHERE id=?', (user[0],)).fetchone()[0]
                    if self.path == '/api/data':
                        data = prepare_update(body, json.loads(raw))
                        reason = 'automatic'
                    else:
                        if 'backupId' in body:
                            if not isinstance(body['backupId'], str):
                                raise ValueError('Identifiant de sauvegarde invalide.')
                            row = db.execute('SELECT data FROM backups WHERE id=? AND user_id=?', (body['backupId'], user[0])).fetchone()
                            if not row:
                                return self.reply(404, {'error': 'Sauvegarde introuvable dans votre compte.'})
                            document = backup_document(json.loads(row[0]), user[2])
                        else:
                            document = body
                        data = restore_document(document, user[2])
                        reason = 'before-restore'
                    serialized = json.dumps(data)
                    if data != json.loads(raw) or reason == 'before-restore':
                        snapshot(db, user[0], raw, reason)
                        db.execute('UPDATE users SET data=? WHERE id=?', (serialized, user[0]))
            except (ValueError, TypeError, KeyError) as error:
                return self.reply(400, {'error': str(error) if isinstance(error, ValueError) else 'Format de données invalide.'})
            return self.reply(200, {'ok': True, 'data': data})
        self.reply(404, {'error': 'Page introuvable.'})

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    print(f'immoGui : écoute sur {host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
