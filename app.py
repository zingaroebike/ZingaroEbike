from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

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
            tipo_percorso TEXT,
            indirizzo_consegna TEXT,
            note TEXT,
            stato TEXT DEFAULT 'in attesa',
            creata_il TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/mappa')
def mappa():
    return render_template('mappa.html')

@app.route('/api/prenota', methods=['POST'])
def prenota():
    data = request.json
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO prenotazioni (nome, cognome, email, telefono, data_ritiro, ora_ritiro, num_bici, tipo_percorso, indirizzo_consegna, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['nome'], data['cognome'], data['email'], data['telefono'],
            data['data_ritiro'], data['ora_ritiro'], data['num_bici'],
            data.get('tipo_percorso', ''), data.get('indirizzo_consegna', ''), data.get('note', '')
        ))
        conn.commit()
        pid = c.lastrowid
        conn.close()
        return jsonify({'success': True, 'id': pid, 'messaggio': f'Prenotazione #{pid} ricevuta! Ti contatteremo presto.'})
    except Exception as e:
        return jsonify({'success': False, 'errore': str(e)}), 500

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
