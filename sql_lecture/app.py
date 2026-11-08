"""Page web SQL en LECTURE SEULE sur la base foot (application Python cPanel, Passenger).

Elle interroge ~/data/lecture/foot.duckdb, une copie que le pipeline de la nuit remplace d'un coup, si bien que le
chargement de 23h30 n'est jamais bloqué. Aucune modification n'est possible, à quatre niveaux :
  1. seules les requêtes SELECT / WITH / FROM / DESCRIBE / SHOW / SUMMARIZE / EXPLAIN sont acceptées (analyse DuckDB) ;
  2. la base est ouverte en read_only ;
  3. enable_external_access=false (pas de COPY vers un fichier, pas d'ATTACH, pas d'INSTALL, pas de lecture de fichiers)
     et lock_configuration=true (la requête ne peut pas changer ces réglages) ;
  4. la copie n'est pas la base de production : même en cas de faille, la vraie base n'est pas touchée.
Accès par mot de passe (haché dans ~/.config/sql_lecture/config.json), délai maximum et nombre de lignes limités.
Interface : onglets de requêtes gardés dans le navigateur (localStorage), éditeur CodeMirror (numéros de ligne,
autocomplétion des tables et colonnes), exécution sans recharger la page (/executer, JSON).
"""
import csv
import functools
import hmac
import io
import json
import os
import sqlite3
import threading
import time

import duckdb
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

CONFIG = json.load(open(os.path.expanduser('~/.config/sql_lecture/config.json')))
BASE = os.path.expanduser(CONFIG.get('base', '~/data/lecture/foot.duckdb'))
RUNS = os.path.expanduser('~/data/pipelines/runs.sqlite')
MAX_LIGNES = 5000          # affichées ; l'export CSV va jusqu'à MAX_CSV
MAX_CSV = 200_000
DELAI = 60                 # secondes
TYPES_PERMIS = {'SELECT', 'EXPLAIN'}

app = Flask(__name__)
app.secret_key = CONFIG['cle_session']
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  PERMANENT_SESSION_LIFETIME=7 * 24 * 3600)


def connexion():
    return duckdb.connect(BASE, read_only=True, config={
        'enable_external_access': False, 'autoinstall_known_extensions': False, 'autoload_known_extensions': False,
        'memory_limit': '1GB', 'threads': 2, 'lock_configuration': True})


def verifier(sql):
    """Lève ValueError si la requête n'est pas une simple lecture."""
    try:
        instructions = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise ValueError(str(e)) from None
    if not instructions:
        raise ValueError('requête vide')
    if len(instructions) > 1:
        raise ValueError('une seule requête à la fois')
    if instructions[0].type.name not in TYPES_PERMIS:
        raise ValueError(f'lecture seule : {instructions[0].type.name} interdit (SELECT, WITH, DESCRIBE, SHOW, '
                         'SUMMARIZE, EXPLAIN uniquement)')


def executer(sql, limite):
    verifier(sql)
    con = connexion()
    minuteur = threading.Timer(DELAI, con.interrupt)
    minuteur.start()
    t0 = time.time()
    try:
        cur = con.execute(sql)
        colonnes = [d[0] for d in cur.description or []]
        lignes = cur.fetchmany(limite + 1)
    except duckdb.InterruptException:
        raise ValueError(f'requête arrêtée après {DELAI} s') from None
    except duckdb.Error as e:
        raise ValueError(str(e)) from None
    finally:
        minuteur.cancel()
        con.close()
    return colonnes, lignes[:limite], len(lignes) > limite, time.time() - t0


def connecte(vue):
    @functools.wraps(vue)
    def f(*a, **k):
        if not session.get('ok'):
            return redirect(url_for('connexion_page', suite=request.path))
        return vue(*a, **k)
    return f


@app.route('/connexion', methods=['GET', 'POST'])
def connexion_page():
    erreur = None
    if request.method == 'POST':
        if check_password_hash(CONFIG['mot_de_passe'], request.form.get('mot_de_passe', '')):
            session.clear()
            session.permanent, session['ok'] = True, True
            suite = request.args.get('suite', '')
            return redirect(suite if suite.startswith('/') and not suite.startswith('//') else url_for('index'))
        time.sleep(2)   # freine les essais de mots de passe
        erreur = 'mot de passe incorrect'
    return render_template('connexion.html', erreur=erreur)


@app.route('/deconnexion')
def deconnexion():
    session.clear()
    return redirect(url_for('connexion_page'))


@functools.lru_cache(maxsize=4)
def schema(cle_fichier):
    con = connexion()
    try:
        lignes = con.execute("""
            select t.table_schema, t.table_name, t.table_type, c.column_name, c.data_type
            from information_schema.tables t
            join information_schema.columns c using (table_catalog, table_schema, table_name)
            where t.table_schema not in ('information_schema', 'pg_catalog')
            order by 1, 2, c.ordinal_position""").fetchall()
    finally:
        con.close()
    arbre = {}
    for sch, table, typ, col, dtype in lignes:
        arbre.setdefault(sch, {}).setdefault(table, {'type': 'vue' if typ == 'VIEW' else 'table', 'colonnes': []})
        arbre[sch][table]['colonnes'].append((col, dtype))
    return arbre


def maj_copie():
    st = os.stat(BASE)
    return st, time.strftime('%d/%m/%Y %H:%M', time.localtime(st.st_mtime))


@app.route('/', methods=['GET', 'POST'])
@connecte
def index():
    st, maj = maj_copie()
    arbre = schema((st.st_mtime, st.st_size))
    tables = {f'{sch}.{t}': [c for c, _ in d['colonnes']] for sch, ts in arbre.items() for t, d in ts.items()}
    return render_template('index.html', sql=request.values.get('sql', '').strip(), arbre=arbre, tables=tables,
                           maj=maj, max_lignes=MAX_LIGNES, delai=DELAI, jeton=jeton())


def valeur(v):
    """Une valeur DuckDB en JSON : nombres, texte, booléens et null tels quels ; le reste (dates, décimaux, listes...)
    en texte, comme l'affichait la page."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v if not (isinstance(v, float) and v != v) else None
    return str(v)


@app.route('/executer', methods=['POST'])
@connecte
def executer_json():
    """Exécute la requête d'un onglet ; réponse JSON (colonnes, lignes, tronque, duree) ou (erreur)."""
    donnees = request.get_json(silent=True) or {}
    if not hmac.compare_digest(request.headers.get('X-Jeton', ''), jeton()):
        return jsonify(erreur='session expirée, rechargez la page'), 403
    try:
        colonnes, lignes, tronque, duree = executer(str(donnees.get('sql', '')), MAX_LIGNES)
    except ValueError as e:
        return jsonify(erreur=str(e))
    return jsonify(colonnes=colonnes, lignes=[[valeur(v) for v in l] for l in lignes], tronque=tronque,
                   duree=round(duree, 3))


@app.route('/csv', methods=['POST'])
@connecte
def export_csv():
    if not hmac.compare_digest(request.form.get('jeton', ''), jeton()):
        return Response('session expirée', status=403)
    try:
        colonnes, lignes, tronque, _ = executer(request.form.get('sql', ''), MAX_CSV)
    except ValueError as e:
        return Response(str(e), status=400, mimetype='text/plain')
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(colonnes)
    w.writerows(lignes)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=requete.csv'})


@app.route('/pipelines')
@connecte
def pipelines():
    runs, taches = [], {}
    if os.path.exists(RUNS):
        con = sqlite3.connect(f'file:{RUNS}?mode=ro', uri=True)
        runs = con.execute('select id, pipeline, debut, fin, statut from runs order by id desc limit 30').fetchall()
        for r in con.execute('select run_id, tache, statut, tentatives, debut, fin from taches where run_id >= ? order by rowid',
                             (runs[-1][0] if runs else 0,)):
            taches.setdefault(r[0], []).append(r[1:])
        con.close()
    return render_template('pipelines.html', runs=runs, taches=taches, maj=maj_copie()[1])


def jeton():
    """Jeton anti-CSRF lié à la session."""
    if 'jeton' not in session:
        session['jeton'] = os.urandom(16).hex()
    return session['jeton']


@app.after_request
def entetes(r):
    r.headers['X-Frame-Options'] = 'DENY'
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['Referrer-Policy'] = 'same-origin'
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return r
