import os, sqlite3, secrets, time, calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, g, Response, send_from_directory
from werkzeug.security import generate_password_hash as werkzeug_hash, check_password_hash

def generate_password_hash(password):
    return werkzeug_hash(password, method="pbkdf2:sha256:1000000")

app = Flask(__name__)
secret = os.environ.get('SECRET_KEY', '')
if len(secret) < 32:
    raise RuntimeError('Defina SECRET_KEY com pelo menos 32 caracteres aleatórios.')
app.config.update(SECRET_KEY=secret, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'true') == 'true', PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=16384)
DB = os.environ.get('DATABASE_PATH', 'data/financeiro.db')

def db():
    if 'db' not in g:
        os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
        g.db = sqlite3.connect(DB, timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(error):
    if 'db' in g: g.db.close()

def init_db():
    db().executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL CHECK(kind IN ('income','expense')), amount INTEGER NOT NULL CHECK(amount>0), description TEXT NOT NULL, category TEXT NOT NULL, day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attempts(email TEXT PRIMARY KEY, count INTEGER NOT NULL, started REAL NOT NULL);''')
    user_columns={r['name'] for r in db().execute('PRAGMA table_info(users)')}
    if 'session_version' not in user_columns: db().execute('ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0')
    columns = {r['name'] for r in db().execute('PRAGMA table_info(entries)')}
    for name, definition in [('account_id','INTEGER REFERENCES accounts(id)'), ('card_id','INTEGER REFERENCES cards(id)'), ('invoice_month','TEXT'), ('recurrence_id','INTEGER'), ('occurrence','TEXT'), ('deleted_at','TEXT'), ('expense_scope',"TEXT NOT NULL DEFAULT 'unclassified'"), ('paid_by','INTEGER REFERENCES users(id)'), ('split_with','INTEGER REFERENCES users(id)'), ('payer_percent','INTEGER NOT NULL DEFAULT 50')]:
        if name not in columns: db().execute(f'ALTER TABLE entries ADD COLUMN {name} {definition}')
    db().executescript("""CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, name TEXT NOT NULL, opening INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY, name TEXT NOT NULL, closing INTEGER NOT NULL, due INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS recurring(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), description TEXT NOT NULL, amount INTEGER NOT NULL, category TEXT NOT NULL, day INTEGER NOT NULL, start TEXT NOT NULL, account_id INTEGER REFERENCES accounts(id), active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS invoice_payments(card_id INTEGER NOT NULL REFERENCES cards(id), month TEXT NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY(card_id,month));
    CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY,card_id INTEGER REFERENCES cards(id),account_id INTEGER REFERENCES accounts(id),month TEXT NOT NULL,amount INTEGER NOT NULL,day TEXT NOT NULL,user_id INTEGER REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS budgets(month TEXT NOT NULL,category TEXT NOT NULL,amount INTEGER NOT NULL CHECK(amount>0),PRIMARY KEY(month,category));
    CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY,name TEXT NOT NULL,target INTEGER NOT NULL CHECK(target>0),deadline TEXT,active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS contributions(id INTEGER PRIMARY KEY,goal_id INTEGER NOT NULL REFERENCES goals(id),user_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),day TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settlements(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),sender INTEGER NOT NULL REFERENCES users(id),recipient INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),day TEXT NOT NULL,month TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',voided INTEGER NOT NULL DEFAULT 0,CHECK(sender<>recipient));
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
    CREATE VIEW IF NOT EXISTS active_entries AS SELECT * FROM entries WHERE deleted_at IS NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS unique_occurrence ON entries(recurrence_id,occurrence);""")
    recurring_columns={r['name'] for r in db().execute('PRAGMA table_info(recurring)')}
    for name,definition in [('expense_scope',"TEXT NOT NULL DEFAULT 'unclassified'"),('paid_by','INTEGER REFERENCES users(id)'),('split_with','INTEGER REFERENCES users(id)'),('payer_percent','INTEGER NOT NULL DEFAULT 50')]:
        if name not in recurring_columns: db().execute(f'ALTER TABLE recurring ADD COLUMN {name} {definition}')
    db().commit()

@app.cli.command('create-user')
def create_user():
    import click
    init_db()
    name = click.prompt('Nome').strip()
    email = click.prompt('E-mail').strip().lower()
    password = click.prompt('Senha (mínimo 12 caracteres)', hide_input=True, confirmation_prompt=True)
    if not name or '@' not in email or len(password) < 12: raise click.ClickException('Nome, e-mail ou senha inválidos.')
    try:
        db().execute('INSERT INTO users(name,email,password) VALUES(?,?,?)', (name,email,generate_password_hash(password)))
        db().commit()
    except sqlite3.IntegrityError: raise click.ClickException('E-mail já cadastrado.')
    click.echo('Conta criada.')

@app.cli.command('init-db')
def init_command(): init_db()

def login_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if 'uid' not in session: return redirect(url_for('login'))
        return f(*a, **kw)
    return wrapped

@app.before_request
def csrf_check():
    if 'uid' in session:
        user=db().execute('SELECT session_version FROM users WHERE id=?',(session['uid'],)).fetchone()
        if not user or session.get('version',0)!=user['session_version']:
            session.clear()
            if request.endpoint != 'login': return redirect(url_for('login'))
    if 'csrf' not in session: session['csrf'] = secrets.token_hex(32)
    if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf', '')): abort(400)

@app.after_request
def headers(response):
    if request.method=='POST' and response.status_code<400 and session.get('uid') and request.endpoint in AUDIT_ACTIONS:
        db().execute('INSERT INTO audit(user_id,action) VALUES(?,?)',(session['uid'],AUDIT_ACTIONS[request.endpoint])); db().commit()
    response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"})
    return response

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()[:254]
        attempt = db().execute('SELECT * FROM attempts WHERE email=?',(email,)).fetchone()
        now = time.time()
        if attempt and attempt['count'] >= 8 and now-attempt['started'] < 900:
            flash('Muitas tentativas. Aguarde 15 minutos.'); return render_template('login.html'), 429
        user = db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        valid = check_password_hash(user['password'] if user else DUMMY_HASH, request.form.get('password',''))
        if user and valid:
            db().execute('DELETE FROM attempts WHERE email=?',(email,)); db().commit()
            session.clear(); session.update(uid=user['id'], name=user['name'], version=user['session_version'], csrf=secrets.token_hex(32)); session.permanent=True
            return redirect(url_for('index'))
        if not attempt or now-attempt['started'] >= 900:
            db().execute('INSERT OR REPLACE INTO attempts VALUES(?,1,?)',(email,now))
        else: db().execute('UPDATE attempts SET count=count+1 WHERE email=?',(email,))
        db().commit(); flash('E-mail ou senha incorretos.')
    return render_template('login.html')

@app.post('/logout')
@login_required
def logout(): session.clear(); return redirect(url_for('login'))

CATEGORIES = ['Moradia','Alimentação','Transporte','Saúde','Lazer','Educação','Salário','Investimentos','Outros']
@app.get('/')
@login_required
def index():
    month = selected_month()
    rows = filtered_entries(month)
    income = sum(r['amount'] for r in rows if r['kind']=='income'); expense = sum(r['amount'] for r in rows if r['kind']=='expense')
    categories = {c:sum(r['amount'] for r in rows if r['kind']=='expense' and r['category']==c) for c in CATEGORIES}
    accounts = db().execute('SELECT * FROM accounts ORDER BY name').fetchall()
    cards = db().execute('SELECT * FROM cards ORDER BY name').fetchall()
    return render_template('index.html', people=db().execute('SELECT id,name FROM users ORDER BY name').fetchall(), accounts=accounts, cards=cards, rows=rows, income=income, expense=expense, balance=income-expense, month=month, today=date.today().isoformat(), categories=CATEGORIES, totals={k:v for k,v in categories.items() if v})

@app.post('/entries')
@login_required
def add_entry():
    try:
        amount = Decimal(request.form.get('amount','').replace(',','.'))
        if not amount.is_finite() or amount<=0 or amount>Decimal('999999999.99') or amount.as_tuple().exponent < -2: raise ValueError()
        cents = int(amount*100)
        day = date.fromisoformat(request.form['day']).isoformat()
        description = request.form['description'].strip()
        kind = request.form['kind']; category = request.form['category']
        if not description or len(description)>120 or kind not in ('income','expense') or category not in CATEGORIES: raise ValueError()
    except (ValueError,InvalidOperation,KeyError): abort(400)
    account_id = optional_id('account_id', 'accounts')
    card_id = optional_id('card_id', 'cards')
    try: installments = int(request.form.get('installments','1'))
    except ValueError: abort(400)
    if installments < 1 or installments > 120 or (card_id and (account_id or kind != 'expense')) or (not card_id and installments != 1) or cents < installments: abort(400)
    card = db().execute('SELECT * FROM cards WHERE id=?',(card_id,)).fetchone() if card_id else None
    invoice = shift_month(day[:7], int(int(day[8:]) >= min(card['closing'], calendar.monthrange(int(day[:4]),int(day[5:7]))[1]))) if card else None
    scope,paid_by,split_with,percent = division_fields(kind)
    for i in range(installments):
        part = cents // installments + int(i < cents % installments)
        label = description if installments == 1 else f'{description} ({i+1}/{installments})'
        part_day = day if i == 0 else month_day(shift_month(day[:7],i),int(day[8:]))
        db().execute('INSERT INTO entries(user_id,kind,amount,description,category,day,account_id,card_id,invoice_month,expense_scope,paid_by,split_with,payer_percent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (session['uid'],kind,part,label,category,part_day,account_id,card_id,shift_month(invoice,i) if invoice else None,scope,paid_by,split_with,percent))
    db().commit()
    flash('Lançamento salvo.'); return redirect(url_for('index',month=day[:7]))

@app.post('/entries/<int:entry_id>/delete')
@login_required
def delete_entry(entry_id):
    row=db().execute('SELECT * FROM active_entries WHERE id=? AND user_id=?',(entry_id,session['uid'])).fetchone()
    if not row: abort(404)
    protect_paid_invoice(row)
    db().execute("UPDATE entries SET deleted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND user_id=? AND deleted_at IS NULL",(entry_id,session['uid'])); db().commit()
    flash('Lançamento movido para a lixeira. Você pode restaurá-lo.'); return redirect(url_for('index',month=row['invoice_month'] or row['day'][:7]))

@app.get('/trash')
@login_required
def trash():
    rows=db().execute('SELECT e.*,u.name FROM entries e JOIN users u ON u.id=e.user_id WHERE e.deleted_at IS NOT NULL ORDER BY e.deleted_at DESC,e.id DESC').fetchall()
    return render_template('trash.html',rows=rows)

@app.post('/entries/<int:entry_id>/restore')
@login_required
def restore_entry(entry_id):
    row=db().execute('SELECT * FROM entries WHERE id=? AND user_id=? AND deleted_at IS NOT NULL',(entry_id,session['uid'])).fetchone()
    if not row: abort(404)
    protect_paid_invoice(row)
    db().execute('UPDATE entries SET deleted_at=NULL WHERE id=? AND user_id=?',(entry_id,session['uid'])); db().commit()
    flash('Lançamento restaurado e saldos recalculados.'); return redirect(url_for('trash'))

@app.template_filter('brl')
def brl(value): return ('R$ '+format(value/100, ',.2f')).replace(',','X').replace('.',',').replace('X','.')


def shift_month(month, offset):
    d = date.fromisoformat(month+'-01'); total = d.year*12+d.month-1+offset
    return f'{total//12:04d}-{total%12+1:02d}'

def month_day(month, day):
    d = date.fromisoformat(month+'-01')
    return d.replace(day=min(day,calendar.monthrange(d.year,d.month)[1])).isoformat()

def optional_id(field, table):
    value = request.form.get(field,'')
    if not value: return None
    try: value = int(value)
    except ValueError: abort(400)
    if not db().execute(f'SELECT id FROM {table} WHERE id=?',(value,)).fetchone(): abort(400)
    return value

def protect_paid_invoice(row):
    if row['card_id'] and db().execute('SELECT 1 FROM invoice_payments WHERE card_id=? AND month=?',(row['card_id'],row['invoice_month'])).fetchone():
        abort(409, description='Esta fatura já tem pagamento registrado. Seus lançamentos não podem ser alterados ou excluídos.')

def money(value, signed=False):
    try:
        n = Decimal(value.replace(',','.'))
        if not n.is_finite() or abs(n)>Decimal('999999999.99') or n.as_tuple().exponent < -2 or (not signed and n<=0): raise ValueError()
        return int(n*100)
    except (ValueError,InvalidOperation): abort(400)

@app.route('/entries/<int:entry_id>/edit', methods=['GET','POST'])
@login_required
def edit_entry(entry_id):
    row = db().execute('SELECT * FROM active_entries WHERE id=? AND user_id=?',(entry_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method == 'POST':
        protect_paid_invoice(row)
        amount = money(request.form.get('amount',''))
        description = request.form.get('description','').strip()
        category = request.form.get('category','')
        try: day = date.fromisoformat(request.form.get('day','')).isoformat()
        except ValueError: abort(400)
        if not description or len(description)>120 or category not in CATEGORIES: abort(400)
        invoice = row['invoice_month']
        if row['card_id']:
            invoice = request.form.get('invoice_month','')
            try: date.fromisoformat(invoice+'-01')
            except ValueError: abort(400)
        if row['card_id'] and db().execute('SELECT 1 FROM invoice_payments WHERE card_id=? AND month=?',(row['card_id'],invoice)).fetchone():
            abort(409, description='A fatura de destino já tem pagamento registrado.')
        account_id=row['account_id'] if row['card_id'] else optional_id('account_id','accounts')
        scope,paid_by,split_with,percent=division_fields(row['kind'],row)
        db().execute('UPDATE entries SET description=?,amount=?,category=?,day=?,invoice_month=?,account_id=?,expense_scope=?,paid_by=?,split_with=?,payer_percent=? WHERE id=?',(description,amount,category,day,invoice,account_id,scope,paid_by,split_with,percent,entry_id)); db().commit()
        flash('Lançamento atualizado.'); return redirect(url_for('index',month=day[:7]))
    return render_template('edit.html',people=db().execute('SELECT id,name FROM users ORDER BY name').fetchall(),row=row,categories=CATEGORIES,accounts=db().execute('SELECT * FROM accounts ORDER BY name').fetchall())

@app.route('/wallet',methods=['GET','POST'])
@login_required
def wallet():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        if not name or len(name)>80: abort(400)
        if request.form.get('type') == 'account':
            db().execute('INSERT INTO accounts(name,opening) VALUES(?,?)',(name,money(request.form.get('opening','0'),signed=True)))
        elif request.form.get('type') == 'card':
            try: closing,due = int(request.form.get('closing','')),int(request.form.get('due',''))
            except ValueError: abort(400)
            if not 1<=closing<=31 or not 1<=due<=31: abort(400)
            db().execute('INSERT INTO cards(name,closing,due) VALUES(?,?,?)',(name,closing,due))
        else: abort(400)
        db().commit(); flash('Cadastro salvo.'); return redirect(url_for('wallet'))
    accounts = db().execute("SELECT a.*, a.opening+COALESCE(SUM(CASE WHEN e.kind='income' THEN e.amount ELSE -e.amount END),0)-COALESCE((SELECT SUM(t.amount) FROM transfers t WHERE t.account_id=a.id),0) AS balance FROM accounts a LEFT JOIN active_entries e ON e.account_id=a.id GROUP BY a.id ORDER BY a.name").fetchall()
    invoices = db().execute("SELECT c.id,c.name,c.due,e.invoice_month,SUM(e.amount) AS total FROM cards c LEFT JOIN active_entries e ON e.card_id=c.id GROUP BY c.id,e.invoice_month ORDER BY c.name,e.invoice_month").fetchall()
    cards = db().execute('SELECT * FROM cards').fetchall()
    payments={(p['card_id'],p['month']):p['amount'] for p in db().execute('SELECT * FROM invoice_payments')}
    return render_template('wallet.html',accounts=accounts,invoices=invoices,cards=cards,payments=payments,today=date.today().isoformat(),transfers=db().execute('SELECT t.*,a.name FROM transfers t JOIN accounts a ON a.id=t.account_id ORDER BY t.id DESC').fetchall())

@app.post('/invoices/pay')
@login_required
def pay_invoice():
    card_id = optional_id('card_id','cards'); account_id = optional_id('account_id','accounts')
    month = request.form.get('month','')
    try: date.fromisoformat(month+'-01'); day=date.fromisoformat(request.form.get('day','')).isoformat()
    except ValueError: abort(400)
    if not card_id or not account_id: abort(400)
    # Record a transfer without counting the expense twice.
    with db():
        db().execute('BEGIN IMMEDIATE')
        payment = db().execute('SELECT * FROM invoice_payments WHERE card_id=? AND month=?',(card_id,month)).fetchone()
        total = db().execute('SELECT COALESCE(SUM(amount),0) FROM active_entries WHERE card_id=? AND invoice_month=?',(card_id,month)).fetchone()[0]
        outstanding = total-(payment['amount'] if payment else 0)
        if outstanding<=0: flash('Fatura já quitada ou sem compras.'); return redirect(url_for('wallet'))
        db().execute('INSERT INTO invoice_payments(card_id,month,amount) VALUES(?,?,?) ON CONFLICT(card_id,month) DO UPDATE SET amount=excluded.amount',(card_id,month,total))
        db().execute('INSERT INTO transfers(card_id,account_id,month,amount,day,user_id) VALUES(?,?,?,?,?,?)',(card_id,account_id,month,outstanding,day,session['uid']))
    flash('Pagamento registrado sem duplicar a despesa.'); return redirect(url_for('wallet'))

@app.route('/recurring',methods=['GET','POST'])
@login_required
def recurring():
    if request.method == 'POST':
        description=request.form.get('description','').strip(); category=request.form.get('category','')
        try: day=int(request.form.get('day','')); start=date.fromisoformat(request.form.get('start','')+'-01').strftime('%Y-%m')
        except ValueError: abort(400)
        if not description or len(description)>120 or category not in CATEGORIES or not 1<=day<=31: abort(400)
        scope,payer,other,percent=division_fields('expense')
        db().execute('INSERT INTO recurring(user_id,description,amount,category,day,start,account_id,expense_scope,paid_by,split_with,payer_percent) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(session['uid'],description,money(request.form.get('amount','')),category,day,start,optional_id('account_id','accounts'),scope,payer,other,percent))
        db().commit(); flash('Despesa recorrente criada.'); return redirect(url_for('recurring'))
    return render_template('recurring.html',people=db().execute('SELECT id,name FROM users ORDER BY name').fetchall(),rules=db().execute('SELECT r.*,u.name FROM recurring r JOIN users u ON u.id=r.user_id ORDER BY r.active DESC,r.id DESC').fetchall(),accounts=db().execute('SELECT * FROM accounts').fetchall(),categories=CATEGORIES,today=date.today().strftime('%Y-%m'))

@app.post('/recurring/generate')
@login_required
def generate_recurring():
    month=request.form.get('month','')
    try: date.fromisoformat(month+'-01')
    except ValueError: abort(400)
    count=0
    for r in db().execute('SELECT * FROM recurring WHERE active=1 AND start<=?',(month,)).fetchall():
        cur=db().execute("INSERT OR IGNORE INTO entries(user_id,kind,amount,description,category,day,account_id,recurrence_id,occurrence,expense_scope,paid_by,split_with,payer_percent) VALUES(?,'expense',?,?,?,?,?,?,?,?,?,?,?)",(r['user_id'],r['amount'],r['description'],r['category'],month_day(month,r['day']),r['account_id'],r['id'],month,r['expense_scope'],r['paid_by'],r['split_with'],r['payer_percent']))
        count+=cur.rowcount
    db().commit(); flash(f'{count} despesas geradas. Gerar novamente não duplica os lançamentos.'); return redirect(url_for('index',month=month))

@app.post('/recurring/<int:rule_id>/stop')
@login_required
def stop_recurring(rule_id):
    db().execute('UPDATE recurring SET active=0 WHERE id=? AND user_id=?',(rule_id,session['uid'])); db().commit()
    flash('Recorrência encerrada. Os lançamentos anteriores foram mantidos.'); return redirect(url_for('recurring'))


def selected_month(value=None):
    month = value if value is not None else request.args.get('month',date.today().strftime('%Y-%m'))
    try:
        parsed = date.fromisoformat(month+'-01')
        if parsed.strftime('%Y-%m') != month: raise ValueError()
    except (ValueError,TypeError): abort(400)
    return month

def filtered_entries(month):
    clauses=['COALESCE(e.invoice_month,substr(e.day,1,7))=?']; params=[month]
    query=request.args.get('q','').strip()[:120]
    if query:
        clauses.append('instr(lower(e.description),lower(?))>0'); params.append(query)
    for arg,column,allowed in [('kind','e.kind',['income','expense']),('category','e.category',CATEGORIES)]:
        value=request.args.get(arg,'')
        if value:
            if value not in allowed: abort(400)
            clauses.append(column+'=?'); params.append(value)
    person=request.args.get('person','')
    if person:
        try: person=int(person)
        except ValueError: abort(400)
        clauses.append('e.user_id=?'); params.append(person)
    return db().execute('SELECT e.*,u.name FROM active_entries e JOIN users u ON u.id=e.user_id WHERE '+' AND '.join(clauses)+' ORDER BY e.day DESC,e.id DESC',params).fetchall()

@app.route('/budgets',methods=['GET','POST'])
@login_required
def budgets():
    month=selected_month(request.form.get('month')) if request.method=='POST' else selected_month()
    if request.method=='POST':
        category=request.form.get('category','')
        if category not in CATEGORIES: abort(400)
        amount=money(request.form.get('amount',''))
        db().execute('INSERT INTO budgets VALUES(?,?,?) ON CONFLICT(month,category) DO UPDATE SET amount=excluded.amount',(month,category,amount)); db().commit()
        flash('Limite mensal salvo.'); return redirect(url_for('budgets',month=month))
    spent={r['category']:r['total'] for r in db().execute("SELECT category,SUM(amount) AS total FROM active_entries WHERE kind='expense' AND COALESCE(invoice_month,substr(day,1,7))=? GROUP BY category",(month,))}
    limits=db().execute('SELECT * FROM budgets WHERE month=? ORDER BY category',(month,)).fetchall()
    return render_template('budgets.html',month=month,limits=limits,spent=spent,categories=CATEGORIES)

@app.post('/budgets/remove')
@login_required
def remove_budget():
    month=selected_month(request.form.get('month',''))
    db().execute('DELETE FROM budgets WHERE month=? AND category=?',(month,request.form.get('category',''))); db().commit()
    flash('Limite removido. Os lançamentos foram mantidos.'); return redirect(url_for('budgets',month=month))

@app.route('/goals',methods=['GET','POST'])
@login_required
def goals():
    if request.method=='POST':
        name=request.form.get('name','').strip(); deadline=request.form.get('deadline','')
        if not name or len(name)>80: abort(400)
        if deadline:
            try: deadline=date.fromisoformat(deadline).isoformat()
            except ValueError: abort(400)
        db().execute('INSERT INTO goals(name,target,deadline) VALUES(?,?,?)',(name,money(request.form.get('target','')),deadline or None)); db().commit()
        flash('Meta criada.'); return redirect(url_for('goals'))
    rows=db().execute('SELECT g.*,COALESCE(SUM(c.amount),0) AS saved FROM goals g LEFT JOIN contributions c ON c.goal_id=g.id GROUP BY g.id ORDER BY g.active DESC,g.id DESC').fetchall()
    history=db().execute('SELECT c.*,g.name AS goal,u.name AS person FROM contributions c JOIN goals g ON g.id=c.goal_id JOIN users u ON u.id=c.user_id ORDER BY c.day DESC,c.id DESC').fetchall()
    return render_template('goals.html',goals=rows,history=history,today=date.today().isoformat())

@app.post('/goals/<int:goal_id>/contribute')
@login_required
def contribute(goal_id):
    if not db().execute('SELECT id FROM goals WHERE id=? AND active=1',(goal_id,)).fetchone(): abort(404)
    try: day=date.fromisoformat(request.form.get('day','')).isoformat()
    except ValueError: abort(400)
    db().execute('INSERT INTO contributions(goal_id,user_id,amount,day) VALUES(?,?,?,?)',(goal_id,session['uid'],money(request.form.get('amount','')),day)); db().commit()
    flash('Valor reservado registrado.'); return redirect(url_for('goals'))

@app.post('/goals/<int:goal_id>/toggle')
@login_required
def toggle_goal(goal_id):
    db().execute('UPDATE goals SET active=1-active WHERE id=?',(goal_id,)); db().commit()
    return redirect(url_for('goals'))

@app.post('/contributions/<int:contribution_id>/remove')
@login_required
def remove_contribution(contribution_id):
    db().execute('DELETE FROM contributions WHERE id=? AND user_id=?',(contribution_id,session['uid'])); db().commit()
    flash('Reserva removida do acompanhamento.'); return redirect(url_for('goals'))

@app.get('/reports')
@login_required
def reports():
    month=selected_month()
    months=[shift_month(month,i) for i in range(-5,1)]
    rows=[]
    for m in months:
        totals=db().execute("SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END),0) AS income,COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) AS expense FROM active_entries WHERE COALESCE(invoice_month,substr(day,1,7))=?",(m,)).fetchone()
        rows.append(dict(month=m,income=totals['income'],expense=totals['expense'],balance=totals['income']-totals['expense']))
    categories=db().execute("SELECT category,SUM(amount) AS total FROM active_entries WHERE kind='expense' AND COALESCE(invoice_month,substr(day,1,7))=? GROUP BY category ORDER BY total DESC",(month,)).fetchall()
    return render_template('reports.html',month=month,rows=rows,categories=categories,expense_delta=rows[-1]['expense']-rows[-2]['expense'])

@app.get('/export.csv')
@login_required
def export_csv():
    import csv,io
    month=selected_month(); output=io.StringIO(); writer=csv.writer(output,delimiter=';')
    writer.writerow(['Data','Competência','Descrição','Pessoa','Tipo','Categoria','Valor (R$)'])
    def safe(value):
        value=str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
    for r in filtered_entries(month):
        writer.writerow([r['day'],r['invoice_month'] or r['day'][:7],safe(r['description']),safe(r['name']),'Receita' if r['kind']=='income' else 'Despesa',safe(r['category']),f"{r['amount']//100},{r['amount']%100:02d}"])
    return Response('\ufeff'+output.getvalue(),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="financeiro-{month}.csv"'})


AUDIT_ACTIONS = {
    'edit_recurring':'Regra de recorrência atualizada',
    'add_settlement':'Acerto entre o casal registrado','void_settlement':'Acerto entre o casal estornado',
    'login':'Login realizado','add_entry':'Lançamento criado','edit_entry':'Lançamento editado',
    'delete_entry':'Lançamento movido para a lixeira','restore_entry':'Lançamento restaurado','wallet':'Conta ou cartão cadastrado',
    'pay_invoice':'Solicitação de registro de pagamento de fatura','recurring':'Recorrência criada',
    'generate_recurring':'Geração de recorrências solicitada','stop_recurring':'Recorrência encerrada',
    'budgets':'Orçamento atualizado','remove_budget':'Limite de orçamento removido',
    'goals':'Meta criada','contribute':'Reserva registrada','toggle_goal':'Estado da meta alterado',
    'remove_contribution':'Solicitação de remoção de reserva',
}

@app.route('/security',methods=['GET','POST'])
@login_required
def security():
    if request.method=='POST':
        user=db().execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()
        key='password-change:'+str(session['uid']); now=time.time()
        attempt=db().execute('SELECT * FROM attempts WHERE email=?',(key,)).fetchone()
        if attempt and attempt['count']>=8 and now-attempt['started']<900:
            flash('Muitas tentativas. Aguarde 15 minutos.'); return redirect(url_for('security'))
        if not check_password_hash(user['password'],request.form.get('current_password','')):
            if not attempt or now-attempt['started']>=900: db().execute('INSERT OR REPLACE INTO attempts VALUES(?,1,?)',(key,now))
            else: db().execute('UPDATE attempts SET count=count+1 WHERE email=?',(key,))
            db().commit(); flash('A senha atual está incorreta.'); return redirect(url_for('security'))
        password=request.form.get('password','')
        if len(password)<12 or len(password)>1024 or password!=request.form.get('confirmation',''):
            flash('Use de 12 a 1024 caracteres e confirme a mesma senha.'); return redirect(url_for('security'))
        if check_password_hash(user['password'],password):
            flash('Escolha uma senha diferente da atual.'); return redirect(url_for('security'))
        with db():
            db().execute('UPDATE users SET password=?,session_version=session_version+1 WHERE id=?',(generate_password_hash(password),session['uid']))
            db().execute('DELETE FROM attempts WHERE email IN (?,?)',(key,user['email']))
            db().execute('INSERT INTO audit(user_id,action) VALUES(?,?)',(session['uid'],'Senha alterada; sessões anteriores encerradas'))
        session.clear(); flash('Senha alterada. Entre novamente com a nova senha.'); return redirect(url_for('login'))
    history=db().execute('SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100').fetchall()
    return render_template('security.html',history=history)

@app.cli.command('backup')
def backup_command():
    """Cria uma cópia consistente e verificada do banco SQLite."""
    import click
    from pathlib import Path
    from datetime import datetime, timezone
    directory=Path(os.environ.get('BACKUP_DIRECTORY','backups'))
    directory.mkdir(parents=True,exist_ok=True)
    destination=directory/('financeiro-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.db')
    # O_EXCL prevents replacing files or following existing symlinks.
    descriptor=os.open(str(destination),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.close(descriptor)
    target=sqlite3.connect(str(destination))
    try:
        db().backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise click.ClickException('Falha na verificação de integridade do backup.')
    finally: target.close()
    click.echo('Backup verificado: '+str(destination.resolve()))


@app.get('/service-worker.js')
def service_worker():
    response=send_from_directory(app.static_folder,'service-worker.js',mimetype='application/javascript')
    response.headers['Service-Worker-Allowed']='/'
    return response

@app.get('/offline')
def offline():
    return render_template('offline.html')

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(413)
@app.errorhandler(500)
def friendly_error(error):
    messages={400:('Não foi possível salvar','Verifique os campos e tente novamente. Se esta página ficou aberta por muito tempo, atualize-a antes de reenviar.'),
              403:('Acesso não permitido','Sua conta não tem permissão para esta ação.'),
              404:('Não encontramos esta página','O registro pode ter sido removido ou pertencer a outra pessoa.'),
              409:('Esta alteração está bloqueada','Uma fatura com pagamento registrado não permite editar, excluir ou restaurar suas compras, nem receber uma compra pela edição.'),
              413:('Envio maior que o permitido','Reduza o conteúdo dos campos e tente novamente.'),
              500:('Não foi possível concluir','Ocorreu um erro no sistema. Volte ao painel e confira se a ação foi registrada antes de tentar novamente.')}
    title,message=messages.get(error.code,messages[500])
    return render_template('error.html',title=title,message=message,code=error.code),error.code


def division_fields(kind, previous=None):
    if previous and 'expense_scope' not in request.form:
        return previous['expense_scope'],previous['paid_by'],previous['split_with'],previous['payer_percent']
    scope=request.form.get('expense_scope','unclassified')
    if scope not in ('unclassified','individual','shared'): abort(400)
    if kind!='expense' or scope=='unclassified': return 'unclassified',None,None,50
    payer=optional_id('paid_by','users')
    if not payer: abort(400)
    if scope=='individual': return scope,payer,None,100
    other=optional_id('split_with','users')
    try: percent=int(request.form.get('payer_percent','50'))
    except ValueError: abort(400)
    if not other or other==payer or not 0<=percent<=100: abort(400)
    return scope,payer,other,percent

def split_amount(amount, percent):
    # Round the payer's share to the nearest cent; assign the exact remainder to the other person.
    own=(amount*percent+50)//100
    return own,amount-own

@app.get('/sharing')
@login_required
def sharing():
    month=selected_month()
    people={p['id']:p['name'] for p in db().execute('SELECT id,name FROM users ORDER BY name')}
    summary={uid:dict(name=name,assumed=0,responsibility=0,net=0,individual=0) for uid,name in people.items()}
    rows=db().execute("SELECT * FROM active_entries WHERE kind='expense' AND COALESCE(invoice_month,substr(day,1,7))=? ORDER BY day DESC,id DESC",(month,)).fetchall()
    details=[]; unclassified=0
    for row in rows:
        if row['expense_scope']=='unclassified': unclassified+=row['amount']; continue
        payer=row['paid_by']
        if row['expense_scope']=='individual': summary[payer]['individual']+=row['amount']; continue
        own,other=split_amount(row['amount'],row['payer_percent'])
        summary[payer]['assumed']+=row['amount']; summary[payer]['responsibility']+=own; summary[payer]['net']+=other
        summary[row['split_with']]['responsibility']+=other; summary[row['split_with']]['net']-=other
        details.append(dict(row=row,payer=people[payer],other=people[row['split_with']],own=own,other_amount=other))
    settlements=db().execute('SELECT s.*,a.name AS sender_name,b.name AS recipient_name,u.name AS author FROM settlements s JOIN users a ON a.id=s.sender JOIN users b ON b.id=s.recipient JOIN users u ON u.id=s.user_id WHERE s.month=? ORDER BY s.day DESC,s.id DESC',(month,)).fetchall()
    for payment in settlements:
        if not payment['voided']:
            summary[payment['sender']]['net']+=payment['amount']
            summary[payment['recipient']]['net']-=payment['amount']
    return render_template('sharing.html',month=month,summary=summary.values(),details=details,unclassified=unclassified,people=people,settlements=settlements,today=date.today().isoformat())


@app.post('/settlements')
@login_required
def add_settlement():
    sender=optional_id('sender','users'); recipient=optional_id('recipient','users')
    if not sender or not recipient or sender==recipient: abort(400)
    month=selected_month(request.form.get('month',''))
    try: day=date.fromisoformat(request.form.get('day','')).isoformat()
    except ValueError: abort(400)
    note=request.form.get('note','').strip()
    if len(note)>200: abort(400)
    db().execute('INSERT INTO settlements(user_id,sender,recipient,amount,day,month,note) VALUES(?,?,?,?,?,?,?)',(session['uid'],sender,recipient,money(request.form.get('amount','')),day,month,note)); db().commit()
    flash('Acerto registrado. O resumo da divisão foi atualizado.'); return redirect(url_for('sharing',month=month))

@app.post('/settlements/<int:settlement_id>/void')
@login_required
def void_settlement(settlement_id):
    row=db().execute('SELECT * FROM settlements WHERE id=? AND user_id=? AND voided=0',(settlement_id,session['uid'])).fetchone()
    if not row: abort(404)
    db().execute('UPDATE settlements SET voided=1 WHERE id=?',(settlement_id,)); db().commit()
    flash('Registro de acerto estornado. O histórico foi preservado.'); return redirect(url_for('sharing',month=row['month']))


@app.route('/recurring/<int:rule_id>/edit',methods=['GET','POST'])
@login_required
def edit_recurring(rule_id):
    row=db().execute('SELECT * FROM recurring WHERE id=? AND user_id=?',(rule_id,session['uid'])).fetchone()
    if not row: abort(404)
    if request.method=='POST':
        description=request.form.get('description','').strip(); category=request.form.get('category','')
        start=selected_month(request.form.get('start',''))
        try: day=int(request.form.get('day',''))
        except ValueError: abort(400)
        if not description or len(description)>120 or category not in CATEGORIES or not 1<=day<=31: abort(400)
        amount=money(request.form.get('amount','')); account=optional_id('account_id','accounts')
        scope,payer,other,percent=division_fields('expense',row)
        active=request.form.get('active','')
        if active not in ('0','1'): abort(400)
        db().execute('UPDATE recurring SET description=?,category=?,start=?,day=?,amount=?,account_id=?,expense_scope=?,paid_by=?,split_with=?,payer_percent=?,active=? WHERE id=? AND user_id=?',(description,category,start,day,amount,account,scope,payer,other,percent,int(active),rule_id,session['uid'])); db().commit()
        flash('Regra atualizada. Os lançamentos já gerados foram preservados.'); return redirect(url_for('recurring'))
    return render_template('edit_recurring.html',row=row,categories=CATEGORIES,accounts=db().execute('SELECT * FROM accounts ORDER BY name').fetchall(),people=db().execute('SELECT id,name FROM users ORDER BY name').fetchall())

DUMMY_HASH = generate_password_hash(secrets.token_hex(32))
with app.app_context(): init_db()
