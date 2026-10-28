from test_app import FinanceTest
from app import app, db

class FinancialFlows(FinanceTest):
    def setUp(self):
        with app.app_context():
            for table in ['transfers','invoice_payments','recurring','entries','cards','accounts']:
                db().execute(f'DELETE FROM {table}')
            db().commit()
        super().setUp()
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def test_installments_invoice_and_payment(self):
        self.login()
        self.post('/wallet',type='account',name='Banco',opening='1000')
        self.post('/wallet',type='card',name='Cartão',closing='20',due='28')
        with app.app_context():
            account=db().execute('SELECT id FROM accounts').fetchone()[0]
            card=db().execute('SELECT id FROM cards').fetchone()[0]
        result=self.post('/entries',amount='100.00',kind='expense',category='Lazer',description='Compra',day='2026-10-20',card_id=card,installments='3')
        self.assertEqual(result.status_code,302)
        with app.app_context():
            rows=db().execute('SELECT * FROM entries ORDER BY id').fetchall()
            self.assertEqual([r['amount'] for r in rows],[3334,3333,3333])
            self.assertEqual([r['invoice_month'] for r in rows],['2026-11','2026-12','2027-01'])
            entry_id=rows[0]['id']
        self.assertIn(b'33,34',self.client.get('/?month=2026-11').data)
        for i in range(2): self.post('/invoices/pay',card_id=card,account_id=account,month='2026-11',day='2026-11-28')
        with app.app_context():
            self.assertEqual(db().execute('SELECT SUM(amount) FROM transfers').fetchone()[0],3334)
        self.assertIn(b'966,66',self.client.get('/wallet').data)
        self.assertEqual(self.post(f'/entries/{entry_id}/delete').status_code,409)
    def test_recurring_idempotence_and_short_month(self):
        self.login()
        self.assertEqual(self.post('/recurring',description='Internet',amount='99.90',category='Moradia',day='31',start='2026-01').status_code,302)
        for i in range(2): self.post('/recurring/generate',month='2026-02')
        with app.app_context():
            rows=db().execute('SELECT * FROM entries').fetchall()
            self.assertEqual(len(rows),1); self.assertEqual(rows[0]['day'],'2026-02-28')
            rule=db().execute('SELECT id FROM recurring').fetchone()[0]
        self.post(f'/recurring/{rule}/stop')
        self.post('/recurring/generate',month='2026-03')
        with app.app_context(): self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
    def test_edit_permissions(self):
        self.login()
        self.post('/entries',amount='10',kind='expense',category='Outros',description='Teste',day='2026-10-01')
        with app.app_context(): eid=db().execute('SELECT id FROM entries').fetchone()[0]
        self.assertEqual(self.post(f'/entries/{eid}/edit',amount='15.50',description='Alterado',category='Saúde',day='2026-10-02').status_code,302)
        with self.client.session_transaction() as s: s['uid']=2
        self.assertEqual(self.client.get(f'/entries/{eid}/edit').status_code,404)
        for page in ['/wallet','/recurring','/']:
            self.assertEqual(self.client.get(page).status_code,200)
