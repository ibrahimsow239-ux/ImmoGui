"""Serveur local immoGui : python3 server.py."""
import hashlib
import hmac
import json
import os
from urllib.parse import urlsplit
import secrets
import sqlite3
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie

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
    db.execute('CREATE TABLE IF NOT EXISTS auth_attempts (key TEXT, created INTEGER)')
    db.execute('CREATE INDEX IF NOT EXISTS auth_attempts_lookup ON auth_attempts(key,created)')
    db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL)')

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
            return db.execute('SELECT users.id, name, email, data FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()

    def do_HEAD(self):
        if self.path.split('?')[0] not in ('/', '/index.html', '/app.js', '/style.css', '/auth.js', '/assets/residence-immogui.jpg', '/assets/maisons-locatives.jpg'):
            return self.reply(404, {'error': 'Page introuvable.'})
        super().do_HEAD()

    def do_GET(self):
        if self.path == '/api/health':
            return self.reply(200, {'ok': True})
        if self.path == '/api/me':
            user = self.user()
            return self.reply(200, {'user': {'name': user[1], 'email': user[2]}, 'data': json.loads(user[3])} if user else {'user': None})
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
        if self.path == '/api/data':
            if set(body) != set(EMPTY) or not all(isinstance(body[k], list) for k in EMPTY):
                return self.reply(400, {'error': 'Format de données invalide.'})
            with connect() as db:
                db.execute('UPDATE users SET data=? WHERE id=?', (json.dumps(body), user[0]))
            return self.reply(200, {'ok': True})
        self.reply(404, {'error': 'Page introuvable.'})

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    print(f'immoGui : écoute sur {host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
