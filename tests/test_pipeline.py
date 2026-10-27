"""Offline regression test of the whole pipeline (pmd/) on a frozen match.

Usage: python tests/test_pipeline.py
Runs fetch-free (raw WhoScored + FotMob data and both xT grids are in tests/fixtures) and compares every output file
with the SHA-256 recorded from the original notebook script. The CSV / JSON files must match exactly; the dashboard PNG
is compared too, but only reported (a different matplotlib / font version changes pixels, not the data).
"""
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, 'tests', 'fixtures')
MATCH = os.path.join(FIX, 'France_vs_England')


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    import matplotlib
    matplotlib.use('Agg')
    from pmd import events, export, dashboard

    fotmob = json.load(open(os.path.join(MATCH, 'fotmob.json')))
    whoscored = json.load(open(os.path.join(MATCH, 'whoscored.json')))
    expected = json.load(open(os.path.join(MATCH, 'expected_sha256.json')))
    out = tempfile.mkdtemp(prefix='pmd_test_')
    ns = events.build_events(whoscored, fotmob, out, xt_grid_source=os.path.join(FIX, 'xT_Grid_mckay.csv'))
    exp_df, mom_df, info_df = export.build_exports(ns['df'], fotmob, ns['hteamName'], ns['ateamName'],
                                                   xt_grid_source=os.path.join(FIX, 'xT_Grid_akapich.csv'))
    export.write_exports(out, ns['file_header'], exp_df, mom_df, info_df, fotmob)
    dashboard.render(ns, out)

    failed = 0
    for name, digest in expected.items():
        got = sha(os.path.join(out, name))
        same = got == digest
        strict = not name.endswith('.png')
        if strict and not same:
            failed += 1
        print(f"{'PASS' if same else ('FAIL' if strict else 'INFO')}  {name}" + ('' if same else '  (differs from the reference)'))
    print(f'\noutputs in {out}')
    print('all exports identical to the reference' if not failed else f'{failed} export(s) differ')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
