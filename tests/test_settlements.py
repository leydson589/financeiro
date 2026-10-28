import test_app
from app import app,db

class SettlementTests(test_app.FinanceTest):
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def test_settlement_reduces_balance_and_void_restores(self):
        self.login()
        self.post('/entries',amount='100',kind='expense',description='Compras',category='Outros',day='2026-10-27',expense_scope='shared',paid_by=1,split_with=2,payer_percent=50)
        self.assertIn(b'50,00',self.client.get('/sharing?month=2026-10').data)
        self.assertEqual(self.post('/settlements',sender=2,recipient=1,amount='20',day='2026-11-01',month='2026-10',note='Pix de teste').status_code,302)
        page=self.client.get('/sharing?month=2026-10'); self.assertEqual(page.status_code,200); self.assertIn(b'30,00',page.data)
        with app.app_context():
            sid=db().execute('SELECT id FROM settlements').fetchone()[0]
            self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],1)
        with self.client.session_transaction() as s:s['uid']=2
        self.assertEqual(self.post(f'/settlements/{sid}/void').status_code,404)
        with self.client.session_transaction() as s:s['uid']=1
        self.assertEqual(self.post(f'/settlements/{sid}/void').status_code,302)
        self.assertIn(b'50,00',self.client.get('/sharing?month=2026-10').data)
        self.assertEqual(self.post(f'/settlements/{sid}/void').status_code,404)
        with app.app_context(): self.assertEqual(db().execute('SELECT voided FROM settlements').fetchone()[0],1)
    def test_validation_and_month_isolation(self):
        self.login()
        for data in [dict(sender=1,recipient=1,amount='10'),dict(sender=1,recipient=2,amount='-1'),dict(sender=999,recipient=2,amount='10')]:
            self.assertEqual(self.post('/settlements',**data,day='2026-10-27',month='2026-10').status_code,400)
        self.post('/settlements',sender=2,recipient=1,amount='10',day='2026-11-02',month='2026-10',note='Somente outubro')
        self.assertNotIn(b'Somente outubro',self.client.get('/sharing?month=2026-11').data)
