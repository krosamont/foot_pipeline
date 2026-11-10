"""Raw data of the matches of data/matches/ -> schema z_raw of the football database (~/data/foot.duckdb, $FOOT_DB),
values unchanged. The dbt project foot_db (github.com/krosamont/foot_db, clone ~/data/foot_db) reads them as sources
(one view stg_<table> each in a_staging) and builds b_intermediate and c_marts.

    python tools/load_raw.py                (load the matches not loaded yet, or whose files changed; from 2025-2026)
    python tools/load_raw.py --limit 3      (test)
    python tools/load_raw.py --seasons 2026-2027
    python tools/load_raw.py --rewrite-csv  (write the CSV files again from the JSON first, e.g. after a change of
                                             pmd/brut_csv.py, then load every match again)
    python tools/load_raw.py --legacy-fotmob   (the FotMob JSON of the old project's matches, data/legacy_fotmob/,
                                             tools/oneoff/legacy_fotmob.py: their xG, line-ups, stats, score)

A match folder has the JSON as downloaded (raw/whoscored.json, raw/fotmob.json) and the same data as flat CSV files
(raw/csv/<table>.csv, pmd/brut_csv.py: one file per list of the JSON, no computation), written at download; a match
that has none yet gets them here. Each CSV file -> table z_raw.<table> (whoscored_event, whoscored_event_qualifier,
fotmob_shot...), every value as text, plus match_id (WhoScored id), competition ('premier-league', ..., 'serie-a'),
season ('2026-2027'), _source_file and _loaded_at (the same time for every table of a batch).
z_technique.pipeline_load: match id -> date of its CSV files, written in the same transaction as the rows (the
loader's bookkeeping: which matches are new or changed; read by no model).
A match WhoScored has no events for (matchCentreData null on its page), listed in tools/fotmob_only_matches.csv, is
loaded from its raw/fotmob.json alone (foot_db: int_match data_convention 'fotmob', its FotMob shots as events).
A new column in the files is added to its table (text). The matches are read 50 at a time (the server limits the
number of open files) and each batch is one transaction: delete the rows of its matches in every match table, insert,
record the load.
"""
import argparse
import csv
import glob
import os
import sys
import time

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pmd import brut_csv  # noqa: E402

MATCHES = os.path.join(ROOT, 'data', 'matches')
# the football database: one DuckDB file on the server (MotherDuck dropped on 2026-11-03: too expensive)
DATABASE = os.environ.get('FOOT_DB', os.path.expanduser('~/data/foot.duckdb'))
SCHEMA = 'z_raw'   # raw data, the dbt sources (models/a_staging/_z_raw.yml of foot_db)
LOADS = 'z_technique.pipeline_load'   # technical schema: the loader's bookkeeping
FIRST_SEASON = '2025-2026'   # before: the old project's seasons (tools/load_legacy.py)
COMPETITION = {'serie': 'serie-a'}   # folder slug -> name used in the tables
BATCH = 50
FOTMOB_ONLY = os.path.join(ROOT, 'tools', 'fotmob_only_matches.csv')   # WhoScored id -> loaded from FotMob alone


def fotmob_only_ids():
    if not os.path.exists(FOTMOB_ONLY):
        return set()
    with open(FOTMOB_ONLY, newline='') as f:
        return {int(r['whoscored_match_id']) for r in csv.DictReader(f)}
PREFIXES = ('whoscored_', 'fotmob_')   # the match tables (not the _legacy ones)


def tag_of(folder):
    comp_season = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    slug, season = comp_season.rsplit('_', 1)
    return int(os.path.basename(os.path.normpath(folder)).split('_', 1)[0]), COMPETITION.get(slug, slug), season


def raw_dir(folder):
    """Where the JSON of a match are: <folder>/raw/ (data/matches/), or the folder itself (data/legacy_fotmob/)."""
    return os.path.join(folder, 'raw') if os.path.isdir(os.path.join(folder, 'raw')) else folder


def csv_dir(folder):
    return os.path.join(raw_dir(folder), 'csv')


def stamp(folder):
    return int(max(os.path.getmtime(p) for p in glob.glob(os.path.join(csv_dir(folder), '*.csv'))))


def ensure_columns(con, table, cols):
    """Table created when missing; columns it does not have yet added (text)."""
    have = [r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_catalog = current_database() "
        "and table_schema = ? and table_name = ?", [SCHEMA, table]).fetchall()]
    if not have:
        defs = ', '.join(f'"{c}" {"TIMESTAMP" if c == "_loaded_at" else "BIGINT" if c == "match_id" else "VARCHAR"}'
                         for c in cols)
        con.execute(f'create table {SCHEMA}."{table}" ({defs})')
        return
    lower = {c.lower() for c in have}
    for c in cols:
        if c.lower() not in lower:
            con.execute(f'alter table {SCHEMA}."{table}" add column "{c}" VARCHAR')
            print(f'[z_raw] {table}: new column {c}', flush=True)


def match_tables(con):
    return [r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_catalog = current_database() "
        "and table_schema = ?", [SCHEMA]).fetchall()
        if r[0].startswith(PREFIXES) and not r[0].endswith('_legacy')]


def load_batch(con, folders):
    tagged = [(f, *tag_of(f)) for f in folders]
    mids = [t[1] for t in tagged]
    tables = sorted({os.path.basename(p)[:-4] for f in folders for p in glob.glob(os.path.join(csv_dir(f), '*.csv'))})
    con.execute('begin transaction')
    try:
        loaded_at = con.execute('select now()::timestamp').fetchone()[0]
        for table in match_tables(con):   # a match reloaded loses its old rows everywhere (a list may now be empty)
            con.execute(f'delete from {SCHEMA}."{table}" where match_id in (select unnest(?::BIGINT[]))', [mids])
        for table in tables:
            files = [(os.path.join(csv_dir(f), f'{table}.csv'), mid, comp, season) for f, mid, comp, season in tagged
                     if os.path.exists(os.path.join(csv_dir(f), f'{table}.csv'))]
            con.execute('create or replace temp table _tags (file VARCHAR, match_id BIGINT, competition VARCHAR, '
                        'season VARCHAR)')
            con.executemany('insert into _tags values (?, ?, ?, ?)', [list(x) for x in files])
            con.execute('create or replace temp table _new as select t.match_id, t.competition, t.season, '
                        'r.* exclude (filename), r.filename as _source_file, ?::timestamp as _loaded_at '
                        'from read_csv(?, union_by_name = true, all_varchar = true, filename = true, header = true) r '
                        'join _tags t on t.file = r.filename', [loaded_at, [x[0] for x in files]])
            ensure_columns(con, table, [r[0] for r in con.execute('describe _new').fetchall()])
            con.execute(f'insert into {SCHEMA}."{table}" by name select * from _new')
        con.execute(f'delete from {LOADS} where match_id in (select unnest(?::BIGINT[]))', [mids])
        con.executemany(f'insert into {LOADS} values (?, ?, ?)', [[mid, stamp(f), loaded_at] for f, mid, *_ in tagged])
        con.execute('commit')
    except Exception:
        con.execute('rollback')
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int, default=None, help='only the first N matches to load (test)')
    ap.add_argument('--seasons', nargs='+', default=None, help=f'only these seasons (default: {FIRST_SEASON} and later)')
    ap.add_argument('--database', default=DATABASE, help='DuckDB file (default: $FOOT_DB or ~/data/foot.duckdb)')
    ap.add_argument('--rewrite-csv', action='store_true', help='write the CSV files again from the JSON first')
    ap.add_argument('--legacy-fotmob', action='store_true',
                    help="the old project's FotMob JSON (data/legacy_fotmob/<competition>_<season>/<WhoScored id>/)")
    a = ap.parse_args(argv)

    season_of = lambda d: os.path.basename(os.path.dirname(os.path.normpath(d))).rsplit('_', 1)[1]
    fotmob_only = fotmob_only_ids()
    folders = sorted(d for d in glob.glob(os.path.join(MATCHES, '*_*-*', '*_*', ''))
                     if os.path.exists(os.path.join(d, 'raw', 'fotmob.json'))
                     and (os.path.exists(os.path.join(d, 'raw', 'whoscored.json')) or tag_of(d)[0] in fotmob_only))
    folders = [d for d in folders if (season_of(d) in a.seasons if a.seasons else season_of(d) >= FIRST_SEASON)]
    if a.legacy_fotmob:
        folders = sorted(d for d in glob.glob(os.path.join(ROOT, 'data', 'legacy_fotmob', '*_*-*', '*', ''))
                         if os.path.exists(os.path.join(d, 'fotmob.json')))
    written, failed = 0, []
    for d in folders:
        if a.rewrite_csv or not glob.glob(os.path.join(csv_dir(d), '*.csv')):
            try:
                brut_csv.convert(raw_dir(d))
                written += 1
            except Exception as e:   # noqa: BLE001  (one bad file must not stop the others; said in the log)
                failed.append(d)
                print(f'[z_raw] CSV files not written for {d}: {e!r}', flush=True)
    if written:
        print(f'[z_raw] CSV files written for {written} matches', flush=True)
    folders = [d for d in folders if glob.glob(os.path.join(csv_dir(d), '*.csv'))]

    con = duckdb.connect(a.database)
    con.execute(f'create schema if not exists {SCHEMA}')
    con.execute('create schema if not exists z_technique')
    con.execute(f'create table if not exists {LOADS} (match_id BIGINT, files_mtime BIGINT, loaded_at TIMESTAMP)')
    con.execute("SET threads = 2; SET memory_limit = '1GB'; SET preserve_insertion_order = false")
    done = dict(con.execute(f'select match_id, files_mtime from {LOADS}').fetchall())
    todo = [d for d in folders if done.get(tag_of(d)[0]) != stamp(d)][:a.limit]
    print(f'[z_raw] {len(folders)} match folders, {len(todo)} to load into {a.database}', flush=True)
    t0 = time.time()
    for k in range(0, len(todo), BATCH):
        load_batch(con, todo[k:k + BATCH])
        print(f'[z_raw] {min(k + BATCH, len(todo))}/{len(todo)} matches ({time.time() - t0:.0f} s)', flush=True)
    # exit code 0 = something loaded (dbt build worth running), 3 = nothing new
    if failed:
        print(f'[z_raw] {len(failed)} matches without CSV files (see above)', flush=True)
    return 0 if todo else 3


if __name__ == '__main__':
    sys.exit(main())
