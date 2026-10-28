import test_app
from app import app, db

class PlanningTests(test_app.FinanceTest):
    def post(self,path,**data):
        return self.client.post(path,data=dict(csrf=self.token(),**data))
    def expense(self,description='Mercado',amount='120.30',category='Alimentação'):
        return self.post('/entries',amount=amount,description=description,kind='expense',category=category,day='2026-10-27')
    def test_budget_updates_and_spending(self):
        self.login(); self.expense()
        self.post('/budgets',month='2026-10',category='Alimentação',amount='100')
        page=self.client.get('/budgets?month=2026-10')
        self.assertEqual(page.status_code,200); self.assertIn(b'20,30',page.data)
        self.post('/budgets',month='2026-10',category='Alimentação',amount='200')
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM budgets').fetchone()[0],1)
            self.assertEqual(db().execute('SELECT amount FROM budgets').fetchone()[0],20000)
        self.assertNotIn(b'120,30',self.client.get('/budgets?month=2026-11').data)
        self.assertEqual(self.post('/budgets',month='invalid',category='Alimentação',amount='100').status_code,400)
    def test_goals_do_not_change_accounts_and_permissions(self):
        self.login(); self.post('/goals',name='Viagem',target='1000',deadline='2027-01-31')
        with app.app_context(): gid=db().execute('SELECT id FROM goals').fetchone()[0]
        self.post(f'/goals/{gid}/contribute',amount='250',day='2026-10-27')
        self.assertIn(b'25%',self.client.get('/goals').data)
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM entries').fetchone()[0],0)
            cid=db().execute('SELECT id FROM contributions').fetchone()[0]
        with self.client.session_transaction() as s:s['uid']=2
        self.post(f'/contributions/{cid}/remove')
        with app.app_context(): self.assertEqual(db().execute('SELECT COUNT(*) FROM contributions').fetchone()[0],1)
        self.post(f'/goals/{gid}/toggle')
        self.assertEqual(self.post(f'/goals/{gid}/contribute',amount='50',day='2026-10-27').status_code,404)
    def test_filters_reports_csv_and_auth(self):
        self.assertEqual(self.client.get('/export.csv').status_code,302)
        self.login(); self.expense(); self.expense(description='=SUM(A1:A2)',amount='10',category='Outros')
        filtered=self.client.get('/?month=2026-10&q=Mercado&kind=expense&category=Alimenta%C3%A7%C3%A3o&person=1')
        self.assertEqual(filtered.status_code,200); self.assertIn(b'120,30',filtered.data); self.assertNotIn(b'=SUM(A1:A2)',filtered.data)
        export=self.client.get('/export.csv?month=2026-10')
        self.assertEqual(export.status_code,200); self.assertIn("'=SUM(A1:A2)",export.data.decode('utf-8-sig'))
        self.assertNotIn(b'Mercado',self.client.get('/export.csv?month=2026-10&category=Outros').data)
        report=self.client.get('/reports?month=2026-10'); self.assertEqual(report.status_code,200); self.assertIn(b'130,30',report.data)
        for path in ['/reports?month=bad','/?kind=bad','/goals']:
            self.assertEqual(self.client.get(path).status_code,200 if path=='/goals' else 400)
