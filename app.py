
from flask import Flask, request, redirect, url_for, render_template_string, flash, session, send_file
import os
import sqlite3, os, json, tempfile, secrets
from datetime import date

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Sur l'hébergement, monter un disque persistant et définir DATA_DIR=/var/data.
DATA_DIR = os.environ.get("DATA_DIR", APP_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bernafacturation.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1")

LOGIN_HTML = """<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Connexion — BERNAFACTURATION</title><body style='font-family:Arial,sans-serif;max-width:440px;margin:8vh auto;padding:24px;background:#f5f7fb'><form method='post' style='background:white;padding:24px;border-radius:12px;box-shadow:0 2px 12px #0001'><h2>BERNAFACTURATION</h2><p>Connexion sécurisée</p>{% if error %}<p style='color:#b91c1c'>{{ error }}</p>{% endif %}<label>Mot de passe</label><input name='password' type='password' required autofocus style='box-sizing:border-box;width:100%;padding:12px;margin:8px 0 16px'><button style='padding:12px 18px'>Se connecter</button></form></body></html>"""

@app.before_request
def require_login():
    if request.endpoint in ("login", "static") or request.path == "/health":
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login", next=request.path))

@app.route("/login", methods=["GET", "POST"])
def login():
    configured = os.environ.get("ADMIN_PASSWORD")
    if not configured:
        return "Configuration requise : définissez ADMIN_PASSWORD dans les variables d'environnement avant d'ouvrir le logiciel en ligne.", 503
    error = None
    if request.method == "POST":
        supplied = request.form.get("password", "")
        import hmac
        if hmac.compare_digest(supplied, configured):
            session.clear()
            session["authenticated"] = True
            target = request.args.get("next", "")
            # N'autoriser qu'une redirection locale pour éviter les redirections externes.
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("home")
            return redirect(target)
        error = "Mot de passe incorrect."
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/health")
def health():
    return {"status": "ok"}


COMPANY = {
    "name": "VINCENT BUSINESS SERVICES",
    "subtitle": "(ETS VINCENT DON DE DIEU)",
    "line": "Imprimerie moderne au Sankuru",
    "services": "Impression sur tous supports : polo, képi, vareuse, invitation, carte PVC, etc. — Conception affiche, saisie et impression, photocopie, studio photo, scannage",
    "ids": "RCCM/23-A-175 | ID.NAT : 01-GA707-N64171K | N°IMPOT : A2403828M",
    "address1": "1 Av. Lekama, Q. Okitandeke/Lodja/Sankuru en RDC (Réf. Paroisse St NICOLAS)",
    "bank": "RAWBANK 01176633001-97 (CDF)",
    "phones": "+243 828 538 027 / 0898390310",
    "address2": "2 Av. de la Révolution, Petit Marché Maman Awoyi/Lodja/Sankuru",
    "email": "vincentbusinessservice@gmail.com",
}

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            unit TEXT DEFAULT 'pièce',
            price REAL NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            client TEXT,
            contact TEXT,
            address TEXT,
            items_json TEXT NOT NULL,
            total REAL NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS cash_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_date TEXT NOT NULL,
            move_type TEXT NOT NULL CHECK(move_type IN ('Entrée','Sortie')),
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS stock_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT, move_date TEXT NOT NULL,
            product TEXT NOT NULL, move_type TEXT NOT NULL CHECK(move_type IN ('Entrée','Sortie')),
            quantity REAL NOT NULL DEFAULT 0, unit TEXT DEFAULT 'unité', motif TEXT DEFAULT '',
            deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS daily_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT, report_date TEXT NOT NULL,
            service TEXT NOT NULL, client TEXT DEFAULT '', quantity REAL NOT NULL DEFAULT 1,
            amount REAL NOT NULL DEFAULT 0, payment TEXT DEFAULT 'Espèces', note TEXT DEFAULT '',
            deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS daily_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, report_date TEXT NOT NULL,
            reason TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, note TEXT DEFAULT '',
            deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

init_db()

# Migrations for linking each daily service to the exact product consumed.
with db() as con:
    cols = {r[1] for r in con.execute("PRAGMA table_info(daily_services)").fetchall()}
    if "stock_product" not in cols:
        con.execute("ALTER TABLE daily_services ADD COLUMN stock_product TEXT DEFAULT ''")
    if "stock_quantity" not in cols:
        con.execute("ALTER TABLE daily_services ADD COLUMN stock_quantity REAL NOT NULL DEFAULT 0")
    if "stock_unit" not in cols:
        con.execute("ALTER TABLE daily_services ADD COLUMN stock_unit TEXT DEFAULT ''")
    stock_cols = {r[1] for r in con.execute("PRAGMA table_info(stock_moves)").fetchall()}
    if "daily_service_id" not in stock_cols:
        con.execute("ALTER TABLE stock_moves ADD COLUMN daily_service_id INTEGER")

STYLE = """
*{box-sizing:border-box} body{font-family:Arial,sans-serif;background-color:#e9edf2;background-image:linear-gradient(rgba(233,237,242,.92),rgba(233,237,242,.92)),url("/static/vbs_logo.jpg");background-repeat:repeat;background-size:auto,360px auto;background-position:center top;margin:0;color:#172033}
nav{background-color:#163d70;background-image:linear-gradient(rgba(22,61,112,.90),rgba(22,61,112,.90)),url("/static/vbs_logo.jpg");background-repeat:no-repeat;background-position:center;background-size:contain;padding:13px 20px;color:white;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
nav a{color:white;text-decoration:none;font-weight:bold}
.wrap{max-width:1100px;margin:20px auto;padding:0 12px}
.paper{background-color:white;border:1px solid #cbd3df;padding:22px;box-shadow:0 3px 12px #0001;position:relative;overflow:hidden}.watermark{position:absolute!important;display:block!important;left:50%;top:50%;transform:translate(-50%,-50%);width:118%;height:auto;max-height:none;object-fit:contain;opacity:.14;pointer-events:none;z-index:0!important}.paper>*:not(.watermark){position:relative;z-index:1}
.header{display:grid;grid-template-columns:140px 1fr;gap:12px;align-items:center;border-bottom:2px solid #173d70;padding-bottom:12px}
.logo{width:100%;max-height:115px;object-fit:contain}.company{text-align:center}.company h1{font-size:21px;margin:3px;color:#173d70}.company p{margin:4px;font-size:12px}
h2{color:#173d70}.invoice-title{text-align:center;font-weight:bold;font-size:22px;margin:18px}
input,textarea,select{padding:8px;border:1px solid #b8c3d1;border-radius:4px;width:100%;font:inherit}
label{font-size:13px;font-weight:bold;display:block;margin:6px 0}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
table{width:100%;border-collapse:collapse;margin-top:12px} th,td{border:1px solid #7c8796;padding:8px;text-align:left} th{background:#eaf0f7}
td input{border:0;padding:4px;background:transparent}.right{text-align:right}.total{font-size:20px;font-weight:bold;text-align:right;margin:16px 0}
button,.btn{background:#173d70;color:white;border:0;border-radius:4px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block;margin:4px 2px}
.btn.secondary,button.secondary{background:#64748b}.btn.danger,button.danger{background:#a52b2b}
.footer{font-size:11px;text-align:center;border-top:1px solid #aaa;margin-top:18px;padding-top:10px;line-height:1.6}
.card{background-color:rgba(255,255,255,.96);background-image:linear-gradient(rgba(255,255,255,.91),rgba(255,255,255,.91)),url("/static/vbs_logo.jpg");background-repeat:no-repeat;background-position:center;background-size:55% auto;padding:18px;margin:12px 0;border:1px solid #d3dae4;border-radius:6px}
.small{font-size:12px;color:#475569}.results{position:absolute;background:white;border:1px solid #aaa;z-index:5;max-height:180px;overflow:auto;width:100%;display:none}.suggest-wrap{position:relative}
@media(max-width:700px){.header{grid-template-columns:1fr;text-align:center}.logo{max-height:85px}.grid{grid-template-columns:1fr}.paper{padding:12px}}
@media print{@page{size:A4 portrait;margin:8mm}html,body{background:white!important;-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}nav,.no-print,.flash{display:none!important}.wrap{max-width:none;margin:0;padding:0}.paper{border:0;box-shadow:none;padding:6mm;break-inside:avoid;position:relative;overflow:hidden}.paper .watermark{display:block!important;opacity:.16!important;width:118%!important;max-height:none!important;z-index:0!important;print-color-adjust:exact!important;-webkit-print-color-adjust:exact!important}.paper>*:not(.watermark){position:relative;z-index:1}.invoice-title{margin:8px}.footer{font-size:9px}}
"""
LAYOUT = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BERNAFACTURATION</title><style>""" + STYLE + """</style></head><body>
<nav class="no-print"><strong>BERNAFACTURATION</strong><a href="/">Facturation</a><a href="/products">Produits et prix</a><a href="/stock">Stock entrant/sortant</a><a href="/storage">Argent</a><a href="/daily-report">Rapport journalier</a><a href="/daily-history">Rapports enregistrés</a><a href="/history">Factures enregistrées</a><a href="/backup">Sauvegarde</a><a href="/trash">Corbeille / Restaurer</a></nav>
{% with messages = get_flashed_messages() %}{% if messages %}<div class="wrap flash">{% for m in messages %}<div class="card">{{m}}</div>{% endfor %}</div>{% endif %}{% endwith %}
<div class="wrap">{{ content|safe }}</div></body></html>"""

INVOICE = """
<div class="paper">
<img class="watermark" src="/static/vbs_logo.jpg" alt="" aria-hidden="true">
<div class="header">
<img class="logo" src="/static/vbs_logo.jpg" alt="Logo Vincent Business Services">
<div class="company"><h1>{{c.name}}</h1><b>{{c.subtitle}}</b><p>{{c.line}}</p><p>{{c.services}}</p><p>{{c.ids}}</p></div>
</div>
<div class="invoice-title">FACTURE N° <input id="number" value="{{number}}" style="width:170px;display:inline-block;text-align:center"></div>
<div class="grid">
<div><label>Date</label><input id="invoice_date" type="date" value="{{today}}"></div>
<div><label>Nom du client</label><input id="client" value="L T J" placeholder="Nom du client"></div>
<div><label>Contact</label><input id="contact" value="0813722443" placeholder="Téléphone"></div>
<div><label>Adresse</label><input id="address" value="Q. ELEMBE" placeholder="Adresse du client"></div>
</div>
<table id="items"><thead><tr><th style="width:44%">Désignation</th><th>Quantité</th><th>Prix unitaire (CDF)</th><th>Total (CDF)</th><th class="no-print">Action</th></tr></thead>
<tbody>
<tr><td><div class="suggest-wrap"><input class="pname" placeholder="Rechercher un produit..." autocomplete="off"><div class="results"></div></div></td><td><input class="qty" type="number" min="0" value="139"></td><td><input class="price" type="number" min="0" value="100"></td><td class="line-total">13 900</td><td class="no-print"><button class="danger" onclick="removeRow(this)">Supprimer</button></td></tr>
<tr><td><div class="suggest-wrap"><input class="pname" placeholder="Rechercher un produit..." autocomplete="off"><div class="results"></div></div></td><td><input class="qty" type="number" min="0" value="66"></td><td><input class="price" type="number" min="0" value="200"></td><td class="line-total">13 200</td><td class="no-print"><button class="danger" onclick="removeRow(this)">Supprimer</button></td></tr>
</tbody></table>
<div class="no-print"><button onclick="addRow()">+ Ajouter une ligne</button></div>
<div class="total">TOTAL : <span id="grand">27 100</span> CDF</div>
<div class="no-print" style="text-align:right"><button onclick="saveInvoice()">Enregistrer la facture</button><button class="secondary" onclick="window.print()">Imprimer</button></div>
<div class="footer">{{c.address1}}<br>{{c.bank}} | {{c.phones}}<br>{{c.address2}}<br>{{c.email}}<br><b>Merci pour votre confiance.</b></div>
</div>
<script>
function fmt(n){return Math.round(n||0).toLocaleString('fr-FR')}
function calc(){let sum=0;document.querySelectorAll('#items tbody tr').forEach(r=>{let q=Number(r.querySelector('.qty').value)||0,p=Number(r.querySelector('.price').value)||0,t=q*p;sum+=t;r.querySelector('.line-total').textContent=fmt(t)});document.getElementById('grand').textContent=fmt(sum)}
function addRow(){let tr=document.createElement('tr');tr.innerHTML='<td><div class="suggest-wrap"><input class="pname" placeholder="Rechercher un produit..." autocomplete="off"><div class="results"></div></div></td><td><input class="qty" type="number" min="0" value="1"></td><td><input class="price" type="number" min="0" value="0"></td><td class="line-total">0</td><td class="no-print"><button class="danger" onclick="removeRow(this)">Supprimer</button></td>';document.querySelector('#items tbody').appendChild(tr);bindRow(tr);calc()}
function removeRow(btn){let tr=btn.closest('tr');let old=tr.outerHTML;tr.remove();window.lastDeletedRow=old;calc();let b=document.getElementById('undo');if(b)b.style.display='inline-block';}
function undoRow(){if(window.lastDeletedRow){document.querySelector('#items tbody').insertAdjacentHTML('beforeend',window.lastDeletedRow);bindRow(document.querySelector('#items tbody tr:last-child'));window.lastDeletedRow=null;calc()}}
function bindRow(row){row.querySelectorAll('.qty,.price').forEach(x=>x.addEventListener('input',calc));let input=row.querySelector('.pname');let box=row.querySelector('.results');input.addEventListener('input',async()=>{let q=input.value.trim();if(q.length<1){box.style.display='none';return}let res=await fetch('/product-search?q='+encodeURIComponent(q));let arr=await res.json();box.innerHTML='';arr.forEach(p=>{let d=document.createElement('div');d.textContent=p.name+' — '+fmt(p.price)+' CDF';d.style.padding='8px';d.style.cursor='pointer';d.onclick=()=>{input.value=p.name;row.querySelector('.price').value=p.price;box.style.display='none';calc()};box.appendChild(d)});box.style.display=arr.length?'block':'none'});document.addEventListener('click',e=>{if(!row.contains(e.target))box.style.display='none'})}
document.querySelectorAll('#items tbody tr').forEach(bindRow);document.querySelectorAll('.qty,.price').forEach(x=>x.addEventListener('input',calc));calc();
async function saveInvoice(){let rows=[...document.querySelectorAll('#items tbody tr')].map(r=>({name:r.querySelector('.pname').value,qty:Number(r.querySelector('.qty').value)||0,price:Number(r.querySelector('.price').value)||0,total:(Number(r.querySelector('.qty').value)||0)*(Number(r.querySelector('.price').value)||0)}));let data={number:document.getElementById('number').value,date:document.getElementById('invoice_date').value,client:document.getElementById('client').value,contact:document.getElementById('contact').value,address:document.getElementById('address').value,items:rows,total:rows.reduce((s,r)=>s+r.total,0)};let r=await fetch('/save-invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let j=await r.json();alert(j.message)}
</script>
"""
PRODUCTS = """
<div class="card"><h2>Produits et prix</h2><p>Ajoutez vos produits et leurs prix. La recherche automatique dans la facture utilisera ces noms et prix. Aucun code produit à six chiffres n'est utilisé.</p>
<form method="post" action="/products"><div class="grid"><div><label>Nom du produit</label><input name="name" required placeholder="Ex. Impression noir et blanc"></div><div><label>Unité</label><input name="unit" value="pièce" placeholder="pièce, page, lot..."></div><div><label>Prix unitaire (CDF)</label><input name="price" type="number" min="0" step="1" required></div></div><button>Enregistrer le produit</button></form></div>
<div class="card"><h2>Catalogue</h2><table><thead><tr><th>Produit</th><th>Unité</th><th>Prix unitaire</th><th>Action</th></tr></thead><tbody>{% for p in products %}<tr><td>{{p.name}}</td><td>{{p.unit}}</td><td>{{'{:,.0f}'.format(p.price).replace(',', ' ')}} CDF</td><td><form method="post" action="/delete-product/{{p.id}}" onsubmit="return confirm('Mettre ce produit dans la corbeille ?')"><button class="danger">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="4">Aucun produit enregistré pour le moment.</td></tr>{% endfor %}</tbody></table></div>
"""
HISTORY = """
<div class="card"><h2>Factures enregistrées</h2><p class="small">Les factures sont conservées dans la base de données du logiciel.</p><table><thead><tr><th>N°</th><th>Date</th><th>Client</th><th>Total</th><th>Action</th></tr></thead><tbody>{% for i in invoices %}<tr><td>{{i.number}}</td><td>{{i.invoice_date}}</td><td>{{i.client}}</td><td>{{'{:,.0f}'.format(i.total).replace(',', ' ')}} CDF</td><td><form method="post" action="/delete-invoice/{{i.id}}"><button class="danger">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="5">Aucune facture enregistrée.</td></tr>{% endfor %}</tbody></table></div>
"""
TRASH = """
<div class="card"><h2>Corbeille — restaurer les éléments supprimés</h2><h3>Produits</h3><table><tr><th>Nom</th><th>Prix</th><th>Action</th></tr>{% for p in products %}<tr><td>{{p.name}}</td><td>{{'{:,.0f}'.format(p.price).replace(',', ' ')}} CDF</td><td><form method="post" action="/restore-product/{{p.id}}"><button>Restaurer</button></form></td></tr>{% else %}<tr><td colspan="3">Aucun produit dans la corbeille.</td></tr>{% endfor %}</table><h3>Factures</h3><table><tr><th>N°</th><th>Date</th><th>Client</th><th>Total</th><th>Action</th></tr>{% for i in invoices %}<tr><td>{{i.number}}</td><td>{{i.invoice_date}}</td><td>{{i.client}}</td><td>{{'{:,.0f}'.format(i.total).replace(',', ' ')}} CDF</td><td><form method="post" action="/restore-invoice/{{i.id}}"><button>Restaurer</button></form></td></tr>{% else %}<tr><td colspan="5">Aucune facture dans la corbeille.</td></tr>{% endfor %}</table></div>
"""
def page(content, **kwargs):
    return render_template_string(LAYOUT, content=render_template_string(content, **kwargs), **kwargs)

@app.route("/")
def home():
    with db() as con:
        count=con.execute("SELECT COUNT(*) FROM products WHERE deleted=0").fetchone()[0]
    return page(INVOICE, c=COMPANY, number="VBS-001", today=date.today().isoformat(), product_count=count)

@app.route("/products", methods=["GET","POST"])
def products():
    if request.method=="POST":
        name=request.form.get("name","").strip()
        unit=request.form.get("unit","pièce").strip() or "pièce"
        try: price=float(request.form.get("price","0"))
        except ValueError: price=0
        if name:
            with db() as con:
                try: con.execute("INSERT INTO products(name,unit,price,deleted) VALUES(?,?,?,0)",(name,unit,price))
                except sqlite3.IntegrityError:
                    con.execute("UPDATE products SET unit=?,price=?,deleted=0 WHERE name=?",(unit,price,name))
            flash("Produit enregistré.")
        return redirect(url_for("products"))
    with db() as con: rows=con.execute("SELECT * FROM products WHERE deleted=0 ORDER BY name").fetchall()
    return page(PRODUCTS, products=rows)

@app.route("/product-search")
def product_search():
    q=request.args.get("q","").strip()
    with db() as con: rows=con.execute("SELECT name,price,unit FROM products WHERE deleted=0 AND name LIKE ? ORDER BY name LIMIT 15",("%"+q+"%",)).fetchall()
    return app.response_class(json.dumps([dict(r) for r in rows], ensure_ascii=False), mimetype="application/json")

@app.route("/delete-product/<int:pid>", methods=["POST"])
def delete_product(pid):
    with db() as con: con.execute("UPDATE products SET deleted=1 WHERE id=?",(pid,))
    flash("Produit placé dans la corbeille. Vous pouvez le restaurer.")
    return redirect(url_for("products"))

@app.route("/restore-product/<int:pid>", methods=["POST"])
def restore_product(pid):
    with db() as con: con.execute("UPDATE products SET deleted=0 WHERE id=?",(pid,))
    flash("Produit restauré.")
    return redirect(url_for("trash"))

@app.route("/save-invoice", methods=["POST"])
def save_invoice():
    data=request.get_json(force=True)
    with db() as con:
        con.execute("INSERT INTO invoices(number,invoice_date,client,contact,address,items_json,total) VALUES(?,?,?,?,?,?,?)",
        (data.get("number",""),data.get("date",date.today().isoformat()),data.get("client",""),data.get("contact",""),data.get("address",""),json.dumps(data.get("items",[]),ensure_ascii=False),float(data.get("total",0))))
    return app.response_class(json.dumps({"message":"Facture enregistrée avec succès."},ensure_ascii=False),mimetype="application/json")

@app.route("/history")
def history():
    with db() as con: rows=con.execute("SELECT * FROM invoices WHERE deleted=0 ORDER BY id DESC").fetchall()
    return page(HISTORY, invoices=rows)

@app.route("/delete-invoice/<int:iid>", methods=["POST"])
def delete_invoice(iid):
    with db() as con: con.execute("UPDATE invoices SET deleted=1 WHERE id=?",(iid,))
    flash("Facture placée dans la corbeille. Vous pouvez la restaurer.")
    return redirect(url_for("history"))

@app.route("/restore-invoice/<int:iid>", methods=["POST"])
def restore_invoice(iid):
    with db() as con: con.execute("UPDATE invoices SET deleted=0 WHERE id=?",(iid,))
    flash("Facture restaurée.")
    return redirect(url_for("trash"))

@app.route("/trash")
def trash():
    with db() as con:
        ps=con.execute("SELECT * FROM products WHERE deleted=1 ORDER BY id DESC").fetchall()
        inv=con.execute("SELECT * FROM invoices WHERE deleted=1 ORDER BY id DESC").fetchall()
        moves=con.execute("SELECT * FROM cash_moves WHERE deleted=1 ORDER BY id DESC").fetchall()
    return page(TRASH, products=ps, invoices=inv) + render_template_string(CASH_TRASH, rows=moves)



STORAGE = """
<div class="card">
<h2>Stockage — Entrées, sorties et dépenses</h2>
<p>Enregistrez ici l'argent reçu (entrée) et les dépenses (sortie). Le solde se calcule automatiquement.</p>
<div class="grid">
<div><b>Total des entrées</b><h2>{{ "{:,.0f}".format(total_in).replace(",", " ") }} CDF</h2></div>
<div><b>Total des sorties / dépenses</b><h2>{{ "{:,.0f}".format(total_out).replace(",", " ") }} CDF</h2></div>
<div><b>Solde disponible</b><h2>{{ "{:,.0f}".format(total_in-total_out).replace(",", " ") }} CDF</h2></div>
</div>
<form method="post" action="/storage">
<div class="grid">
<div><label>Date</label><input type="date" name="move_date" value="{{ today }}" required></div>
<div><label>Type de mouvement</label><select name="move_type"><option>Entrée</option><option>Sortie</option></select></div>
<div><label>Catégorie</label><select name="category"><option>Vente / paiement client</option><option>Impression</option><option>Achat de matériel</option><option>Papier et consommables</option><option>Transport</option><option>Électricité</option><option>Loyer</option><option>Salaire</option><option>Autre dépense</option><option>Autre entrée</option></select></div>
<div style="grid-column:span 2"><label>Description / motif</label><input name="description" placeholder="Ex. Paiement facture du client"></div>
<div><label>Montant (CDF)</label><input type="number" name="amount" min="1" step="1" required></div>
</div><button type="submit">Enregistrer le mouvement</button>
</form>
</div>
<div class="card"><h2>Historique des mouvements</h2>
<form method="get" action="/storage" class="grid"><div><label>Filtrer par type</label><select name="type"><option value="">Tous</option><option>Entrée</option><option>Sortie</option></select></div><div><label>Recherche dans la description</label><input name="q" placeholder="Rechercher"></div><div style="align-self:end"><button type="submit">Rechercher</button></div></form>
<table><thead><tr><th>Date</th><th>Type</th><th>Catégorie</th><th>Description</th><th>Montant (CDF)</th><th class="no-print">Action</th></tr></thead><tbody>
{% for r in rows %}<tr><td>{{r.move_date}}</td><td>{{r.move_type}}</td><td>{{r.category}}</td><td>{{r.description or ""}}</td><td>{{ "{:,.0f}".format(r.amount).replace(",", " ") }}</td><td class="no-print"><form method="post" action="/delete-move/{{r.id}}" onsubmit="return confirm('Placer ce mouvement dans la corbeille ?')"><button class="danger">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="6">Aucun mouvement enregistré.</td></tr>{% endfor %}
</tbody></table></div>
"""
CASH_TRASH = """
<div class="card"><h2>Mouvements supprimés</h2><p>Vous pouvez restaurer les entrées et dépenses supprimées.</p>
<table><tr><th>Date</th><th>Type</th><th>Catégorie</th><th>Description</th><th>Montant</th><th>Action</th></tr>
{% for r in rows %}<tr><td>{{r.move_date}}</td><td>{{r.move_type}}</td><td>{{r.category}}</td><td>{{r.description or ""}}</td><td>{{ "{:,.0f}".format(r.amount).replace(",", " ") }} CDF</td><td><form method="post" action="/restore-move/{{r.id}}"><button>Restaurer</button></form></td></tr>{% else %}<tr><td colspan="6">Aucun mouvement supprimé.</td></tr>{% endfor %}
</table></div>
"""

@app.route("/storage", methods=["GET", "POST"])
def storage():
    if request.method == "POST":
        typ = request.form.get("move_type", "Entrée")
        if typ not in ("Entrée", "Sortie"): typ = "Entrée"
        amount = max(0, float(request.form.get("amount", "0") or 0))
        with db() as con:
            con.execute("INSERT INTO cash_moves(move_date,move_type,category,description,amount) VALUES(?,?,?,?,?)",
                (request.form.get("move_date", date.today().isoformat()), typ,
                 request.form.get("category", "Autre"), request.form.get("description", "").strip(), amount))
        flash("Mouvement enregistré. Les totaux et le solde ont été recalculés.")
        return redirect(url_for("storage"))
    typ=request.args.get("type","")
    q=request.args.get("q","").strip()
    with db() as con:
        total_in=con.execute("SELECT COALESCE(SUM(amount),0) FROM cash_moves WHERE deleted=0 AND move_type='Entrée'").fetchone()[0]
        total_out=con.execute("SELECT COALESCE(SUM(amount),0) FROM cash_moves WHERE deleted=0 AND move_type='Sortie'").fetchone()[0]
        sql="SELECT * FROM cash_moves WHERE deleted=0"
        args=[]
        if typ in ("Entrée","Sortie"): sql += " AND move_type=?"; args.append(typ)
        if q: sql += " AND (description LIKE ? OR category LIKE ?)"; args += ["%"+q+"%","%"+q+"%"]
        sql += " ORDER BY move_date DESC, id DESC"
        rows=con.execute(sql,args).fetchall()
    return page(STORAGE, rows=rows, total_in=total_in, total_out=total_out, today=date.today().isoformat())

@app.route("/delete-move/<int:mid>", methods=["POST"])
def delete_move(mid):
    with db() as con: con.execute("UPDATE cash_moves SET deleted=1 WHERE id=?", (mid,))
    flash("Mouvement placé dans la corbeille. Il peut être restauré.")
    return redirect(url_for("storage"))

@app.route("/restore-move/<int:mid>", methods=["POST"])
def restore_move(mid):
    with db() as con: con.execute("UPDATE cash_moves SET deleted=0 WHERE id=?", (mid,))
    flash("Mouvement restauré.")
    return redirect(url_for("trash"))


STOCK_PAGE = """
<div class="card"><h2>Stock entrant et stock sortant des produits</h2>
<div class="grid"><div><b>Entrées totales</b><h2>{{'{:g}'.format(total_in)}}</h2></div><div><b>Sorties totales</b><h2>{{'{:g}'.format(total_out)}}</h2></div><div><b>Solde de mouvements</b><h2>{{'{:g}'.format(total_in-total_out)}}</h2></div></div>
<form method="post" action="/stock"><div class="grid">
<div><label>Date</label><input type="date" name="move_date" value="{{today}}" required></div>
<div><label>Nom du produit</label><input name="product" required placeholder="Ex. Papier A4 blanc"></div>
<div><label>Type de mouvement</label><select name="move_type"><option>Entrée</option><option>Sortie</option></select></div>
<div><label>Quantité</label><input name="quantity" type="number" min="0.01" step="any" required></div>
<div><label>Unité</label><input name="unit" value="pièce" placeholder="ramette, paquet, pièce"></div>
<div><label>Motif / observation</label><input name="motif" placeholder="Achat, utilisation pour impression..."></div>
</div><button>Enregistrer le mouvement de stock</button></form></div>
<div class="card"><h2>État actuel du stock</h2><p class="small">Le solde est calculé par produit : entrées moins sorties.</p>
<table><tr><th>Produit</th><th>Unité</th><th>Entrées</th><th>Sorties</th><th>Stock restant</th></tr>{% for r in balances %}<tr><td>{{r.product}}</td><td>{{r.unit}}</td><td>{{'{:g}'.format(r.ins)}}</td><td>{{'{:g}'.format(r.outs)}}</td><td><b>{{'{:g}'.format(r.ins-r.outs)}}</b></td></tr>{% else %}<tr><td colspan="5">Aucun mouvement de stock enregistré.</td></tr>{% endfor %}</table></div>
<div class="card"><h2>Historique des mouvements</h2><table><tr><th>Date</th><th>Produit</th><th>Type</th><th>Quantité</th><th>Motif</th></tr>{% for r in rows %}<tr><td>{{r.move_date}}</td><td>{{r.product}}</td><td>{{r.move_type}}</td><td>{{'{:g}'.format(r.quantity)}} {{r.unit}}</td><td>{{r.motif}}</td></tr>{% else %}<tr><td colspan="5">Aucun mouvement.</td></tr>{% endfor %}</table></div>
"""

DAILY_PAGE = """
<div class="paper"><img class="watermark" src="/static/vbs_logo.jpg" alt="" aria-hidden="true"><div class="header"><img class="logo" src="/static/vbs_logo.jpg" alt="Logo Vincent Business Services"><div class="company"><h1>{{c.name}}</h1><b>{{c.subtitle}}</b><p>{{c.line}}</p><p>{{c.services}}</p><p>{{c.ids}}</p></div></div>
<div class="invoice-title">RAPPORT JOURNALIER DES SERVICES</div>
<div class="no-print"><form method="get" action="/daily-report" class="grid"><div><label>Date du rapport</label><input type="date" name="day" value="{{day}}"></div><div style="align-self:end"><button>Afficher cette date</button></div></form></div>
<h2>1. SERVICES EFFECTUÉS — ARGENT REÇU</h2>
<form method="post" action="/daily-service" class="no-print"><div class="grid"><div><label>Date</label><input type="date" name="report_date" value="{{day}}" required></div><div><label>Service effectué</label><input name="service" required placeholder="Logo, montage, impression..."></div><div><label>Client</label><input name="client" placeholder="Nom du client"></div><div><label>Quantité de services</label><input name="quantity" type="number" min="0.01" step="any" value="1" required></div><div><label>Produit utilisé (pour déduire le stock)</label><select name="stock_product"><option value="">Aucun produit à déduire</option>{% for p in stock_products %}<option value="{{p.product}}|||{{p.unit}}">{{p.product}} — reste {{'{:g}'.format(p.remaining)}} {{p.unit}}</option>{% endfor %}</select></div><div><label>Quantité de produit utilisée</label><input name="stock_quantity" type="number" min="0" step="any" value="0"></div><div><label>Montant reçu (CDF)</label><input name="amount" type="number" min="0" step="1" required></div><div><label>Mode de paiement</label><select name="payment"><option>Espèces</option><option>Mobile money</option><option>Banque</option><option>Crédit / non payé</option><option>Autre</option></select></div><div style="grid-column:1/-1"><label>Observation</label><input name="note"></div></div><button>Ajouter le service</button></form>
<table><tr><th>Service effectué</th><th>Client</th><th>Qté</th><th>Produit sorti</th><th>Qté sortie</th><th>Montant reçu (CDF)</th><th>Paiement</th><th class="no-print">Action</th></tr>{% for r in services %}<tr><td>{{r.service}}</td><td>{{r.client}}</td><td>{{'{:g}'.format(r.quantity)}}</td><td>{{r.stock_product or '—'}}</td><td>{% if r.stock_quantity %}{{'{:g}'.format(r.stock_quantity)}} {{r.stock_unit}}{% else %}—{% endif %}</td><td>{{'{:,.0f}'.format(r.amount).replace(',', ' ')}}</td><td>{{r.payment}}</td><td class="no-print"><form method="post" action="/daily-delete/service/{{r.id}}"><button class="danger">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="8">Aucun service enregistré pour cette date.</td></tr>{% endfor %}</table>
<div class="total">TOTAL DES SERVICES : {{'{:,.0f}'.format(total_services).replace(',', ' ')}} CDF</div>
<h2>2. DÉPENSES DU JOUR — À DÉDUIRE</h2>
<form method="post" action="/daily-expense" class="no-print"><div class="grid"><div><label>Date</label><input type="date" name="report_date" value="{{day}}" required></div><div><label>Motif de la dépense</label><input name="reason" required placeholder="Papier, encre, transport..."></div><div><label>Montant dépensé (CDF)</label><input name="amount" type="number" min="0" step="1" required></div><div style="grid-column:1/-1"><label>Observation</label><input name="note"></div></div><button>Ajouter la dépense</button></form>
<table><tr><th>Motif de la dépense</th><th>Observation</th><th>Montant (CDF)</th><th class="no-print">Action</th></tr>{% for r in expenses %}<tr><td>{{r.reason}}</td><td>{{r.note}}</td><td>{{'{:,.0f}'.format(r.amount).replace(',', ' ')}}</td><td class="no-print"><form method="post" action="/daily-delete/expense/{{r.id}}"><button class="danger">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="4">Aucune dépense enregistrée pour cette date.</td></tr>{% endfor %}</table>
<div class="total">TOTAL DES DÉPENSES : {{'{:,.0f}'.format(total_expenses).replace(',', ' ')}} CDF</div>
<div class="total" style="background:#edf7ed;border:2px solid #477a4b;padding:14px">SOLDE NET DU JOUR : {{'{:,.0f}'.format(total_services-total_expenses).replace(',', ' ')}} CDF</div>
<div class="no-print" style="text-align:right"><label for="export-format">Format du fichier</label><select id="export-format" style="max-width:220px;display:inline-block"><option value="pdf">PDF</option><option value="jpg">Image JPG</option></select><button type="button" onclick="saveDailyReport()">Enregistrer le rapport</button><a class="btn secondary" href="/daily-history">Rapports enregistrés</a></div><script>function saveDailyReport(){const day={{ day|tojson }};const fmt=document.getElementById("export-format").value;window.location.href="/daily-export?day="+encodeURIComponent(day)+"&format="+encodeURIComponent(fmt);}</script>
<div class="footer">{{c.address1}}<br>{{c.bank}} | {{c.phones}}<br>{{c.address2}}<br>{{c.email}}<br><b>Merci pour votre confiance.</b></div></div>
"""

@app.route('/stock', methods=['GET','POST'])
def stock_page():
    if request.method == 'POST':
        typ=request.form.get('move_type','Entrée')
        if typ not in ('Entrée','Sortie'): typ='Entrée'
        qty=max(0,float(request.form.get('quantity','0') or 0))
        with db() as con:
            con.execute('INSERT INTO stock_moves(move_date,product,move_type,quantity,unit,motif) VALUES(?,?,?,?,?,?)',
                (request.form.get('move_date',date.today().isoformat()),request.form.get('product','').strip(),typ,qty,request.form.get('unit','unité').strip(),request.form.get('motif','').strip()))
        flash('Mouvement de stock enregistré.')
        return redirect(url_for('stock_page'))
    with db() as con:
        rows=con.execute('SELECT * FROM stock_moves WHERE deleted=0 ORDER BY move_date DESC,id DESC').fetchall()
        balances=con.execute("SELECT product,unit,SUM(CASE WHEN move_type='Entrée' THEN quantity ELSE 0 END) ins,SUM(CASE WHEN move_type='Sortie' THEN quantity ELSE 0 END) outs FROM stock_moves WHERE deleted=0 GROUP BY product,unit ORDER BY product").fetchall()
        ti=con.execute("SELECT COALESCE(SUM(quantity),0) FROM stock_moves WHERE deleted=0 AND move_type='Entrée'").fetchone()[0]
        to=con.execute("SELECT COALESCE(SUM(quantity),0) FROM stock_moves WHERE deleted=0 AND move_type='Sortie'").fetchone()[0]
    return page(STOCK_PAGE,rows=rows,balances=balances,total_in=ti,total_out=to,today=date.today().isoformat())

@app.route('/daily-export')
def daily_export():
    """Export the selected daily report to a user-chosen Windows folder."""
    import textwrap

    day = request.args.get('day', date.today().isoformat())
    fmt = request.args.get('format', 'pdf').lower()
    if fmt not in ('pdf', 'jpg'):
        flash('Format non reconnu. Choisissez PDF ou JPG.')
        return redirect(url_for('daily_report', day=day))

    with db() as con:
        services = con.execute("SELECT * FROM daily_services WHERE deleted=0 AND report_date=? ORDER BY id", (day,)).fetchall()
        expenses = con.execute("SELECT * FROM daily_expenses WHERE deleted=0 AND report_date=? ORDER BY id", (day,)).fetchall()

    total_services = sum(float(r['amount']) for r in services)
    total_expenses = sum(float(r['amount']) for r in expenses)
    def money(value):
        return f"{value:,.0f}".replace(',', ' ')

    lines = [COMPANY['name'], COMPANY['subtitle'], 'RAPPORT JOURNALIER DES SERVICES', f'Date : {day}', '',
             '1. SERVICES EFFECTUÉS — ARGENT REÇU']
    if services:
        for r in services:
            lines.append(f"Service : {r['service']} | Client : {r['client'] or '-'} | Quantité : {r['quantity']:g} | Montant : {money(r['amount'])} CDF | Paiement : {r['payment']}")
            if r['note']:
                lines.append(f"  Observation : {r['note']}")
    else:
        lines.append('Aucun service enregistré pour cette date.')
    lines += [f'TOTAL DES SERVICES : {money(total_services)} CDF', '', '2. DÉPENSES DU JOUR — À DÉDUIRE']
    if expenses:
        for r in expenses:
            lines.append(f"Dépense : {r['reason']} | Montant : {money(r['amount'])} CDF")
            if r['note']:
                lines.append(f"  Observation : {r['note']}")
    else:
        lines.append('Aucune dépense enregistrée pour cette date.')
    lines += [f'TOTAL DES DÉPENSES : {money(total_expenses)} CDF',
              f'SOLDE NET DU JOUR : {money(total_services-total_expenses)} CDF', '',
              COMPANY['address1'], COMPANY['phones'], COMPANY['address2'], COMPANY['email'],
              'Merci pour votre confiance.']

    extensions = {'pdf': '.pdf', 'jpg': '.jpg'}
    # Le navigateur ne peut pas ouvrir la boîte de dialogue Windows sur un serveur.
    # Générer le fichier côté serveur puis le proposer au téléchargement.
    tmp = tempfile.NamedTemporaryFile(prefix='rapport_journalier_', suffix=extensions[fmt], delete=False)
    filename = tmp.name
    tmp.close()

    try:
        logo_path = os.path.join(app.root_path, 'static', 'vbs_logo.jpg')
        if fmt == 'pdf':
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from xml.sax.saxutils import escape
            page_w, page_h = A4
            doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=12*mm, bottomMargin=15*mm)
            styles = getSampleStyleSheet()
            styles.add(ParagraphStyle(name='VBSCompany', parent=styles['Title'], alignment=TA_CENTER, textColor=colors.HexColor('#173d70'), fontSize=15, leading=18, spaceAfter=3))
            styles.add(ParagraphStyle(name='VBSCenter', parent=styles['Normal'], alignment=TA_CENTER, fontSize=8, leading=10, spaceAfter=2))
            styles.add(ParagraphStyle(name='VBSSection', parent=styles['Heading2'], textColor=colors.HexColor('#173d70'), fontSize=12, leading=15, spaceBefore=10, spaceAfter=5))
            styles.add(ParagraphStyle(name='VBSCell', parent=styles['BodyText'], fontSize=8, leading=10))
            styles.add(ParagraphStyle(name='VBSTotal', parent=styles['BodyText'], alignment=TA_RIGHT, fontSize=10, leading=13))
            def watermark(canvas, document):
                canvas.saveState()
                try:
                    canvas.setFillAlpha(0.09)
                except Exception:
                    pass
                if os.path.exists(logo_path):
                    iw, ih = 1536, 512
                    ww = page_w * 0.78
                    hh = ww * ih / iw
                    canvas.drawImage(logo_path, (page_w-ww)/2, (page_h-hh)/2, width=ww, height=hh, preserveAspectRatio=True, mask='auto')
                canvas.restoreState()
            story = []
            if os.path.exists(logo_path):
                logo = RLImage(logo_path, width=58*mm, height=19.3*mm, kind='proportional')
                logo.hAlign = 'CENTER'; story += [logo, Spacer(1, 2*mm)]
            story.append(Paragraph(escape(COMPANY['name']), styles['VBSCompany']))
            story.append(Paragraph(escape(COMPANY['subtitle']), styles['VBSCenter']))
            for key in ('line','services','ids'):
                if COMPANY.get(key): story.append(Paragraph(escape(COMPANY[key]), styles['VBSCenter']))
            story += [Spacer(1, 3*mm), Table([['']], colWidths=[178*mm], rowHeights=[1.2], style=TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#173d70'))])), Spacer(1, 4*mm)]
            story.append(Paragraph('RAPPORT JOURNALIER DES SERVICES', ParagraphStyle('DailyTitle', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.HexColor('#172033'), fontSize=15, leading=18, spaceAfter=4)))
            story.append(Paragraph('Date : ' + escape(day), styles['VBSCenter']))
            story.append(Paragraph('1. SERVICES EFFECTUÉS — ARGENT REÇU', styles['VBSSection']))
            cell = styles['VBSCell']
            rows = [[Paragraph('<b>Service effectué</b>',cell), Paragraph('<b>Client</b>',cell), Paragraph('<b>Qté</b>',cell), Paragraph('<b>Montant reçu (CDF)</b>',cell), Paragraph('<b>Paiement</b>',cell)]]
            if services:
                for r in services:
                    rows.append([Paragraph(escape(str(r['service'] or '')),cell), Paragraph(escape(str(r['client'] or '-')),cell), Paragraph(escape(f"{r['quantity']:g}"),cell), Paragraph(escape(money(r['amount'])),cell), Paragraph(escape(str(r['payment'] or '')),cell)])
            else: rows.append([Paragraph('Aucun service enregistré pour cette date.',cell),'','','',''])
            t=Table(rows, colWidths=[48*mm,31*mm,13*mm,43*mm,38*mm], repeatRows=1, hAlign='LEFT')
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.6,colors.HexColor('#7c8796')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f7')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story += [t, Spacer(1,2*mm), Paragraph(f'<b>TOTAL DES SERVICES : {money(total_services)} CDF</b>',styles['VBSTotal'])]
            story.append(Paragraph('2. DÉPENSES DU JOUR — À DÉDUIRE', styles['VBSSection']))
            rows=[[Paragraph('<b>Motif de la dépense</b>',cell),Paragraph('<b>Observation</b>',cell),Paragraph('<b>Montant (CDF)</b>',cell)]]
            if expenses:
                for r in expenses: rows.append([Paragraph(escape(str(r['reason'] or '')),cell),Paragraph(escape(str(r['note'] or '')),cell),Paragraph(escape(money(r['amount'])),cell)])
            else: rows.append([Paragraph('Aucune dépense enregistrée pour cette date.',cell),'',''])
            t=Table(rows,colWidths=[62*mm,65*mm,46*mm],repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.6,colors.HexColor('#7c8796')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f7')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story += [t, Spacer(1,2*mm), Paragraph(f'<b>TOTAL DES DÉPENSES : {money(total_expenses)} CDF</b>',styles['VBSTotal']), Spacer(1,4*mm)]
            total_box=Table([[Paragraph(f'<b>SOLDE NET DU JOUR : {money(total_services-total_expenses)} CDF</b>',styles['VBSTotal'])]],colWidths=[173*mm])
            total_box.setStyle(TableStyle([('BOX',(0,0),(-1,-1),1.1,colors.HexColor('#477a4b')),('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f7fbf7')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
            story += [total_box, Spacer(1,5*mm)]
            footer = ' | '.join(str(COMPANY.get(k,'')) for k in ('address1','phones','address2','email') if COMPANY.get(k))
            if footer: story.append(Paragraph(escape(footer), styles['VBSCenter']))
            story.append(Paragraph('Merci pour votre confiance.', styles['VBSCenter']))
            doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
        elif fmt == 'docx':
            from docx import Document
            from docx.shared import Inches, Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            doc = Document()
            sec=doc.sections[0]; sec.top_margin=Inches(.45); sec.bottom_margin=Inches(.55); sec.left_margin=Inches(.55); sec.right_margin=Inches(.55)
            if os.path.exists(logo_path):
                p0=doc.add_paragraph(); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER; p0.add_run().add_picture(logo_path,width=Inches(2.4))
            p0=doc.add_paragraph(); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER
            rr=p0.add_run(COMPANY['name']); rr.bold=True; rr.font.size=Pt(16); rr.font.color.rgb=RGBColor(23,61,112)
            for k in ('subtitle','line','services','ids'):
                if COMPANY.get(k):
                    p0=doc.add_paragraph(COMPANY[k]); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER
                    for rr in p0.runs: rr.font.size=Pt(8)
            p0=doc.add_paragraph('RAPPORT JOURNALIER DES SERVICES'); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER
            for rr in p0.runs: rr.bold=True; rr.font.size=Pt(14)
            p0=doc.add_paragraph(f'Date : {day}'); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER
            def shade(cell, fill):
                shd=OxmlElement('w:shd'); shd.set(qn('w:fill'),fill); cell._tc.get_or_add_tcPr().append(shd)
            def borders(table):
                tblPr=table._tbl.tblPr; borders_el=OxmlElement('w:tblBorders')
                for edge in ('top','left','bottom','right','insideH','insideV'):
                    tag=OxmlElement('w:'+edge); tag.set(qn('w:val'),'single'); tag.set(qn('w:sz'),'6'); tag.set(qn('w:color'),'7C8796'); borders_el.append(tag)
                tblPr.append(borders_el)
            def make_table(headers, data):
                tb=doc.add_table(rows=1, cols=len(headers)); tb.alignment=WD_TABLE_ALIGNMENT.CENTER; tb.autofit=True
                for i,h in enumerate(headers): tb.rows[0].cells[i].text=h; shade(tb.rows[0].cells[i],'EAF0F7')
                for row in data:
                    cells=tb.add_row().cells
                    for i,val in enumerate(row): cells[i].text=str(val)
                borders(tb)
                for row in tb.rows:
                    for c in row.cells:
                        c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                        for p in c.paragraphs:
                            for run in p.runs: run.font.size=Pt(8)
                return tb
            doc.add_heading('1. SERVICES EFFECTUÉS — ARGENT REÇU',level=2)
            data=[[r['service'],r['client'] or '-',f"{r['quantity']:g}",f"{money(r['amount'])} CDF",r['payment']] for r in services] or [['Aucun service enregistré pour cette date.','','','','']]
            make_table(['Service effectué','Client','Qté','Montant reçu (CDF)','Paiement'],data)
            p0=doc.add_paragraph(f'TOTAL DES SERVICES : {money(total_services)} CDF'); p0.alignment=WD_ALIGN_PARAGRAPH.RIGHT
            for rr in p0.runs: rr.bold=True
            doc.add_heading('2. DÉPENSES DU JOUR — À DÉDUIRE',level=2)
            data=[[r['reason'],r['note'] or '',f"{money(r['amount'])} CDF"] for r in expenses] or [['Aucune dépense enregistrée pour cette date.','','']]
            make_table(['Motif de la dépense','Observation','Montant (CDF)'],data)
            p0=doc.add_paragraph(f'TOTAL DES DÉPENSES : {money(total_expenses)} CDF'); p0.alignment=WD_ALIGN_PARAGRAPH.RIGHT
            for rr in p0.runs: rr.bold=True
            tb=doc.add_table(rows=1,cols=1); tb.cell(0,0).text=f'SOLDE NET DU JOUR : {money(total_services-total_expenses)} CDF'; borders(tb)
            for rr in tb.cell(0,0).paragraphs[0].runs: rr.bold=True; rr.font.size=Pt(12)
            p0=doc.add_paragraph(' | '.join(str(COMPANY.get(k,'')) for k in ('address1','phones','address2','email') if COMPANY.get(k))); p0.alignment=WD_ALIGN_PARAGRAPH.CENTER
            doc.save(filename)
        else:
            from PIL import Image, ImageDraw, ImageFont
            try:
                font=ImageFont.truetype('arial.ttf',17); bold=ImageFont.truetype('arialbd.ttf',19); small=ImageFont.truetype('arial.ttf',13)
            except OSError:
                font=ImageFont.load_default(); bold=font; small=font
            W=1100; margin=48; content=W-2*margin
            try: logo=Image.open(logo_path).convert('RGBA') if os.path.exists(logo_path) else None
            except Exception: logo=None
            # Petit logo d'en-tête : ne pas l'étirer sur toute la largeur du rapport.
            logo_width=min(150, content) if logo else 0
            logo_h=int(logo.height*logo_width/logo.width) if logo else 0
            service_rows=[[str(r['service']),str(r['client'] or '-'),f"{r['quantity']:g}",money(r['amount']),str(r['payment'])] for r in services] or [['Aucun service enregistré pour cette date.','','','','']]
            expense_rows=[[str(r['reason']),str(r['note'] or ''),money(r['amount'])] for r in expenses] or [['Aucune dépense enregistrée pour cette date.','','']]
            def wrap_rows(rows, widths, fnt):
                out=[]
                for row in rows:
                    parts=[]
                    for val,w in zip(row,widths):
                        words=str(val).split(); lines=[]; cur=''
                        for word in words:
                            trial=(cur+' '+word).strip()
                            if draw.textbbox((0,0),trial,font=fnt)[2] <= w-16: cur=trial
                            else:
                                if cur: lines.append(cur)
                                cur=word
                        if cur: lines.append(cur)
                        parts.append(lines or [''])
                    out.append(parts)
                return out
            # Measure wrapped rows on a scratch image; then render crisp table grid lines.
            scratch=Image.new('RGB',(W,100),'white'); draw=ImageDraw.Draw(scratch)
            sw=[content*.34,content*.19,content*.08,content*.23,content*.16]
            ew=[content*.38,content*.39,content*.23]
            sr=wrap_rows(service_rows,sw,small); er=wrap_rows(expense_rows,ew,small)
            def rows_height(wrapped): return sum(max(36, max(len(c) for c in row)*21+14) for row in wrapped)
            H=margin+logo_h+900+rows_height(sr)+rows_height(er)+350
            image=Image.new('RGB',(W,int(H)),'white')
            # Filigrane VBS intégré au JPG lui-même, léger et derrière le texte/tableaux.
            if logo:
                try:
                    watermark=logo.copy().convert('RGBA')
                    wm_width=min(650, int(W*0.66))
                    wm_height=max(1, int(watermark.height*wm_width/watermark.width))
                    watermark=watermark.resize((wm_width,wm_height),Image.Resampling.LANCZOS)
                    alpha=watermark.getchannel('A').point(lambda a: int(a*0.13))
                    watermark.putalpha(alpha)
                    image_rgba=image.convert('RGBA')
                    image_rgba.alpha_composite(watermark,((W-wm_width)//2,max(margin+logo_h+170,(int(H*0.42)-wm_height//2))))
                    image=image_rgba.convert('RGB')
                except Exception:
                    pass
            draw=ImageDraw.Draw(image); y=margin
            if logo:
                header_logo=logo.copy()
                header_logo.thumbnail((logo_width, max(1,logo_h)), Image.Resampling.LANCZOS)
                image.paste(header_logo,( (W-header_logo.width)//2, y),header_logo if header_logo.mode=='RGBA' else None)
                draw=ImageDraw.Draw(image)
                y+=header_logo.height+12
            def center(text, fnt, fill='#172033'):
                nonlocal_y=None
                box=draw.textbbox((0,0),text,font=fnt); draw.text(((W-(box[2]-box[0]))/2,y),text,font=fnt,fill=fill)
            center(COMPANY['name'],bold,'#173d70'); y+=32
            for k in ('subtitle','line','services','ids'):
                if COMPANY.get(k): center(str(COMPANY[k]),small); y+=23
            y+=10; draw.line((margin,y,W-margin,y),fill='#173d70',width=3); y+=20
            center('RAPPORT JOURNALIER DES SERVICES',bold); y+=34; center('Date : '+day,small); y+=35
            def table(title, headers, wrapped, widths):
                nonlocal_y=None
                nonlocal y
                draw.text((margin,y),title,font=bold,fill='#173d70'); y+=34
                x_positions=[margin]
                for w in widths: x_positions.append(x_positions[-1]+int(w))
                header_lines=wrap_rows([headers], widths, small)[0]
                header_h=max(44, max(len(c) for c in header_lines)*18+14)
                draw.rectangle((margin,y,W-margin,y+header_h),fill='#eaf0f7',outline='#7c8796',width=2)
                for x in x_positions[1:-1]: draw.line((x,y,x,y+header_h),fill='#7c8796',width=2)
                for i,lines0 in enumerate(header_lines):
                    for j,txt in enumerate(lines0): draw.text((x_positions[i]+7,y+6+j*18),txt,font=small,fill='#172033')
                y+=header_h
                for row in wrapped:
                    rh=max(36,max(len(c) for c in row)*21+12)
                    draw.rectangle((margin,y,W-margin,y+rh),outline='#7c8796',width=2)
                    for x in x_positions[1:-1]: draw.line((x,y,x,y+rh),fill='#7c8796',width=2)
                    for i,lines0 in enumerate(row):
                        for j,txt in enumerate(lines0): draw.text((x_positions[i]+7,y+6+j*21),txt,font=small,fill='#172033')
                    y+=rh
                y+=10
            table('1. SERVICES EFFECTUÉS — ARGENT REÇU',['Service effectué','Client','Qté','Montant reçu (CDF)','Paiement'],sr,sw)
            draw.text((margin,y),f'TOTAL DES SERVICES : {money(total_services)} CDF',font=bold,fill='#172033'); y+=42
            table('2. DÉPENSES DU JOUR — À DÉDUIRE',['Motif de la dépense','Observation','Montant (CDF)'],er,ew)
            draw.text((margin,y),f'TOTAL DES DÉPENSES : {money(total_expenses)} CDF',font=bold,fill='#172033'); y+=45
            draw.rectangle((margin,y,W-margin,y+58),outline='#477a4b',width=3)
            draw.text((margin+14,y+15),f'SOLDE NET DU JOUR : {money(total_services-total_expenses)} CDF',font=bold,fill='#172033'); y+=80
            footer=' | '.join(str(COMPANY.get(k,'')) for k in ('address1','phones','address2','email') if COMPANY.get(k))
            draw.text((margin,y),footer,font=small,fill='#475569')
            # Export as portrait JPG; retain every row and extend the canvas if needed.
            final_h=max(y+70, image.height, int(W*1.414))
            if image.height < final_h:
                portrait=Image.new('RGB',(W,final_h),'white'); portrait.paste(image,(0,0)); image=portrait
            # Enregistrer toute la hauteur réellement dessinée : ne jamais couper les totaux ou le pied de page.
            image.crop((0,0,W,final_h)).save(filename,'JPEG',quality=95,dpi=(180,180))
    except ImportError as exc:
        try: os.unlink(filename)
        except OSError: pass
        missing = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
        flash(f'Le module {missing} est nécessaire pour ce format.')
        return redirect(url_for('daily_report', day=day))
    except Exception as exc:
        try: os.unlink(filename)
        except OSError: pass
        flash(f'Échec de la création du rapport : {exc}')
        return redirect(url_for('daily_report', day=day))
    return send_file(filename, as_attachment=True, download_name=f"rapport_journalier_{day}{extensions[fmt]}", mimetype="application/pdf" if fmt == "pdf" else "image/jpeg")


@app.route('/daily-report')
def daily_report():
    day=request.args.get('day',date.today().isoformat())
    with db() as con:
        sv=con.execute('SELECT * FROM daily_services WHERE deleted=0 AND report_date=? ORDER BY id',(day,)).fetchall()
        ex=con.execute('SELECT * FROM daily_expenses WHERE deleted=0 AND report_date=? ORDER BY id',(day,)).fetchall()
        stock_products=con.execute("SELECT product,unit, SUM(CASE WHEN move_type='Entrée' THEN quantity ELSE -quantity END) AS remaining FROM stock_moves WHERE deleted=0 GROUP BY product,unit HAVING remaining>0 ORDER BY product,unit").fetchall()
    return page(DAILY_PAGE,c=COMPANY,day=day,services=sv,expenses=ex,stock_products=stock_products,total_services=sum(float(r['amount']) for r in sv),total_expenses=sum(float(r['amount']) for r in ex))

@app.route('/daily-service',methods=['POST'])
def add_daily_service():
    f=request.form
    day=f.get('report_date',date.today().isoformat())
    stock_choice=f.get('stock_product','').strip()
    if '|||' in stock_choice:
        product, selected_unit = stock_choice.split('|||', 1)
    else:
        product, selected_unit = stock_choice, ''
    used=float(f.get('stock_quantity','0') or 0)
    if used < 0:
        flash('La quantité utilisée ne peut pas être négative.')
        return redirect(url_for('daily_report',day=day))
    with db() as con:
        unit=''
        if product and used > 0:
            unit_row=con.execute("SELECT unit, SUM(CASE WHEN move_type='Entrée' THEN quantity ELSE -quantity END) remaining FROM stock_moves WHERE deleted=0 AND product=? AND (?='' OR unit=?) GROUP BY unit ORDER BY remaining DESC LIMIT 1",(product,selected_unit,selected_unit)).fetchone()
            if not unit_row:
                flash('Ce produit n’existe pas dans le stock. Enregistrez d’abord son entrée.')
                return redirect(url_for('daily_report',day=day))
            unit=unit_row['unit'] or 'unité'
            available=float(unit_row['remaining'] or 0)
            if used > available:
                flash(f'Stock insuffisant pour {product} : disponible {available:g} {unit}, demandé {used:g}.')
                return redirect(url_for('daily_report',day=day))
        cur=con.execute('INSERT INTO daily_services(report_date,service,client,quantity,amount,payment,note,stock_product,stock_quantity,stock_unit) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (day,f.get('service','').strip(),f.get('client','').strip(),float(f.get('quantity','1') or 1),float(f.get('amount','0') or 0),f.get('payment','Espèces'),f.get('note','').strip(),product,used,unit))
        service_id=cur.lastrowid
        if product and used > 0:
            con.execute("INSERT INTO stock_moves(move_date,product,move_type,quantity,unit,motif,daily_service_id) VALUES(?,?,?,?,?,?,?)",
                (day,product,'Sortie',used,unit,f"Utilisation automatique — rapport journalier : {f.get('service','').strip()}",service_id))
    flash('Service ajouté au rapport journalier.' + (f' Stock de {product} diminué de {used:g} {unit}.' if product and used > 0 else ' Aucun produit déduit du stock.'))
    return redirect(url_for('daily_report',day=day))

@app.route('/daily-expense',methods=['POST'])
def add_daily_expense():
    f=request.form
    with db() as con:
        con.execute('INSERT INTO daily_expenses(report_date,reason,amount,note) VALUES(?,?,?,?)',(f.get('report_date',date.today().isoformat()),f.get('reason','').strip(),float(f.get('amount','0') or 0),f.get('note','').strip()))
    flash('Dépense ajoutée au rapport journalier.')
    return redirect(url_for('daily_report',day=f.get('report_date',date.today().isoformat())))

@app.route('/daily-delete/<kind>/<int:item_id>',methods=['POST'])
def daily_delete(kind,item_id):
    table='daily_services' if kind=='service' else 'daily_expenses'
    with db() as con:
        con.execute(f'UPDATE {table} SET deleted=1 WHERE id=?',(item_id,))
        if kind == 'service':
            con.execute('UPDATE stock_moves SET deleted=1 WHERE daily_service_id=? AND deleted=0',(item_id,))
    flash('Ligne retirée du rapport. La sortie de stock liée a aussi été annulée si elle existait.')
    return redirect(request.referrer or url_for('daily_report'))

@app.route('/daily-history')
def daily_history():
    with db() as con:
        sv=con.execute('SELECT report_date,COUNT(*) n,SUM(amount) total FROM daily_services WHERE deleted=0 GROUP BY report_date').fetchall()
        ex=con.execute('SELECT report_date,SUM(amount) total FROM daily_expenses WHERE deleted=0 GROUP BY report_date').fetchall()
    rows={r['report_date']:{'day':r['report_date'],'n':r['n'],'services':r['total'] or 0,'expenses':0} for r in sv}
    for r in ex: rows.setdefault(r['report_date'],{'day':r['report_date'],'n':0,'services':0,'expenses':0})['expenses']=r['total'] or 0
    content="""<div class='card'><h2>Rapports journaliers enregistrés</h2><p>Choisissez une date pour ouvrir et imprimer le rapport complet.</p><table><tr><th>Date</th><th>Nombre de services</th><th>Total services (CDF)</th><th>Total dépenses (CDF)</th><th>Solde net (CDF)</th><th>Action</th></tr>{% for r in rows %}<tr><td>{{r.day}}</td><td>{{r.n}}</td><td>{{'{:,.0f}'.format(r.services).replace(',', ' ')}}</td><td>{{'{:,.0f}'.format(r.expenses).replace(',', ' ')}}</td><td><b>{{'{:,.0f}'.format(r.services-r.expenses).replace(',', ' ')}}</b></td><td><a class='btn' href='/daily-report?day={{r.day}}'>Ouvrir</a></td></tr>{% else %}<tr><td colspan='6'>Aucun rapport enregistré pour le moment.</td></tr>{% endfor %}</table></div>"""
    return page(content,rows=sorted(rows.values(),key=lambda x:x['day'],reverse=True))

@app.route("/backup")
def backup():
    import shutil
    os.makedirs(os.path.join(DATA_DIR, "sauvegardes"), exist_ok=True)
    name="bernard_facturation_"+date.today().strftime("%Y%m%d")+".db"
    target=os.path.join(DATA_DIR,"sauvegardes",name)
    shutil.copy2(DB_PATH,target)
    flash("Sauvegarde créée : sauvegardes/"+name)
    return redirect(url_for("storage"))


if __name__ == "__main__":
    print("BERNAFACTURATION est lancé. Ouvrez http://127.0.0.1:5000 dans le navigateur.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
