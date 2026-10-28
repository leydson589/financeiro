import test_app
from app import app,db

class MobileTests(test_app.FinanceTest):
    def test_pwa_public_assets_and_private_data(self):
        self.assertEqual(self.client.get('/').status_code,302)
        for path in ['/static/manifest.webmanifest','/static/icon-192.png','/static/icon-512.png','/offline','/service-worker.js']:
            response=self.client.get(path); self.assertEqual(response.status_code,200,path)
        worker=self.client.get('/service-worker.js')
        self.assertEqual(worker.headers['Service-Worker-Allowed'],'/')
        manifest=self.client.get('/static/manifest.webmanifest').json
        self.assertEqual(manifest['display'],'standalone')
        offline=self.client.get('/offline').data
        self.assertNotIn(b'csrf',offline)
        self.assertEqual(self.client.get('/does-not-exist').status_code,404)
        self.assertIn(b'Ir para o login',self.client.get('/does-not-exist').data)
    def test_reassign_account_updates_balances(self):
        self.login()
        self.client.post('/entries',data=dict(csrf=self.token(),amount='40',description='Mercado',kind='expense',category='Alimentação',day='2026-10-27'))
        self.client.post('/wallet',data=dict(csrf=self.token(),type='account',name='Banco',opening='100'))
        with app.app_context():
            eid=db().execute('SELECT id FROM entries').fetchone()[0]
            aid=db().execute('SELECT id FROM accounts').fetchone()[0]
        payload=dict(csrf=self.token(),amount='40',description='Mercado',category='Alimentação',day='2026-10-27',account_id=aid)
        self.assertEqual(self.client.post(f'/entries/{eid}/edit',data=payload).status_code,302)
        self.assertIn(b'60,00',self.client.get('/wallet').data)
        payload['account_id']=''
        self.client.post(f'/entries/{eid}/edit',data=payload)
        self.assertIn(b'100,00',self.client.get('/wallet').data)
        payload['account_id']='999999'; self.assertEqual(self.client.post(f'/entries/{eid}/edit',data=payload).status_code,400)
