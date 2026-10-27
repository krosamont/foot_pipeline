"""Checks on the event CSV exported by postmatchdashboard_whoscored_v2.py.

Usage: python tests/test_export.py [path/to/<match>_qualifiers_expanded.csv]
"""
import ast
import os
import sys

import numpy as np
import pandas as pd

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'France_vs_England', 'France_vs_England_qualifiers_expanded.csv')
ZONE_TAGS = ['start', 'end', 'passEnd']
PHASES = {'Build', 'Progress', 'Penetrate', 'Finish'}
CHANNELS = {'Wide Left', 'Half Space Left', 'Central', 'Half Space Right', 'Wide Right'}

df = pd.read_csv(PATH, index_col=0)
failures = []


def check(name, ok):
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


# 1. qualifiers expanded into columns
names = set()
for q in df['qualifiers'].dropna():
    for item in ast.literal_eval(q):
        names.add(item['type']['displayName'])
check('original qualifiers column kept', 'qualifiers' in df.columns)
check('one column per qualifier', all(n in df.columns or f'q_{n}' in df.columns for n in names))
row = df[df['qualifiers'].str.contains("'Longball'", na=False)].iloc[0]
check('flag qualifier = True (Longball)', bool(row['Longball']) is True)

# 2. PassEndX / PassEndY in metres and equal to endX / endY on passes
check('PassEndX within 0-105', df['PassEndX'].dropna().between(0, 105).all())
check('PassEndY within 0-68', df['PassEndY'].dropna().between(0, 68).all())
p = df[df['PassEndX'].notna() & df['endX'].notna()]
check('PassEndX/Y match endX/endY (< 0.01 m)',
      ((p['PassEndX'] - p['endX']).abs().max() < 0.01) and ((p['PassEndY'] - p['endY']).abs().max() < 0.01))

# 3. zones, phase zones and channels
for tag in ZONE_TAGS:
    z, ph, ch = df[f'zone_{tag}'].dropna(), df[f'phaseZone_{tag}'].dropna(), df[f'channel_{tag}'].dropna()
    check(f'zone_{tag} in 1-18', z.between(1, 18).all())
    check(f'phaseZone_{tag} values valid', set(ph) <= PHASES)
    check(f'channel_{tag} values valid', set(ch) <= CHANNELS)

xcol = {'start': 'x', 'end': 'endX', 'passEnd': 'PassEndX'}
ycol = {'start': 'y', 'end': 'endY', 'passEnd': 'PassEndY'}
for tag in ZONE_TAGS:
    d = df[df[f'zone_{tag}'].notna()]
    band = ((d[f'zone_{tag}'] - 1) // 3).astype(int)
    check(f'zone_{tag} band matches x',
          ((d[xcol[tag]] >= band * 17.5 - 1e-9) & (d[xcol[tag]] <= (band + 1) * 17.5 + 1e-9)).all())
    lane = ((d[f'zone_{tag}'] - 1) % 3).astype(int)          # 0 = left (high y)
    check(f'zone_{tag} lane matches y (zone 1 = left = high y)',
          ((d[ycol[tag]] >= (2 - lane) * 68 / 3 - 1e-9) & (d[ycol[tag]] <= (3 - lane) * 68 / 3 + 1e-9)).all())

d = df[df['phaseZone_start'].notna()]
order = d['phaseZone_start'].map({'Build': 0, 'Progress': 1, 'Penetrate': 2, 'Finish': 3})
check('phaseZone_start matches x (26.25 m parts)',
      ((d['x'] >= order * 26.25 - 1e-9) & (d['x'] <= (order + 1) * 26.25 + 1e-9)).all())
check('Central channel = six-yard-box width', df.loc[df['channel_start'] == 'Central', 'y'].between(24.84, 43.16).all())
check('Wide Left channel = y > 54.16', (df.loc[df['channel_start'] == 'Wide Left', 'y'] > 54.16).all())

# 4. distance (x, y) -> (endX, endY)
dist = np.hypot(df['endX'] - df['x'], df['endY'] - df['y'])
check('distance_start_end = Euclidean distance', np.allclose(df['distance_start_end'], dist, equal_nan=True))
L = df['Length'].notna() & df['distance_start_end'].notna()
check('distance_start_end close to WhoScored Length (median diff < 0.5 m)',
      (df.loc[L, 'Length'] - df.loc[L, 'distance_start_end']).abs().median() < 0.5)

# 5. carry before the pass
passes = df['type'] == 'Pass'
check('carry columns only on passes', df.loc[~passes, 'carry_distance'].isna().all())
check('carry on every pass', df.loc[passes, 'carry_distance'].notna().all())
c = df[passes]
check('carry_distance = distance from carry start to pass origin',
      np.allclose(c['carry_distance'], np.hypot(c['x'] - c['carry_startX'], c['y'] - c['carry_startY'])))
check('carry_progress = x - carry_startX', np.allclose(c['carry_progress'], c['x'] - c['carry_startX']))
check('carry_distance >= |carry_progress|', (c['carry_distance'] + 1e-9 >= c['carry_progress'].abs()).all())

# 6. xT of passes and carries
if 'xT_pass' in df.columns:
    ok_pass = (df['type'] == 'Pass') & (df['outcomeType'] == 'Successful') & df['endX'].notna()
    check('xT_pass on every completed pass only', df.loc[ok_pass, 'xT_pass'].notna().all() and df.loc[~ok_pass, 'xT_pass'].isna().all())
    check('xT values within the grid range (-0.26 .. 0.26)', df['xT_pass'].dropna().abs().max() <= 0.26 and df['xT_carry'].dropna().abs().max() <= 0.26)
    check('xT_carry only where a carry exists', df.loc[df['xT_carry'].notna(), 'carry_distance'].gt(0).all())

# 7. FotMob player ids
if 'fotmob_player_id' in df.columns:
    pl = df[df['name'].notna()]
    check('every event with a player has a FotMob player id', pl['fotmob_player_id'].notna().all())
    check('one FotMob id per player', (pl.groupby('name')['fotmob_player_id'].nunique() <= 1).all())

print(f"\n{len(failures)} failure(s)" if failures else '\nall checks passed')
sys.exit(1 if failures else 0)
