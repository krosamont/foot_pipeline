"""Restore test of a backup copied by tools/sauvegarde_mac.sh: the schemas and raw tables of its schema.sql, then its
load.sql COPY statements (the paths of the server replaced by the backup folder), into a temporary DuckDB file; each
table must have as many rows as its Parquet file. Exit code 1 with the tables that differ.

    python tools/test_restauration.py ~/Documents/dataScience/sport/football/sauvegardes_foot/foot-20261109
"""
import os
import re
import sys
import tempfile

import duckdb

KEEP = ('z_raw.', 'z_technique.')


def statements(path):
    return [s.strip() for s in open(path).read().split(';\n') if s.strip().strip(';')]


def main(folder):
    folder = os.path.abspath(folder)
    with tempfile.TemporaryDirectory() as tmp:
        con = duckdb.connect(os.path.join(tmp, 'restore.duckdb'))
        con.execute("SET memory_limit = '2GB'")
        for s in statements(os.path.join(folder, 'schema.sql')):
            if s.startswith('CREATE SCHEMA') or (s.startswith('CREATE TABLE') and any(k in s.split('(')[0] for k in KEEP)):
                con.execute(s.rstrip(';'))
        bad, n = [], 0
        for s in statements(os.path.join(folder, 'load.sql')):
            m = re.match(r"COPY (\S+) FROM '([^']+)'", s)
            if not m or not m.group(1).startswith(KEEP):
                continue
            table, parquet = m.group(1), os.path.join(folder, os.path.basename(m.group(2)))
            con.execute(f"COPY {table} FROM '{parquet}' (FORMAT 'parquet')")
            rows = con.execute(f'select count(*) from {table}').fetchone()[0]
            expected = con.execute(f"select sum(num_rows) from parquet_file_metadata('{parquet}')").fetchone()[0]
            n += 1
            if rows != expected:
                bad.append(f'{table}: {rows} rows restored, {expected} in the file')
        con.close()
    if bad or n == 0:
        print('restore test FAILED:', *(bad or ['no table restored']), sep='\n  ')
        return 1
    print(f'restore test ok: {n} tables')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
