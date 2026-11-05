"""One-off load (rerun it only if the old files change).
Old project's Parquet files (~/data/foot/whoscored/combined_data, seasons 2020-2021 to 2024-2025) -> the football
database (~/data/foot.duckdb, $FOOT_DB), layer a_staging, tables stg_whoscored_<subject>_legacy, as they are
(+ data_convention 'ancienne', _source_file, _loaded_at)."""
import os, time, duckdb
SRC = os.path.expanduser('~/data/foot/whoscored/combined_data')
c = duckdb.connect(os.environ.get('FOOT_DB', os.path.expanduser('~/data/foot.duckdb')))
c.execute("SET threads = 2; SET memory_limit = '1GB'; SET preserve_insertion_order = false")
c.execute('create schema if not exists a_staging')
for table, f in [('stg_whoscored_match_legacy', 'match_df'), ('stg_whoscored_player_legacy', 'player_df'),
                 ('stg_whoscored_match_stat_legacy', 'metrics_df'), ('stg_whoscored_event_legacy', 'event_df')]:
    p = f'{SRC}/{f}.parquet'
    t0 = time.time()
    c.execute(f"""create or replace table a_staging."{table}" as
                  select *, 'ancienne' as data_convention, ? as _source_file, now()::timestamp as _loaded_at
                  from read_parquet(?)""", [p, p])
    n = c.sql(f'select count(*) from a_staging."{table}"').fetchone()[0]
    src = duckdb.sql(f"select count(*) from '{p}'").fetchone()[0]
    assert n == src, (table, n, src)
    print(f'a_staging.{table}: {n} rows (= {f}.parquet), {time.time() - t0:.0f} s', flush=True)
