import test_app
from app import app,db

class RecurringEditTests(test_app.FinanceTest):
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def test_rule_edits_preserve_history_and_copy_division(self):
        self.login()
        self.post('/recurring',description='Internet',amount='100',day=31,start='2026-10',category='Moradia',expense_scope='shared',paid_by=1,split_with=2,payer_percent=60)
        with app.app_context(): rid=db().execute('SELECT id FROM recurring').fetchone()[0]
        self.post('/recurring/generate',month='2026-10')
        self.assertEqual(self.client.get(f'/recurring/{rid}/edit').status_code,200)
        self.assertEqual(self.post(f'/recurring/{rid}/edit',description='Internet nova',amount='120',day=31,start='2026-10',category='Moradia',active='1',expense_scope='shared',paid_by=2,split_with=1,payer_percent=70).status_code,302)
        self.post('/recurring/generate',month='2026-10'); self.post('/recurring/generate',month='2026-11')
        with app.app_context():
            rows=db().execute('SELECT * FROM entries ORDER BY day').fetchall()
            self.assertEqual(len(rows),2); self.assertEqual([r['amount'] for r in rows],[10000,12000])
            self.assertEqual([r['payer_percent'] for r in rows],[60,70]); self.assertEqual(rows[1]['day'],'2026-11-30')
            self.assertEqual(rows[1]['paid_by'],2)
    def test_owner_and_reactivation(self):
        self.login(); self.post('/recurring',description='Teste',amount='10',day=1,start='2026-10',category='Outros')
        with app.app_context():rid=db().execute('SELECT id FROM recurring').fetchone()[0]
        with self.client.session_transaction() as s:s['uid']=2
        self.assertEqual(self.client.get(f'/recurring/{rid}/edit').status_code,404)
        with self.client.session_transaction() as s:s['uid']=1
        self.post(f'/recurring/{rid}/stop'); self.post('/recurring/generate',month='2026-11')
        with app.app_context(): self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],0)
        self.post(f'/recurring/{rid}/edit',description='Teste',amount='10',day=1,start='2026-10',category='Outros',active='1')
        self.post('/recurring/generate',month='2026-11')
        with app.app_context(): self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
