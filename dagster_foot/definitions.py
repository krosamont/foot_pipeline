"""The football database as Dagster assets: what is loaded, what dbt builds from it, what is published.

    z_raw          one asset per raw table (the dbt sources of foot_db): the match tables, all filled at once by
                   load_matches (tools/load_raw.py; nothing new: no dbt run), the Transfermarkt tables
                   (check_transfermarkt: profiles loaded from the Mac since the last read copy), and the old
                   project's tables (external: loaded once, never again)
    foot_db        one asset per dbt model and seed of foot_db (dagster-dbt), each test an asset check: the lineage
                   goes from each raw table to the marts
    publication    read_copy            the copy of the base read by the SQL page (data-workers.com/sql)
    maintenance    backup               EXPORT DATABASE to Parquet, the 7 latest kept (pipeline nuit)
                   match_check          every match played is everywhere (tools/check_matches.py, e-mail if not)
                   source_freshness     dbt source freshness

Jobs: journee (sources, dbt only when something is new, read copy), nuit (the same, dbt always), controles,
sauvegarde. o2switch allows no daemon: no dagster-daemon, the cron runs `dagster_foot/dagster_run.sh <job>`, which
takes the lock of the base, runs the job with the Dagster CLI and e-mails a failure. The schedules below are the
cron times, for the UI (dagster-webserver, started on demand behind an SSH tunnel). Run history: $DAGSTER_HOME
(SQLite). Paths: $FOOT_3D (~/data/foot_3d), $FOOT_DB_PROJECT (~/data/foot_db), $FOOT_DB (~/data/foot.duckdb).
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from dagster import (AssetExecutionContext, AssetKey, AssetSpec, Definitions, Failure, MaterializeResult,
                     RetryPolicy, ScheduleDefinition, asset, define_asset_job, in_process_executor, multi_asset)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

HOME = Path.home()
FOOT_3D = Path(os.environ.get('FOOT_3D', HOME / 'data' / 'foot_3d'))
FOOT_DB_PROJECT = Path(os.environ.get('FOOT_DB_PROJECT', HOME / 'data' / 'foot_db'))
BASE = Path(os.environ.get('FOOT_DB', HOME / 'data' / 'foot.duckdb'))
LECTURE = Path(os.environ.get('FOOT_LECTURE', HOME / 'data' / 'lecture' / 'foot.duckdb'))
BACKUPS = Path(os.environ.get('FOOT_BACKUPS', HOME / 'data' / 'sauvegardes'))
DUCKDB = os.environ.get('DUCKDB_CLI', str(HOME / 'bin' / 'duckdb'))
PY = str(FOOT_3D / '.venv' / 'bin' / 'python')
NOTHING_NEW = 3   # exit code of tools/load_raw.py when no match is new


def sh(context, command, cwd, ok=(0,)):
    """Runs a shell command, its output in the Dagster log; its exit code (one of `ok`, else a Failure)."""
    context.log.info(f'$ {command}')
    p = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, executable='/bin/bash')
    for line in (p.stdout + p.stderr).strip().splitlines()[-60:]:
        context.log.info(line)
    if p.returncode not in ok:
        raise Failure(f'exit code {p.returncode}: {command}', metadata={'output': (p.stdout + p.stderr)[-4000:]})
    return p.returncode


# ---------------------------------------------------------------- z_raw (the dbt sources)
foot_db = DbtProject(project_dir=FOOT_DB_PROJECT, profiles_dir=FOOT_DB_PROJECT)
SOURCES = [n for n in json.loads(Path(foot_db.manifest_path).read_text())['sources'].values() if n['schema'] == 'z_raw']
RAW = sorted(n['name'] for n in SOURCES)
# dbt names a source by its short prefix (ws_event, tm_player); identifier: its table in the database (whoscored_event)
TABLE = {n['name']: n.get('identifier') or n['name'] for n in SOURCES}
LEGACY = [t for t in RAW if t.endswith('_legacy')]
TRANSFERMARKT = [t for t in RAW if t.startswith(('transfermarkt_', 'tm_')) and t not in LEGACY]
MATCH_TABLES = [t for t in RAW if t not in LEGACY + TRANSFERMARKT]
raw_key = lambda table: AssetKey(['z_raw', table])


@multi_asset(specs=[AssetSpec(raw_key(t), group_name='z_raw') for t in MATCH_TABLES], name='load_matches',
             retry_policy=RetryPolicy(max_retries=2, delay=300),
             description='New matches (JSON of data/matches/ as CSV) -> the z_raw match tables, values unchanged '
                         '(tools/load_raw.py), under the lock of tools/run_missing.py: no match read while written.')
def load_matches(context: AssetExecutionContext):
    code = sh(context, f'flock -w 3600 data/matches/.run.lock {PY} -u tools/load_raw.py', FOOT_3D, ok=(0, NOTHING_NEW))
    for t in MATCH_TABLES:
        yield MaterializeResult(asset_key=raw_key(t), metadata={'new_data': code == 0})


@multi_asset(specs=[AssetSpec(raw_key(t), group_name='z_raw') for t in TRANSFERMARKT], name='check_transfermarkt',
             description='The Transfermarkt tables, loaded from the Mac (tm.run load): profiles loaded since the last '
                         'read copy?')
def check_transfermarkt(context: AssetExecutionContext):
    since = int(LECTURE.stat().st_mtime) if LECTURE.exists() else 0
    out = subprocess.run([DUCKDB, '-readonly', '-noheader', '-list', str(BASE), '-c',
                          f'select count(*) from z_raw.{TABLE[TRANSFERMARKT_PLAYER]} where epoch(_loaded_at) > {since}'],
                         capture_output=True, text=True, check=True).stdout.strip()
    rows = int(out or 0)
    context.log.info(f'{rows} Transfermarkt profiles loaded since the last read copy')
    for t in TRANSFERMARKT:
        yield MaterializeResult(asset_key=raw_key(t), metadata={'new_data': rows > 0, 'new_profiles': rows})


TRANSFERMARKT_PLAYER = next(t for t in TRANSFERMARKT if t in ('transfermarkt_player', 'tm_player'))
legacy_tables = [AssetSpec(raw_key(t), group_name='z_raw',
                           description="The old project's table (seasons 2020-2021 to 2024-2025), loaded once by "
                                       'tools/load_legacy.py.') for t in LEGACY]


# ---------------------------------------------------------------- foot_db (dbt)


class FootTranslator(DagsterDbtTranslator):
    """Every dbt node as <schema>/<name> (z_raw/ws_event, b_intermediate/int_match...), grouped by layer."""

    def get_asset_key(self, props):
        if props['resource_type'] == 'source':
            return raw_key(props['name'])
        return AssetKey([props['schema'], props['name']]) if props.get('schema') else super().get_asset_key(props)

    def get_group_name(self, props):
        return props.get('schema') or 'foot_db'


def new_in_this_run(context, key):
    """Did `key` say new_data = true in this run? (None when it was not materialized in this run.)"""
    event = context.instance.get_latest_materialization_event(key)
    if event is None or event.run_id != context.run_id:
        return None
    value = event.asset_materialization.metadata.get('new_data')
    return bool(value.value) if value is not None else None


@dbt_assets(manifest=foot_db.manifest_path, dagster_dbt_translator=FootTranslator(),
            retry_policy=RetryPolicy(max_retries=1, delay=60))
def foot_db_models(context: AssetExecutionContext, dbt: DbtCliResource):
    """dbt build of foot_db: a_staging views, b_intermediate and c_marts tables (per-match models incremental: only
    the matches loaded since the previous run), every test. In the job journee, skipped when neither source has
    anything new (the read copy is then skipped too)."""
    if context.run.job_name == 'journee':
        news = [new_in_this_run(context, raw_key(t)) for t in (MATCH_TABLES[0], TRANSFERMARKT_PLAYER)]
        if not any(news):
            context.log.info('nothing new in the sources: no dbt run')
            return
    yield from dbt.cli(['build'], context=context).stream()


# ---------------------------------------------------------------- publication and maintenance
@asset(group_name='publication', deps=[foot_db_models],
       description='Copy of the base for the read-only SQL page, replaced at once (mv): the page is never cut.')
def read_copy(context: AssetExecutionContext) -> MaterializeResult:
    LECTURE.parent.mkdir(parents=True, exist_ok=True)
    sh(context, f'{DUCKDB} {BASE} -c "CHECKPOINT" && cp {BASE} {LECTURE}.tmp && mv -f {LECTURE}.tmp {LECTURE}', HOME)
    return MaterializeResult(metadata={'size_mb': round(LECTURE.stat().st_size / 1e6)})


@asset(group_name='maintenance', retry_policy=RetryPolicy(max_retries=1, delay=300),
       description='EXPORT DATABASE to Parquet in ~/data/sauvegardes/foot-<date> (restore: IMPORT DATABASE), the 7 '
                   'latest kept; the Mac copies the raw data of the latest every morning (tools/sauvegarde_mac.sh).')
def backup(context: AssetExecutionContext) -> MaterializeResult:
    d = BACKUPS / f"foot-{subprocess.run(['date', '+%Y%m%d'], capture_output=True, text=True).stdout.strip()}"
    sh(context, f'rm -rf "{d}" && mkdir -p {BACKUPS} && {DUCKDB} -readonly {BASE} -c "SET memory_limit=\'1GB\'; '
                f'SET threads=1; SET preserve_insertion_order=false; SET temp_directory=\'{BACKUPS}/.tmp\'; '
                f'EXPORT DATABASE \'{d}\' (FORMAT parquet, COMPRESSION zstd)" && du -sh "{d}" && '
                f'ls -1d {BACKUPS}/foot-* | head -n -7 | xargs -r rm -rf', HOME)
    return MaterializeResult(metadata={'folder': str(d)})


@asset(group_name='maintenance', deps=[foot_db_models],
       description='Every match played is downloaded, published, in z_raw and in c_marts (tools/check_matches.py: '
                   'an e-mail when one is missing).')
def match_check(context: AssetExecutionContext):
    if dt.date.today().isoweekday() not in (7, 1, 2, 3, 6):   # the days after match days
        context.log.info('no match check today (only Saturday to Wednesday)')
        return
    sh(context, f'{PY} tools/check_matches.py', FOOT_3D)


@asset(group_name='maintenance', deps=[foot_db_models],
       description='dbt source freshness: a warning after 4 days without a load, an error after 15.')
def source_freshness(context: AssetExecutionContext, dbt: DbtCliResource):
    dbt.cli(['source', 'freshness'], context=context, manifest=foot_db.manifest_path).wait()


# ---------------------------------------------------------------- jobs and schedules
main_assets = [load_matches, check_transfermarkt, foot_db_models, read_copy]
journee = define_asset_job('journee', selection=main_assets, executor_def=in_process_executor,
                           description='new matches and profiles into the base, dbt when something is new, read copy')
nuit = define_asset_job('nuit', selection=main_assets, executor_def=in_process_executor,
                        description='sources, dbt (always), read copy; foot_db pulled from GitHub first (dagster_run.sh)')
controles = define_asset_job('controles', selection=[match_check, source_freshness], executor_def=in_process_executor,
                             description='match check and source freshness (failures reported, nothing blocked)')
sauvegarde = define_asset_job('sauvegarde', selection=[backup], executor_def=in_process_executor,
                              description='Parquet export of the whole base, even when the load failed')

defs = Definitions(
    assets=[load_matches, check_transfermarkt, *legacy_tables, foot_db_models, read_copy, backup, match_check,
            source_freshness],
    jobs=[journee, nuit, controles, sauvegarde],
    schedules=[ScheduleDefinition(job=journee, cron_schedule='45 9-21/2 * * *', execution_timezone='Europe/Paris'),
               ScheduleDefinition(job=nuit, cron_schedule='30 23 * * *', execution_timezone='Europe/Paris')],
    resources={'dbt': DbtCliResource(project_dir=foot_db, profiles_dir=str(FOOT_DB_PROJECT),
                                     dbt_executable=str(Path(sys.executable).parent / 'dbt'))},
)
