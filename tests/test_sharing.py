import test_app
from app import app,db,split_amount

class SharingTests(test_app.FinanceTest):
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def test_division_rounding_and_reverse_payments(self):
        self.login()
        for amount,percent in [(1,50),(101,50),(9999,33),(9999,0),(9999,100)]:
            own,other=split_amount(amount,percent)
            self.assertEqual(own+other,amount); self.assertGreaterEqual(own,0); self.assertGreaterEqual(other,0)
        self.post('/entries',amount='100.01',kind='expense',description='Jantar',category='Lazer',day='2026-10-27',expense_scope='shared',paid_by=1,split_with=2,payer_percent=50)
        self.post('/entries',amount='20',kind='expense',description='Compras',category='Lazer',day='2026-10-27',expense_scope='shared',paid_by=2,split_with=1,payer_percent=50)
        page=self.client.get('/sharing?month=2026-10'); self.assertEqual(page.status_code,200)
        self.assertIn(b'40,00',page.data)
        with app.app_context(): eid=db().execute("SELECT id FROM entries WHERE description='Jantar'").fetchone()[0]
        self.post(f'/entries/{eid}/delete')
        self.assertNotIn(b'Jantar',self.client.get('/sharing?month=2026-10').data)
    def test_classification_validation_and_legacy(self):
        self.login()
        base=dict(amount='10',kind='expense',description='Antiga',category='Outros',day='2026-10-27')
        self.assertEqual(self.post('/entries',**base).status_code,302)
        self.assertEqual(self.post('/entries',**base,expense_scope='shared',paid_by=1,split_with=1,payer_percent=50).status_code,400)
        self.assertEqual(self.post('/entries',**base,expense_scope='shared',paid_by=1,split_with=2,payer_percent=101).status_code,400)
        with app.app_context():
            row=db().execute('SELECT * FROM entries').fetchone(); self.assertEqual(row['expense_scope'],'unclassified'); eid=row['id']
        self.assertEqual(self.post(f'/entries/{eid}/edit',amount='10',description='Individual',category='Outros',day='2026-10-27',expense_scope='individual',paid_by=1).status_code,302)
        with app.app_context(): self.assertEqual(db().execute('SELECT expense_scope FROM entries WHERE id=?',(eid,)).fetchone()[0],'individual')
        self.assertEqual(self.client.get(f'/entries/{eid}/edit').status_code,200)
