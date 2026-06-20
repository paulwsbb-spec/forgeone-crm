import sqlite3
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(__file__))
DB_PATH = os.path.join(DATA_DIR, 'crm.db')
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'public', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_db():
    conn = get_db()
    cols = [r['name'] for r in conn.execute("PRAGMA table_info(prospects)").fetchall()]
    for col, typedef in [
        ('source', 'TEXT'), ('valeur_estimee', 'TEXT'),
        ('situation', 'TEXT'), ('obstacles', 'TEXT'), ('prochain_pas', 'TEXT'),
        ('tag', 'TEXT'), ('premier_contact', 'TEXT'),
    ]:
        if col not in cols:
            conn.execute(f'ALTER TABLE prospects ADD COLUMN {col} {typedef}')
    conn.commit()
    conn.close()

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS prospects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            instagram TEXT NOT NULL,
            secteur TEXT,
            site_web TEXT,
            lien_profil TEXT,
            score INTEGER DEFAULT 0,
            m1 INTEGER DEFAULT 0,
            statut TEXT DEFAULT 'A DM',
            quali INTEGER DEFAULT 0,
            dead INTEGER DEFAULT 0,
            notes TEXT,
            a_vu_video INTEGER DEFAULT 0,
            rdv_propose INTEGER DEFAULT 0,
            rdv_booke INTEGER DEFAULT 0,
            relance_count INTEGER DEFAULT 0,
            screenshot TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER NOT NULL,
            instagram TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            ts TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            temps_heures REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    ''')
    conn.commit()
    conn.close()

def log_activity(conn, prospect_id, instagram, action, old_value=None, new_value=None):
    conn.execute(
        'INSERT INTO activity_log (prospect_id, instagram, action, old_value, new_value) VALUES (?,?,?,?,?)',
        (prospect_id, instagram, action, str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None)
    )

init_db()
migrate_db()

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# --- PROSPECTS ---

@app.route('/api/prospects', methods=['GET'])
def get_prospects():
    statut = request.args.get('statut')
    search = request.args.get('search', '')
    conn = get_db()
    if statut and statut != 'ALL':
        rows = conn.execute(
            'SELECT * FROM prospects WHERE statut=? AND (instagram LIKE ? OR secteur LIKE ?) ORDER BY updated_at DESC',
            (statut, f'%{search}%', f'%{search}%')
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM prospects WHERE instagram LIKE ? OR secteur LIKE ? ORDER BY updated_at DESC',
            (f'%{search}%', f'%{search}%')
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/prospects', methods=['POST'])
def create_prospect():
    data = request.json
    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO prospects (date, instagram, secteur, site_web, lien_profil, score, m1, statut, quali, dead, notes, a_vu_video, rdv_propose, rdv_booke, relance_count)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (data.get('date', datetime.now().strftime('%Y-%m-%d')),
         data.get('instagram',''), data.get('secteur',''), data.get('site_web',''),
         data.get('lien_profil',''), data.get('score',0), data.get('m1',0),
         data.get('statut','A DM'), data.get('quali',0), data.get('dead',0),
         data.get('notes',''), data.get('a_vu_video',0), data.get('rdv_propose',0),
         data.get('rdv_booke',0), data.get('relance_count',0))
    )
    pid = cur.lastrowid
    ig = data.get('instagram','')
    log_activity(conn, pid, ig, 'prospect_ajouté', new_value=data.get('statut','A DM'))
    if data.get('m1'): log_activity(conn, pid, ig, 'm1_envoyé', new_value='1')
    if data.get('statut') and data.get('statut') != 'A DM':
        log_activity(conn, pid, ig, 'statut_changé', old_value='A DM', new_value=data.get('statut'))
    conn.commit()
    row = conn.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/api/prospects/<int:pid>', methods=['GET'])
def get_prospect(pid):
    conn = get_db()
    row = conn.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    logs = conn.execute('SELECT * FROM activity_log WHERE prospect_id=? ORDER BY ts DESC', (pid,)).fetchall()
    conn.close()
    data = dict(row)
    data['historique'] = [dict(l) for l in logs]
    return jsonify(data)

@app.route('/api/prospects/<int:pid>', methods=['PUT'])
def update_prospect(pid):
    data = request.json
    fields = ['date','instagram','secteur','site_web','lien_profil','score','m1','statut',
              'quali','dead','notes','a_vu_video','rdv_propose','rdv_booke','relance_count','screenshot',
              'source','valeur_estimee','situation','obstacles','prochain_pas','tag','premier_contact']
    sets = ', '.join(f'{f}=?' for f in fields if f in data)
    vals = [data[f] for f in fields if f in data]
    if not sets:
        return jsonify({'error': 'no fields'}), 400
    conn = get_db()
    old = conn.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    conn.execute(f'UPDATE prospects SET {sets}, updated_at=datetime("now") WHERE id=?', vals + [pid])
    ig = old['instagram'] if old else data.get('instagram','')
    # Log meaningful changes
    if old:
        if 'statut' in data and data['statut'] != old['statut']:
            log_activity(conn, pid, ig, 'statut_changé', old_value=old['statut'], new_value=data['statut'])
        if 'm1' in data and int(data['m1']) != int(old['m1']):
            log_activity(conn, pid, ig, 'm1_envoyé' if data['m1'] else 'm1_annulé', old_value=old['m1'], new_value=data['m1'])
        if 'quali' in data and int(data['quali']) != int(old['quali']):
            log_activity(conn, pid, ig, 'qualifié' if data['quali'] else 'déqualifié', new_value=data['quali'])
        if 'rdv_propose' in data and int(data['rdv_propose']) != int(old['rdv_propose']):
            log_activity(conn, pid, ig, 'rdv_proposé' if data['rdv_propose'] else 'rdv_proposé_annulé')
        if 'rdv_booke' in data and int(data['rdv_booke']) != int(old['rdv_booke']):
            log_activity(conn, pid, ig, 'rdv_booké' if data['rdv_booke'] else 'rdv_booké_annulé')
        if 'dead' in data and int(data['dead']) != int(old['dead']):
            log_activity(conn, pid, ig, 'dead' if data['dead'] else 'réactivé')
        if 'a_vu_video' in data and int(data['a_vu_video']) != int(old['a_vu_video']):
            log_activity(conn, pid, ig, 'a_vu_vidéo' if data['a_vu_video'] else 'vidéo_annulée')
        if 'relance_count' in data and int(data['relance_count']) > int(old['relance_count'] or 0):
            log_activity(conn, pid, ig, 'relance_envoyée', new_value=data['relance_count'])
    conn.commit()
    row = conn.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row))

@app.route('/api/prospects/<int:pid>', methods=['DELETE'])
def delete_prospect(pid):
    conn = get_db()
    conn.execute('DELETE FROM prospects WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/prospects/upload/<int:pid>', methods=['POST'])
def upload_screenshot(pid):
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400
    filename = f'prospect_{pid}_{int(datetime.now().timestamp())}{os.path.splitext(f.filename)[1]}'
    f.save(os.path.join(UPLOAD_DIR, filename))
    url = f'/uploads/{filename}'
    conn = get_db()
    conn.execute('UPDATE prospects SET screenshot=?, updated_at=datetime("now") WHERE id=?', (url, pid))
    conn.commit()
    conn.close()
    return jsonify({'url': url})

@app.route('/api/prospects/import', methods=['POST'])
def import_prospects():
    data = request.json
    prospects = data.get('prospects', [])
    conn = get_db()
    inserted = 0
    for p in prospects:
        try:
            conn.execute(
                '''INSERT INTO prospects (date, instagram, secteur, site_web, lien_profil, score, statut, notes)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (p.get('date', datetime.now().strftime('%Y-%m-%d')),
                 p.get('instagram',''), p.get('secteur',''), p.get('site_web',''),
                 p.get('lien_profil',''), p.get('score',0),
                 p.get('statut','A DM'), p.get('notes',''))
            )
            inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({'inserted': inserted})

# --- ACTIVITY LOG ---

@app.route('/api/activity', methods=['GET'])
def get_activity():
    period = request.args.get('period', 'day')
    limit = request.args.get('limit', 100)
    conn = get_db()
    if period == 'day':
        where = "date(ts) = date('now')"
    elif period == 'week':
        where = "ts >= datetime('now', '-7 days')"
    elif period == 'month':
        where = "ts >= datetime('now', '-30 days')"
    else:
        where = '1=1'
    rows = conn.execute(
        f'SELECT * FROM activity_log WHERE {where} ORDER BY ts DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/sessions/auto', methods=['GET'])
def get_sessions_auto():
    period = request.args.get('period', 'day')
    conn = get_db()

    if period == 'day':
        group = "date(ts)"
        since = "ts >= datetime('now', '-30 days')"
    elif period == 'week':
        group = "strftime('%Y-W%W', ts)"
        since = "ts >= datetime('now', '-90 days')"
    else:
        group = "strftime('%Y-%m', ts)"
        since = "ts >= datetime('now', '-365 days')"

    rows = conn.execute(f'''
        SELECT
            {group} as periode,
            SUM(CASE WHEN action='prospect_ajouté' THEN 1 ELSE 0 END) as nouveaux_prospects,
            SUM(CASE WHEN action='m1_envoyé' THEN 1 ELSE 0 END) as m1_envoyes,
            SUM(CASE WHEN action='statut_changé' AND new_value='En cours' THEN 1 ELSE 0 END) as reponses,
            SUM(CASE WHEN action='qualifié' THEN 1 ELSE 0 END) as qualifies,
            SUM(CASE WHEN action='rdv_proposé' THEN 1 ELSE 0 END) as rdv_proposes,
            SUM(CASE WHEN action='rdv_booké' THEN 1 ELSE 0 END) as rdv_bookes,
            SUM(CASE WHEN action='relance_envoyée' THEN 1 ELSE 0 END) as relances,
            SUM(CASE WHEN action='dead' THEN 1 ELSE 0 END) as dead,
            COUNT(DISTINCT CASE WHEN action='prospect_ajouté' THEN prospect_id END) as prospects_uniques
        FROM activity_log
        WHERE {since}
        GROUP BY {group}
        ORDER BY periode DESC
    ''').fetchall()

    sessions_manual = {}
    try:
        for r in conn.execute('SELECT date, temps_heures, notes FROM sessions').fetchall():
            sessions_manual[r['date']] = dict(r)
    except Exception:
        pass

    result = []
    for r in rows:
        d = dict(r)
        manual = sessions_manual.get(d.get('periode',''), {})
        d['temps_heures'] = manual.get('temps_heures', 0)
        d['notes'] = manual.get('notes', '')
        result.append(d)

    conn.close()
    return jsonify(result)

# --- SESSIONS (temps travaillé uniquement — le reste est auto) ---

@app.route('/api/sessions', methods=['POST'])
def create_session():
    data = request.json
    conn = get_db()
    existing = conn.execute('SELECT id FROM sessions WHERE date=?', (data.get('date'),)).fetchone()
    if existing:
        conn.execute('UPDATE sessions SET temps_heures=?, notes=? WHERE date=?',
                     (data.get('temps_heures',0), data.get('notes',''), data.get('date')))
        sid = existing['id']
    else:
        cur = conn.execute(
            'INSERT INTO sessions (date, temps_heures, notes) VALUES (?,?,?)',
            (data.get('date', datetime.now().strftime('%Y-%m-%d')),
             data.get('temps_heures',0), data.get('notes',''))
        )
        sid = cur.lastrowid
    conn.commit()
    row = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

# --- DASHBOARD STATS ---

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    totals = conn.execute('''
        SELECT
            COUNT(*) as total_prospects,
            SUM(m1) as total_m1,
            SUM(CASE WHEN statut != "A DM" AND statut != "Dead" THEN 1 ELSE 0 END) as total_en_cours,
            SUM(quali) as total_quali,
            SUM(a_vu_video) as total_video,
            SUM(rdv_propose) as total_rdv_propose,
            SUM(rdv_booke) as total_rdv_booke,
            SUM(dead) as total_dead
        FROM prospects
    ''').fetchone()
    sessions_total = conn.execute('''
        SELECT
            COUNT(CASE WHEN action='prospect_ajouté' THEN 1 END) as new_conv,
            COUNT(CASE WHEN action='rdv_proposé' THEN 1 END) as rdv_proposes,
            COUNT(CASE WHEN action='rdv_booké' THEN 1 END) as rdv_bookes,
            COUNT(CASE WHEN action='relance_envoyée' THEN 1 END) as relances,
            0 as temps_heures,
            0 as retour
        FROM activity_log
    ''').fetchone()
    by_statut = conn.execute('''
        SELECT statut, COUNT(*) as count FROM prospects GROUP BY statut
    ''').fetchall()
    recent = conn.execute('''
        SELECT date(ts) as date,
               COUNT(CASE WHEN action='prospect_ajouté' THEN 1 END) as new_conv
        FROM activity_log
        WHERE ts >= datetime('now', '-14 days')
        GROUP BY date(ts)
        ORDER BY date DESC LIMIT 14
    ''').fetchall()
    conn.close()
    return jsonify({
        'prospects': dict(totals),
        'sessions': dict(sessions_total),
        'by_statut': [dict(r) for r in by_statut],
        'recent': [dict(r) for r in recent]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=False)
