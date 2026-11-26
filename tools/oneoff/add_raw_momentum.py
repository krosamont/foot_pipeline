"""Add the unsmoothed momentum (`momentum.raw`, see tools/build_data.py) to 3D data files built before it existed,
without rebuilding them: the rest of each file is kept as it is.

    python tools/oneoff/add_raw_momentum.py fabric/data [~/data-workers.com/projet/foot_3d/fabric/data] [--dry-run]

For each match of data/matches/ that has a <match>_momentum.csv, the points already in `momentum.csv` (smoothed,
scaled to +-100) are found back in the CSV's rows, in order, by their value; the raw momentum of those same rows,
scaled to its own peak, becomes `momentum.raw`. A file whose points cannot all be found is left unchanged (the
momentum bar then draws the smoothed series).
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from pmd.slug import match_slug  # noqa: E402

PREFIX = 'window.MATCH = '


def raw_series(stored, mdf):
    """The raw value of each stored smoothed point, or None when the points are not found in order."""
    peak = float(mdf['smoothed_momentum'].abs().max()) or 1.0
    peak_raw = float(mdf['momentum'].abs().max()) or 1.0
    smooth = [round(100 * float(v) / peak, 1) for v in mdf['smoothed_momentum']]
    raw = [round(100 * float(v) / peak_raw, 1) for v in mdf['momentum']]
    out, r = [], 0
    for cm, v in stored:
        while r < len(smooth) and abs(smooth[r] - v) > 0.051:
            r += 1
        if r == len(smooth):
            return None
        out.append([cm, raw[r]])
        r += 1
    return out


def main():
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    dry = '--dry-run' in sys.argv
    dirs = [os.path.expanduser(d) for d in args] or [os.path.join(ROOT, 'fabric', 'data')]
    moms = {}
    for csv in glob.glob(os.path.join(ROOT, 'data', 'matches', '*', '*', '*_qualifiers_expanded.csv')):
        mcsv = csv.replace('_qualifiers_expanded.csv', '_momentum.csv')
        if os.path.exists(mcsv):
            moms[match_slug(csv)] = mcsv
    for d in dirs:
        done = kept = missing = failed = 0
        for path in sorted(glob.glob(os.path.join(d, '*.js'))):
            slug = os.path.basename(path)[:-3]
            text = open(path, encoding='utf-8').read()
            if not text.startswith(PREFIX):
                continue
            data = json.loads(text[len(PREFIX):].rstrip().rstrip(';'))
            mom = data.get('momentum') or {}
            if mom.get('raw') or not mom.get('csv'):
                kept += 1
                continue
            if slug not in moms:
                missing += 1
                continue
            raw = raw_series(mom['csv'], pd.read_csv(moms[slug]))
            if raw is None:
                failed += 1
                print(f'[skip] {slug}: smoothed points not found in {moms[slug]}')
                continue
            data['momentum'] = {'csv': mom['csv'], 'raw': raw, **{k: v for k, v in mom.items() if k not in ('csv', 'raw')}}
            if not dry:
                tmp = path + '.tmp'
                open(tmp, 'w', encoding='utf-8').write(PREFIX + json.dumps(data, ensure_ascii=False) + ';\n')
                os.replace(tmp, path)
            done += 1
        print(f'{d}: {done} files {"to update" if dry else "updated"}, {kept} already done / no momentum, '
              f'{missing} without momentum CSV, {failed} not matched')


if __name__ == '__main__':
    main()
