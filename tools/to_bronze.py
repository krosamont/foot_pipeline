"""Sources of the football database (~/data/foot.duckdb, $FOOT_DB; schema raw): the files of data/matches/ as they are. The dbt project foot_db
(github.com/krosamont/foot_db, clone ~/data/foot_db) reads them in its bronze models, then builds silver and gold.

    python tools/to_bronze.py               (load the matches not loaded yet, or whose files changed; from 2025-2026)
    python tools/to_bronze.py --limit 3     (test)
    python tools/to_bronze.py --seasons 2026-2027

One table raw.<name> per kind of file, every value kept as text (as in the file; silver casts them), plus match_id (WhoScored id),
competition ('premier-league', ..., 'serie-a'), season ('2026-2027'), data_convention ('foot_3d'), _source_file and
_loaded_at:
  events            <match>_qualifiers_expanded.csv   (one row per WhoScored event; x, y in metres, 105 x 68)
  whoscored_players PlayerData.csv                    ('stats' kept as written)
  fotmob_players    <match>_players.csv
  match_info        <match>_match_info.csv            (one row per side)
  momentum          <match>_momentum.csv
  match_status      raw/whoscored.json + raw/fotmob.json: referee, attendance, scores, managers, FotMob status
  _loads            match id -> date of its files, written in the same transaction as the rows
A new column in the files is added to its table (text). The matches are read 50 at a time (the server limits the
number of open files) and each batch is one transaction: delete the rows of its matches, insert, record the load.
"""
import argparse
import glob
import json
import os
import sys
import time

import duckdb
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATCHES = os.path.join(ROOT, 'data', 'matches')
# the football database: one DuckDB file on the server (MotherDuck dropped on 2026-11-03: too expensive)
DATABASE = os.environ.get('FOOT_DB', os.path.expanduser('~/data/foot.duckdb'))
SCHEMA = 'raw'   # the dbt sources (models/bronze/_bronze.yml of foot_db)
FIRST_SEASON = '2025-2026'
COMPETITION = {'serie': 'serie-a'}   # folder slug -> name used in the tables (as in BigQuery)
CONVENTION = 'foot_3d'
BATCH = 50
FILES = {   # table -> file pattern in a match folder
    'events': '*_qualifiers_expanded.csv',
    'whoscored_players': 'PlayerData.csv',
    'fotmob_players': '*_players.csv',
    'match_info': '*_match_info.csv',
    'momentum': '*_momentum.csv',
}
TAGS = ['match_id', 'competition', 'season', 'data_convention', '_source_file', '_loaded_at']


def token():
    if not os.environ.get('motherduck_token'):
        path = os.path.expanduser('~/.motherduck_token')
        os.environ['motherduck_token'] = open(path).read().strip()


def tag_of(folder):
    comp_season = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    slug, season = comp_season.rsplit('_', 1)
    return int(os.path.basename(os.path.normpath(folder)).split('_', 1)[0]), COMPETITION.get(slug, slug), season


def stamp(folder):
    files = [p for pat in FILES.values() for p in glob.glob(os.path.join(folder, pat))]
    return int(max(os.path.getmtime(p) for p in files))


def status_row(folder):
    """The scalar fields of raw/whoscored.json (+ referee) and the FotMob status, as text."""
    mid, comp, season = tag_of(folder)
    row = {}
    p = os.path.join(folder, 'raw', 'whoscored.json')
    if os.path.exists(p):
        w = json.load(open(p, encoding='utf-8'))
        for k, v in w.items():
            if not isinstance(v, (dict, list)):
                row[f'ws_{k}'] = None if v is None else str(v)
        for k, v in (w.get('referee') or {}).items():
            row[f'ws_referee_{k}'] = None if v is None else str(v)
        for side in ('home', 'away'):
            s = w.get(side) or {}
            for k in ('teamId', 'name', 'managerName', 'averageAge', 'countryName'):
                if k in s:
                    row[f'ws_{side}_{k}'] = str(s[k])
    p = os.path.join(folder, 'raw', 'fotmob.json')
    if os.path.exists(p):
        st = (json.load(open(p, encoding='utf-8')).get('header') or {}).get('status') or {}
        for k in ('utcTime', 'started', 'finished', 'cancelled', 'scoreStr'):
            if k in st:
                row[f'fm_{k}'] = str(st[k])
        reason = st.get('reason') or {}
        row['fm_reason'] = reason.get('longKey')
    row.update(match_id=str(mid), competition=comp, season=season, data_convention=CONVENTION,
               _source_file=os.path.join(folder, 'raw'))
    return row


def ensure_columns(con, table, cols):
    """Table created when missing; columns it does not have yet added (text)."""
    have = [r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_catalog = ? and table_schema = ? and table_name = ?",
        [DATABASE, SCHEMA, table]).fetchall()]
    if not have:
        defs = ', '.join(f'"{c}" {"TIMESTAMP" if c == "_loaded_at" else "BIGINT" if c == "match_id" else "VARCHAR"}' for c in cols)
        con.execute(f'create table {SCHEMA}."{table}" ({defs})')
        return
    lower = {c.lower() for c in have}
    for c in cols:
        if c.lower() not in lower:
            con.execute(f'alter table {SCHEMA}."{table}" add column "{c}" VARCHAR')
            print(f'[bronze] {table}: new column {c}', flush=True)


def load_batch(con, folders):
    mids = []
    with_tags = []
    for f in folders:
        mid, comp, season = tag_of(f)
        mids.append(mid)
        with_tags.append((f, mid, comp, season))
    con.execute('begin transaction')
    try:
        for table, pattern in FILES.items():
            files = []
            for f, mid, comp, season in with_tags:
                found = sorted(glob.glob(os.path.join(f, pattern)))
                if found:
                    files.append((found[0], mid, comp, season))
            if not files:
                continue
            con.execute('create or replace temp table _tags (file VARCHAR, match_id BIGINT, competition VARCHAR, season VARCHAR)')
            con.executemany('insert into _tags values (?, ?, ?, ?)', [list(x) for x in files])
            paths = [x[0] for x in files]
            con.execute('create or replace temp table _new as select t.match_id, t.competition, t.season, ? as data_convention, '
                        'r.filename as _source_file, now()::timestamp as _loaded_at, r.* exclude (filename) '
                        'from read_csv(?, union_by_name = true, all_varchar = true, filename = true, header = true) r '
                        'join _tags t on t.file = r.filename', [CONVENTION, paths])
            cols = [r[0] for r in con.execute('describe _new').fetchall()]
            ensure_columns(con, table, cols)
            con.execute(f'delete from {SCHEMA}."{table}" where match_id in (select unnest(?::BIGINT[]))', [mids])
            con.execute(f'insert into {SCHEMA}."{table}" by name select * from _new')
        rows = pd.DataFrame([status_row(f) for f in folders])
        rows['_loaded_at'] = pd.Timestamp.now()
        con.register('_status', rows)
        con.execute('create or replace temp table _new as select * replace (match_id::BIGINT as match_id) from _status')
        ensure_columns(con, 'match_status', [r[0] for r in con.execute('describe _new').fetchall()])
        con.execute(f'delete from {SCHEMA}.match_status where match_id in (select unnest(?::BIGINT[]))', [mids])
        con.execute(f'insert into {SCHEMA}.match_status by name select * from _new')
        con.unregister('_status')
        con.execute(f'delete from {SCHEMA}._loads where match_id in (select unnest(?::BIGINT[]))', [mids])
        con.executemany(f'insert into {SCHEMA}._loads values (?, ?, now()::timestamp)', [[tag_of(f)[0], stamp(f)] for f in folders])
        con.execute('commit')
    except Exception:
        con.execute('rollback')
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int, default=None, help='only the first N matches to load (test)')
    ap.add_argument('--seasons', nargs='+', default=None, help=f'only these seasons (default: {FIRST_SEASON} and later)')
    ap.add_argument('--database', default=DATABASE, help='DuckDB file (default: $FOOT_DB or ~/data/foot.duckdb)')
    a = ap.parse_args(argv)
    globals()['DATABASE'] = a.database

    season_of = lambda d: os.path.basename(os.path.dirname(os.path.normpath(d))).rsplit('_', 1)[1]
    folders = sorted(d for d in glob.glob(os.path.join(MATCHES, '*_*-*', '*_*', ''))
                     if glob.glob(os.path.join(d, FILES['events'])) and os.path.exists(os.path.join(d, 'PlayerData.csv')))
    folders = [d for d in folders if (season_of(d) in a.seasons if a.seasons else season_of(d) >= FIRST_SEASON)]

    con = duckdb.connect(DATABASE)
    con.execute(f'create schema if not exists {SCHEMA}')
    con.execute(f'create table if not exists {SCHEMA}._loads (match_id BIGINT, files_mtime BIGINT, loaded_at TIMESTAMP)')
    con.execute("SET threads = 4; SET memory_limit = '4GB'")
    done = dict(con.execute(f'select match_id, files_mtime from {SCHEMA}._loads').fetchall())
    todo = [d for d in folders if done.get(tag_of(d)[0]) != stamp(d)][:a.limit]
    print(f'[bronze] {len(folders)} match folders, {len(todo)} to load into {DATABASE}', flush=True)
    t0 = time.time()
    for k in range(0, len(todo), BATCH):
        load_batch(con, todo[k:k + BATCH])
        print(f'[bronze] {min(k + BATCH, len(todo))}/{len(todo)} matches ({time.time() - t0:.0f} s)', flush=True)
    # exit code 0 = something loaded (dbt build worth running), 3 = nothing new
    return 0 if todo else 3


if __name__ == '__main__':
    sys.exit(main())
