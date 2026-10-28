"""Inicia o ambiente local, com dados persistentes e contas de teste."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
data = root / 'data'
data.mkdir(exist_ok=True)
key = data / '.local-secret'
if not key.exists():
    key.write_text(secrets.token_hex(32))
    key.chmod(0o600)
os.environ['SECRET_KEY'] = key.read_text().strip()
os.environ['COOKIE_SECURE'] = 'false'
os.environ['DATABASE_PATH'] = str(data / 'financeiro.db')
from app import app, db, generate_password_hash

with app.app_context():
    for name, email, password in [
        ('Você', 'voce@example.com', 'TesteLocal-2026!'),
        ('Esposa', 'esposa@example.com', 'TesteCasal-2026!'),
    ]:
        if not db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
            db().execute('INSERT INTO users(name,email,password) VALUES(?,?,?)',
                         (name, email, generate_password_hash(password)))
    db().commit()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5055, debug=False)
