"""One-off load (rerun it only if the old files change).
Old project's Parquet files (~/data/foot/whoscored/combined_data, seasons 2020-2021 to 2024-2025) -> MotherDuck
md:foot, schema raw_legacy, as they are (+ data_convention 'ancienne', _source_file, _loaded_at)."""
import os, time, duckdb
os.environ.setdefault('motherduck_token', open(os.path.expanduser('~/.motherduck_token')).read().strip())
SRC = os.path.expanduser('~/data/foot/whoscored/combined_data')
c = duckdb.connect('md:foot')
c.execute("SET threads = 4; SET memory_limit = '4GB'")
c.execute('create schema if not exists raw_legacy')
for table, f in [('match', 'match_df'), ('player', 'player_df'), ('metric', 'metrics_df'), ('event', 'event_df')]:
    p = f'{SRC}/{f}.parquet'
    t0 = time.time()
    c.execute(f"""create or replace table raw_legacy."{table}" as
                  select *, 'ancienne' as data_convention, ? as _source_file, now()::timestamp as _loaded_at
                  from read_parquet(?)""", [p, p])
    n = c.sql(f'select count(*) from raw_legacy."{table}"').fetchone()[0]
    src = duckdb.sql(f"select count(*) from '{p}'").fetchone()[0]
    assert n == src, (table, n, src)
    print(f'raw_legacy.{table}: {n} rows (= {f}.parquet), {time.time() - t0:.0f} s', flush=True)
print(c.sql("select * from pragma_database_size() where database_name = 'foot'").fetchall()[0][:2])
