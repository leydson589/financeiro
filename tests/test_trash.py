import test_app
from app import app, db

class TrashTests(test_app.FinanceTest):
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def test_restore_permissions_balances_and_reports(self):
        self.login()
        self.post('/wallet',type='account',name='Conta de teste',opening='100')
        with app.app_context(): aid=db().execute('SELECT id FROM accounts').fetchone()[0]
        self.post('/entries',amount='40',kind='expense',description='Compra recuperável',category='Lazer',day='2026-10-27',account_id=aid)
        with app.app_context(): eid=db().execute('SELECT id FROM entries').fetchone()[0]
        self.assertEqual(self.post(f'/entries/{eid}/delete').status_code,302)
        self.assertIn(b'100,00',self.client.get('/wallet').data)
        self.assertNotIn('Compra recuperável'.encode(),self.client.get('/export.csv?month=2026-10').data)
        self.assertIn('Compra recuperável'.encode(),self.client.get('/trash').data)
        self.assertEqual(self.client.get(f'/entries/{eid}/edit').status_code,404)
        with self.client.session_transaction() as s:s['uid']=2
        self.assertEqual(self.post(f'/entries/{eid}/restore').status_code,404)
        with self.client.session_transaction() as s:s['uid']=1
        self.assertEqual(self.post(f'/entries/{eid}/restore').status_code,302)
        self.assertIn(b'60,00',self.client.get('/wallet').data)
        self.assertIn('Compra recuperável'.encode(),self.client.get('/export.csv?month=2026-10').data)
        self.assertEqual(self.post(f'/entries/{eid}/restore').status_code,404)
    def test_recurring_not_regenerated_while_in_trash(self):
        self.login()
        self.post('/recurring',description='Internet',amount='100',category='Moradia',day='5',start='2026-10')
        self.post('/recurring/generate',month='2026-10')
        with app.app_context(): eid=db().execute('SELECT id FROM entries').fetchone()[0]
        self.post(f'/entries/{eid}/delete')
        self.post('/recurring/generate',month='2026-10')
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
            self.assertEqual(db().execute('SELECT COUNT(*) FROM active_entries').fetchone()[0],0)
    def test_restore_into_paid_invoice_is_blocked(self):
        self.login()
        self.post('/wallet',type='card',name='Cartão',closing='20',due='28')
        self.post('/wallet',type='account',name='Banco',opening='1000')
        with app.app_context():
            cid=db().execute('SELECT id FROM cards').fetchone()[0]; aid=db().execute('SELECT id FROM accounts').fetchone()[0]
        for label in ['Excluída','Ativa']:
            self.post('/entries',amount='20',kind='expense',description=label,category='Lazer',day='2026-10-01',card_id=cid)
        with app.app_context(): eid=db().execute('SELECT MIN(id) FROM entries').fetchone()[0]
        self.post(f'/entries/{eid}/delete')
        self.post('/invoices/pay',card_id=cid,account_id=aid,month='2026-10',day='2026-10-28')
        self.assertEqual(self.post(f'/entries/{eid}/restore').status_code,409)
