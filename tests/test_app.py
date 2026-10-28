import os, tempfile, unittest
os.environ['SECRET_KEY'] = 'test-key-' * 8
os.environ['COOKIE_SECURE'] = 'false'
TEMP = tempfile.TemporaryDirectory()
os.environ['DATABASE_PATH'] = TEMP.name + '/test.db'
from app import app, db, generate_password_hash

class FinanceTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            for table in ['audit','settlements','contributions','goals','budgets','transfers','invoice_payments','recurring','entries','cards','accounts','users','attempts']:
                db().execute(f'DELETE FROM {table}')
            db().execute('INSERT INTO users(id,name,email,password) VALUES(1,?,?,?)',('Pessoa 1','um@example.com',generate_password_hash('senha-segura-123')))
            db().execute('INSERT INTO users(id,name,email,password) VALUES(2,?,?,?)',('Pessoa 2','dois@example.com',generate_password_hash('outra-senha-123')))
            db().commit()
    def login(self):
        self.client.get('/login')
        with self.client.session_transaction() as s: token=s['csrf']
        return self.client.post('/login',data={'csrf':token,'email':'um@example.com','password':'senha-segura-123'})
    def token(self):
        with self.client.session_transaction() as s: return s['csrf']
    def test_auth_and_csrf(self):
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.client.post('/entries',data={}).status_code,400)
        self.assertEqual(self.login().status_code,302)
        self.assertEqual(self.client.get('/').status_code,200)
    def test_money_and_owner(self):
        self.login()
        payload=dict(csrf=self.token(),amount='123.45',day='2026-10-27',description='Mercado',kind='expense',category='Alimentação')
        self.assertEqual(self.client.post('/entries',data=payload).status_code,302)
        with app.app_context():
            row=db().execute('SELECT * FROM entries').fetchone(); self.assertEqual(row['amount'],12345); entry_id=row['id']
        with self.client.session_transaction() as s: s['uid']=2
        self.assertEqual(self.client.post(f'/entries/{entry_id}/delete',data={'csrf':self.token()}).status_code,404)
        with app.app_context(): self.assertEqual(db().execute('SELECT count(*) FROM entries').fetchone()[0],1)
        with self.client.session_transaction() as s: s['uid']=1
        self.client.post(f'/entries/{entry_id}/delete',data={'csrf':self.token()})
        with app.app_context(): self.assertEqual(db().execute('SELECT count(*) FROM active_entries').fetchone()[0],0)
        payload['amount']='NaN'; self.assertEqual(self.client.post('/entries',data=payload).status_code,400)
    def test_login_throttle(self):
        self.client.get('/login')
        for i in range(8): self.client.post('/login',data=dict(csrf=self.token(),email='um@example.com',password='errada'))
        self.assertEqual(self.client.post('/login',data=dict(csrf=self.token(),email='um@example.com',password='errada')).status_code,429)

if __name__ == '__main__': unittest.main()
