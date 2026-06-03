from flask import Flask, request, jsonify, render_template, send_from_directory, redirect
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import stripe
import urllib.request
import json as _json

# Chiavi Stripe — da sostituire con le tue dopo la registrazione su stripe.com
STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', 'pk_test_INSERISCI_LA_TUA_CHIAVE_PUBBLICA')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_INSERISCI_LA_TUA_CHIAVE_SEGRETA')
stripe.api_key = STRIPE_SECRET_KEY

# Prezzi in centesimi (Stripe vuole i centesimi)
PREZZI = {
    'city_mezza':     2500,   # €25
    'city_giornata':  3000,   # €30
    'mtb_mezza':      4000,   # €40
    'mtb_giornata':   5000,   # €50
    'gruppo_mezza':   8000,   # €80
    'gruppo_giornata':18000,  # €180
    'supplemento_notte': 1000, # €10
}

# ── TELEGRAM ─────────────────────────────────────────────────────────────
# Inserisci qui i tuoi valori dopo aver creato il bot (vedi istruzioni)
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', 'INSERISCI_IL_TOKEN_DEL_BOT')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'INSERISCI_IL_TUO_CHAT_ID')

def invia_telegram(testo):
    """Invia un messaggio Telegram al proprietario."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = _json.dumps({'chat_id': TELEGRAM_CHAT_ID, 'text': testo, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Telegram] Errore invio notifica: {e}")
# ─────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'database/prenotazioni.db'))
# Su Render usa /data/prenotazioni.db
if os.path.exists('/data'):
    DB_PATH = '/data/prenotazioni.db'


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS prenotazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            email TEXT NOT NULL,
            telefono TEXT NOT NULL,
            data_ritiro TEXT NOT NULL,
            ora_ritiro TEXT NOT NULL,
            num_bici INTEGER NOT NULL,
            tipo_bici TEXT DEFAULT 'city',
            durata TEXT DEFAULT 'mezza',
            tipo_percorso TEXT,
            indirizzo_consegna TEXT,
            note TEXT,
            importo_totale INTEGER DEFAULT 0,
            stato TEXT DEFAULT 'in attesa',
            pagamento_stato TEXT DEFAULT 'non pagato',
            stripe_session_id TEXT,
            creata_il TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Aggiunge le colonne mancanti se il DB esiste già dalla versione precedente
    colonne_da_aggiungere = [
        ('tipo_bici',        "TEXT DEFAULT 'city'"),
        ('durata',           "TEXT DEFAULT 'mezza'"),
        ('importo_totale',   "INTEGER DEFAULT 0"),
        ('pagamento_stato',  "TEXT DEFAULT 'non pagato'"),
        ('stripe_session_id',"TEXT"),
    ]
    colonne_esistenti = [row[1] for row in c.execute("PRAGMA table_info(prenotazioni)").fetchall()]
    for nome_col, definizione in colonne_da_aggiungere:
        if nome_col not in colonne_esistenti:
            c.execute(f"ALTER TABLE prenotazioni ADD COLUMN {nome_col} {definizione}")
    conn.commit()
    conn.close()

# Eseguito subito all'avvio — funziona sia con 'python app.py' che con gunicorn (Render)
init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/mappa')
def mappa():
    return render_template('mappa.html')

@app.route('/api/calcola-prezzo', methods=['POST'])
def calcola_prezzo():
    data = request.json
    tipo_bici = data.get('tipo_bici', 'city')
    durata = data.get('durata', 'mezza')
    num_bici = int(data.get('num_bici', 1))
    ora_ritiro = data.get('ora_ritiro', '09:00')

    # Prezzo base per bici
    chiave = f"{tipo_bici}_{durata}"
    prezzo_base = PREZZI.get(chiave, 2500)

    # Supplemento notturno (oltre le 21:00)
    ora = int(ora_ritiro.split(':')[0])
    supplemento = PREZZI['supplemento_notte'] if ora >= 21 else 0

    # Pacchetto gruppo include 4 bici
    if tipo_bici == 'gruppo':
        totale = prezzo_base + supplemento
    else:
        totale = (prezzo_base * num_bici) + supplemento

    return jsonify({
        'totale_centesimi': totale,
        'totale_euro': totale / 100,
        'supplemento_notte': supplemento > 0,
        'dettaglio': f"{'Mezza giornata' if durata == 'mezza' else 'Giornata intera'} × {num_bici} bici" + (' + supplemento notturno €10' if supplemento else '')
    })

@app.route('/api/prenota', methods=['POST'])
def prenota():
    data = request.json
    try:
        tipo_bici = data.get('tipo_bici', 'city')
        durata = data.get('durata', 'mezza')
        num_bici = int(data.get('num_bici', 1))
        ora_ritiro = data.get('ora_ritiro', '09:00')

        # Calcola totale
        chiave = f"{tipo_bici}_{durata}"
        prezzo_base = PREZZI.get(chiave, 2500)
        ora = int(ora_ritiro.split(':')[0])
        supplemento = PREZZI['supplemento_notte'] if ora >= 21 else 0
        if tipo_bici == 'gruppo':
            totale = prezzo_base + supplemento
        else:
            totale = (prezzo_base * num_bici) + supplemento

        # Salva prenotazione in stato "non pagato"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO prenotazioni (nome, cognome, email, telefono, data_ritiro, ora_ritiro,
            num_bici, tipo_bici, durata, tipo_percorso, indirizzo_consegna, note,
            importo_totale, stato, pagamento_stato)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'in attesa', 'non pagato')
        ''', (
            data['nome'], data['cognome'], data['email'], data['telefono'],
            data['data_ritiro'], data['ora_ritiro'], num_bici,
            tipo_bici, durata,
            data.get('tipo_percorso', ''), data.get('indirizzo_consegna', ''),
            data.get('note', ''), totale
        ))
        conn.commit()
        pid = c.lastrowid
        conn.close()

        # Descrizione per Stripe
        nomi_bici = {'city': 'E-Bike City', 'mtb': 'E-MTB Trail', 'gruppo': 'Pacchetto Gruppo'}
        nome_bici = nomi_bici.get(tipo_bici, 'E-Bike')
        durata_label = 'Mezza giornata' if durata == 'mezza' else 'Giornata intera'
        descrizione = f"{nome_bici} – {durata_label} × {num_bici} | {data['data_ritiro']} ore {ora_ritiro}"
        if supplemento:
            descrizione += ' (+supplemento notturno)'

        # Crea sessione Stripe
        base_url = request.host_url.rstrip('/')
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': f'ZingaroEbike – {nome_bici}',
                        'description': descrizione,
                    },
                    'unit_amount': totale,
                },
                'quantity': 1,
            }],
            mode='payment',
            customer_email=data['email'],
            success_url=f"{base_url}/pagamento-ok?id={pid}",
            cancel_url=f"{base_url}/pagamento-annullato?id={pid}",
            metadata={'prenotazione_id': str(pid)}
        )

        # Salva session id
        conn = sqlite3.connect(DB_PATH)
        conn.execute('UPDATE prenotazioni SET stripe_session_id=? WHERE id=?', (session.id, pid))
        conn.commit()
        conn.close()

        # Notifica Telegram — nuova prenotazione in attesa di pagamento
        nomi_bici_label = {'city': '🚲 E-Bike City', 'mtb': '🚵 E-MTB Trail', 'gruppo': '👥 Pacchetto Gruppo'}
        invia_telegram(
            f"🔔 <b>Nuova prenotazione #{pid}</b>\n\n"
            f"👤 {data['nome']} {data['cognome']}\n"
            f"📧 {data['email']}\n"
            f"📱 {data['telefono']}\n"
            f"📅 {data['data_ritiro']} ore {data['ora_ritiro']}\n"
            f"🚴 {nomi_bici_label.get(tipo_bici, tipo_bici)} × {num_bici}\n"
            f"⏱️ {'Mezza giornata' if durata == 'mezza' else 'Giornata intera'}\n"
            f"💶 Totale: €{totale/100:.2f}\n"
            f"📍 {data.get('indirizzo_consegna','—')}\n\n"
            f"⏳ <i>In attesa del pagamento Stripe</i>"
        )

        return jsonify({'success': True, 'checkout_url': session.url, 'id': pid})

    except Exception as e:
        return jsonify({'success': False, 'errore': str(e)}), 500

@app.route('/contratto')
def contratto():
    return render_template('contratto.html')

@app.route('/pagamento-ok')
def pagamento_ok():
    pid = request.args.get('id')
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE prenotazioni SET pagamento_stato='pagato', stato='confermata' WHERE id=?", (pid,))
    conn.commit()
    # Recupera i dati per la notifica
    c = conn.cursor()
    c.execute('SELECT nome, cognome, data_ritiro, ora_ritiro, importo_totale FROM prenotazioni WHERE id=?', (pid,))
    row = c.fetchone()
    conn.close()
    if row:
        invia_telegram(
            f"✅ <b>PAGAMENTO CONFERMATO – #{pid}</b>\n\n"
            f"👤 {row[0]} {row[1]}\n"
            f"📅 {row[2]} ore {row[3]}\n"
            f"💶 €{row[4]/100:.2f} ricevuti\n\n"
            f"🎉 Prenotazione confermata!"
        )
    return render_template('pagamento_ok.html', id=pid)

@app.route('/pagamento-annullato')
def pagamento_annullato():
    pid = request.args.get('id')
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE prenotazioni SET pagamento_stato='annullato', stato='annullata' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return render_template('pagamento_annullato.html')

@app.route('/api/prenotazioni', methods=['GET'])
def get_prenotazioni():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM prenotazioni ORDER BY data_ritiro DESC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/prenotazioni/<int:pid>/stato', methods=['PUT'])
def aggiorna_stato(pid):
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE prenotazioni SET stato=? WHERE id=?', (data['stato'], pid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/disponibilita', methods=['GET'])
def disponibilita():
    data = request.args.get('data')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(num_bici) FROM prenotazioni WHERE data_ritiro=? AND stato != 'annullata'", (data,))
    row = c.fetchone()
    conn.close()
    bici_prenotate = row[0] or 0
    bici_totali = 10
    return jsonify({'disponibili': bici_totali - bici_prenotate, 'totali': bici_totali})

if __name__ == '__main__':
    init_db()
    print("\n🚴 ZingaroEbike avviato!")
    print("👉 Apri nel browser: http://localhost:5000")
    print("👉 Admin: http://localhost:5000/admin\n")
    app.run(debug=True, port=5000)
