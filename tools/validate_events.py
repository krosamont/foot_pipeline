"""Consistency checks on an event CSV exported by postmatchdashboard_whoscored_v2.py (any match).

Usage:
    python tools/validate_events.py <match>_qualifiers_expanded.csv [--momentum <match>_momentum.csv] [--fotmob matchDetails.json]

Every check prints PASS / WARN / FAIL with the rows involved. Exit code 1 when a FAIL is found.
Coordinates are WhoScored's, in metres, from the acting team's point of view (x 0 -> 105 toward the opponent goal).
"""
import argparse
import ast
import json
import sys

import numpy as np
import pandas as pd

PITCH_LENGTH, PITCH_WIDTH = 105.0, 68.0
MIRROR_TOL = 2.0          # m, two rows of the same duel must sit on the same spot once mirrored
results = []


def report(level, name, detail=''):
    results.append(level)
    print(f'{level:4}  {name}' + (f'\n      {detail}' if detail else ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--momentum')
    ap.add_argument('--fotmob')
    a = ap.parse_args()

    df = pd.read_csv(a.csv, index_col=0, low_memory=False)
    df['T'] = df['expandedMinute'].fillna(0) * 60 + df['second'].fillna(0)
    real = df[~df['type'].isin(['Start', 'End', 'FormationSet', 'FormationChange'])]

    # 0. periods the 3D can draw: two halves and extra time; a penalty shoot-out is left out of the 3D
    drawn = {'FirstHalf', 'SecondHalf', 'FirstPeriodOfExtraTime', 'SecondPeriodOfExtraTime', 'PreMatch', 'PostGame'}
    other = sorted(set(df['period'].dropna()) - drawn)
    et = [p for p in ('FirstPeriodOfExtraTime', 'SecondPeriodOfExtraTime') if p in set(df['period'])]
    report('PASS' if not other else 'WARN', 'periods drawn by the 3D (halves + extra time; no penalty shoot-out)',
           (f'extra time: {et}. ' if et else '') + (f'not drawn: {other}' if other else ''))
    if et:   # WhoScored's expandedMinute may overlap between periods; build_data.py shifts them, this reports it
        T_ = df['expandedMinute'].fillna(0) * 60 + df['second'].fillna(0)
        order = [p for p in ('FirstHalf', 'SecondHalf', 'FirstPeriodOfExtraTime', 'SecondPeriodOfExtraTime') if p in set(df['period'])]
        ov = [(a, b) for a, b in zip(order, order[1:]) if T_[df['period'] == b].min() <= T_[df['period'] == a].max()]
        report('INFO' if ov else 'PASS', 'periods follow each other in time', f'overlapping (shifted by build_data.py): {ov}' if ov else '')
    own = df[(df['type'] == 'Goal') & df['qualifiers'].astype(str).str.contains('OwnGoal')]
    report('INFO' if len(own) else 'PASS', 'own goals', f'{len(own)} own goal(s): counted for the other side' if len(own) else '')

    # 1. coordinates on the pitch
    bad = real[(real['x'] < 0) | (real['x'] > PITCH_LENGTH) | (real['y'] < 0) | (real['y'] > PITCH_WIDTH)]
    report('PASS' if bad.empty else 'FAIL', 'coordinates inside 105 x 68 m', '' if bad.empty else f'{len(bad)} rows, e.g. {bad.index[:5].tolist()}')

    # 2. fouls: one row per team at the same time, at the same spot once mirrored; who had the ball
    fouls = df[df['type'] == 'Foul']
    unpaired, off_spot, offensive = [], [], 0
    for T, g in fouls.groupby('T'):
        won, lost = g[g['outcomeType'] == 'Successful'], g[g['outcomeType'] == 'Unsuccessful']
        if len(won) != 1 or len(lost) != 1 or won.iloc[0]['teamName'] == lost.iloc[0]['teamName']:
            unpaired.append(T); continue
        w, l = won.iloc[0], lost.iloc[0]
        if abs(w['x'] + l['x'] - PITCH_LENGTH) > MIRROR_TOL or abs(w['y'] + l['y'] - PITCH_WIDTH) > MIRROR_TOL:
            off_spot.append(T)
        offensive += bool(l.get('Offensive') is True or str(l.get('Offensive')) == 'True')
    report('PASS' if not unpaired else 'WARN', 'every foul has a fouled row and a committer row', f'unpaired at T = {unpaired[:10]}' if unpaired else '')
    report('PASS' if not off_spot else 'FAIL', 'the two rows of a foul are at the same spot (mirrored frames)', f'mismatch at T = {off_spot[:10]}' if off_spot else '')
    report('INFO' if offensive else 'PASS', 'offensive fouls (committer had the ball)',
           f'{offensive} fouls are offensive: the side in possession is the committer, not the fouled side' if offensive else '')

    # 3. shots from the team's own half
    shots = df[df['type'].isin(['Goal', 'SavedShot', 'MissedShots', 'ShotOnPost'])]
    own = shots[(shots['x'] < PITCH_LENGTH / 2) & ~shots['qualifiers'].astype(str).str.contains('OwnGoal')]
    report('PASS' if own.empty else 'WARN', 'shots taken in the attacking half', '' if own.empty else f'{len(own)} shots from own half at T = {own["T"].tolist()[:10]}')

    # 4. pass destination qualifiers agree with endX / endY
    if 'PassEndX' in df.columns:
        p = df[df['PassEndX'].notna() & df['endX'].notna()]
        dx = (p['PassEndX'] - p['endX']).abs().max() if len(p) else 0
        dy = (p['PassEndY'] - p['endY']).abs().max() if len(p) else 0
        report('PASS' if max(dx, dy) < 0.5 else 'FAIL', 'PassEndX/Y (metres) match endX/endY', f'max gap {max(dx, dy):.2f} m')

    # 5. period start/end markers sit at the edges of their period
    misplaced = []
    for period, g in df[df['type'] == 'End'].groupby('period'):
        last = real[real['period'] == period]['T'].max()
        misplaced += [(period, float(t)) for t in g['T'] if t < last - 120]
    report('PASS' if not misplaced else 'WARN', "'End' markers at the end of their period",
           f'End events long before the last event of the period: {misplaced}' if misplaced else '')

    # 6. events in time order inside each period
    order = [p for p, g in real.groupby('period', sort=False) if (g['T'].diff().dropna() < -1).any()]
    report('PASS' if not order else 'WARN', 'events in time order inside each period', f'out of order in {order}' if order else '')

    # 7. carries: implausible lengths
    if 'carry_distance' in df.columns:
        long_c = df[df['carry_distance'] > 60]
        report('PASS' if long_c.empty else 'WARN', 'carries shorter than 60 m', '' if long_c.empty else f'{len(long_c)} carries > 60 m at T = {long_c["T"].tolist()[:10]}')

    # 8. cards: present in the events, and in agreement with FotMob's count
    cards = df[df['type'].astype(str).str.contains('Card')]
    fm = json.load(open(a.fotmob)) if a.fotmob else None
    if fm:
        stats = {s['key']: s['stats'] for grp in fm['content']['stats']['Periods']['All']['stats'] for s in grp['stats'] if 'key' in s}
        n_fm = sum(sum(int(v) for v in stats.get(k, [0, 0])) for k in ('yellow_cards', 'red_cards'))
        report('PASS' if n_fm == len(cards) else 'FAIL', 'card events match FotMob card count', f'CSV {len(cards)} cards, FotMob {n_fm}')
    else:
        report('INFO', 'card events in the CSV', f'{len(cards)} cards (pass --fotmob to cross-check)')

    # 9. xT: recomputed xT_pass agrees in sign with the dashboard xT column
    if 'xT_pass' in df.columns and 'xT' in df.columns:
        both = df[df['xT_pass'].notna() & df['xT'].notna()]
        agree = (np.sign(both['xT_pass']) == np.sign(both['xT'])).mean() if len(both) else 1
        report('PASS' if agree > 0.8 else 'WARN', 'xT_pass and xT agree in sign', f'{100 * agree:.0f} % of {len(both)} passes')

    # 10. momentum: the recomputed xT momentum vs FotMob's, minute by minute
    if a.momentum and fm and fm.get('content', {}).get('momentum'):
        mom = pd.read_csv(a.momentum)
        fmm = pd.DataFrame(fm['content']['momentum']['main']['data'])
        sh = float(df[df['period'] == 'SecondHalf']['T'].min())
        mom['cm'] = [min((m + 0.5), 45) if p == 'FirstHalf' else min(45 + ((m + 0.5) * 60 - sh) / 60, 90) for m, p in zip(mom['expandedMinute'], mom['period'])]
        f = np.interp(mom['cm'], fmm['minute'], fmm['value'])
        a_ = mom['smoothed_momentum'] / (mom['smoothed_momentum'].abs().max() or 1)
        strong = (np.abs(a_) > 0.3) & (np.abs(f) > 30) & (np.sign(a_) != np.sign(f))
        report('PASS' if strong.mean() < 0.1 else 'WARN', 'CSV xT momentum and FotMob momentum agree',
               f'opposite with both strong at minutes {mom.loc[strong, "cm"].round(1).tolist()}' if strong.any() else '')

    print('\n' + ('FAILED' if 'FAIL' in results else 'OK') + f'  ({results.count("PASS")} pass, {results.count("WARN")} warn, {results.count("FAIL")} fail)')
    sys.exit(1 if 'FAIL' in results else 0)


if __name__ == '__main__':
    main()
