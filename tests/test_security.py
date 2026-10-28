import os, tempfile, sqlite3
import test_app
from app import app, db

class SecurityTests(test_app.FinanceTest):
    def test_password_rotation_revokes_old_sessions(self):
        self.login()
        second=app.test_client(); second.get('/login')
        with second.session_transaction() as s: token=s['csrf']
        second.post('/login',data=dict(csrf=token,email='um@example.com',password='senha-segura-123'))
        token=self.token()
        self.client.post('/security',data=dict(csrf=token,current_password='errada',password='senha-nova-123456',confirmation='senha-nova-123456'))
        self.assertEqual(second.get('/').status_code,200)
        response=self.client.post('/security',data=dict(csrf=token,current_password='senha-segura-123',password='senha-nova-123456',confirmation='senha-nova-123456'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(second.get('/').status_code,302)
        self.assertEqual(self.client.get('/').status_code,302)
        self.client.get('/login')
        response=self.client.post('/login',data=dict(csrf=self.token(),email='um@example.com',password='senha-nova-123456'))
        self.assertEqual(response.status_code,302); self.assertEqual(self.client.get('/security').status_code,200)
    def test_audit_and_backup(self):
        self.login()
        self.client.post('/entries',data=dict(csrf=self.token(),amount='10',kind='income',description='Teste',category='Outros',day='2026-10-27'))
        with app.app_context():
            self.assertTrue(db().execute("SELECT 1 FROM audit WHERE action='Lançamento criado'").fetchone())
        with tempfile.TemporaryDirectory() as directory:
            os.environ['BACKUP_DIRECTORY']=directory
            try:
                result=app.test_cli_runner().invoke(args=['backup'])
                self.assertEqual(result.exit_code,0,result.output)
                files=os.listdir(directory); self.assertEqual(len(files),1)
                path=os.path.join(directory,files[0]); self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
                conn=sqlite3.connect(path)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0],1); conn.close()
            finally: os.environ.pop('BACKUP_DIRECTORY',None)
