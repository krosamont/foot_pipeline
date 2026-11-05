"""Raw JSON of a match (raw/whoscored.json, raw/fotmob.json) -> flat CSV files (raw/csv/<table>.csv), values unchanged.

Flattening only, no computation: every list of objects becomes a table of its own (one row per element, `_index` =
its position in the list, plus the keys of its parent: `_event_index`, `_side`, `teamId`...); a nested object becomes
columns `<key>_<sub key>`; a short list of values inside an object becomes columns `<key>_0`, `<key>_1`...; a map
(object whose keys are ids or minutes, e.g. per-minute stats) becomes rows (key, value). Values are written as in the
JSON: text as is, numbers as JSON writes them (1.0 stays 1.0), true / false, null = empty cell.
Left out (in the JSON files, not in the tables): the parts of the pages that are not about the match itself (FotMob
nav, seo, h2h, table, liveticker, buzz, poll, insights, team form, top players, QA, heatmap) and repeats of a table
(WhoScored home/away incidentEvents = rows of events; FotMob playerStats shotmap = rows of shotmap; FotMob rawStats).

Written when a match is downloaded (pmd/run.py, next to the JSON: <match folder>/raw/csv/*.csv); tools/load_raw.py
loads them into the schema z_raw of the football database (and writes them first for a match that has none).

    python -m pmd.brut_csv <match folder>/raw [...]      (re)writes <match folder>/raw/csv/*.csv
"""
import csv
import json
import os
import re
import sys

SIDES = ('home', 'away')


def value(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, str):
        return v
    return json.dumps(v)   # numbers as in the JSON


def col(k):
    return re.sub(r'\W+', '_', str(k)).strip('_')


def flat(o, prefix='', out=None, skip=()):
    """One row: nested objects -> <key>_<sub key>, lists of values or objects -> <key>_<i>[_<sub key>]."""
    out = {} if out is None else out
    items = o.items() if isinstance(o, dict) else enumerate(o)
    for k, v in items:
        if k in skip:
            continue
        name = f'{prefix}{col(k)}'
        if isinstance(v, (dict, list)):
            if len(v) > 12:
                raise ValueError(f'{name}: {len(v)} elements in one row, make it a table')
            flat(v, name + '_', out)
        else:
            out[name] = value(v)
    return out


def write(folder, tables):
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        if f.endswith('.csv'):
            os.remove(os.path.join(folder, f))
    for name, rows in tables.items():
        if not rows:
            continue
        cols = list(dict.fromkeys(c for r in rows for c in r))
        with open(os.path.join(folder, f'{name}.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)


def whoscored(w):
    t = {k: [] for k in ('whoscored_match', 'whoscored_period', 'whoscored_expanded_minute', 'whoscored_player_name',
                         'whoscored_team', 'whoscored_team_stat', 'whoscored_team_shot_zone', 'whoscored_formation',
                         'whoscored_formation_player', 'whoscored_player', 'whoscored_player_stat', 'whoscored_event',
                         'whoscored_event_qualifier', 'whoscored_event_satisfied_type', 'whoscored_common_event')}
    t['whoscored_match'].append(flat(w, skip={'home', 'away', 'events', 'playerIdNameDictionary', 'periodMinuteLimits',
                                              'expandedMinutes', 'periodEndMinutes', 'commonEvents'}))
    limits, ends = w.get('periodMinuteLimits') or {}, w.get('periodEndMinutes') or {}
    for p in dict.fromkeys([*limits, *ends]):
        t['whoscored_period'].append({'period': p, 'periodMinuteLimits': value(limits.get(p)),
                                      'periodEndMinutes': value(ends.get(p))})
    for p, minutes in (w.get('expandedMinutes') or {}).items():
        for m, e in minutes.items():
            t['whoscored_expanded_minute'].append({'period': p, 'minute': m, 'expandedMinute': value(e)})
    for pid, name in (w.get('playerIdNameDictionary') or {}).items():
        t['whoscored_player_name'].append({'playerId': pid, 'name': value(name)})
    for i, e in enumerate(w.get('commonEvents') or []):
        t['whoscored_common_event'].append({'_index': i, **flat(e)})
    for side in SIDES:
        team = w.get(side) or {}
        tid = value(team.get('teamId'))
        t['whoscored_team'].append({'_side': side, **flat(team, skip={'players', 'formations', 'stats', 'incidentEvents',
                                                                        'shotZones'})})
        for stat, per_minute in (team.get('stats') or {}).items():
            if isinstance(per_minute, list):          # minutesWithStats: the minutes that have stats
                per_minute = {m: None for m in per_minute}
            for m, v in per_minute.items():
                t['whoscored_team_stat'].append({'_side': side, 'teamId': tid, 'stat': stat, 'minute': m, 'value': value(v)})
        for zone, z in (team.get('shotZones') or {}).items():
            for m, s in ((z or {}).get('stats') or {}).items():
                t['whoscored_team_shot_zone'].append({'_side': side, 'teamId': tid, 'zone': zone, 'minute': m, **flat(s)})
        for i, f in enumerate(team.get('formations') or []):
            lists = ('jerseyNumbers', 'formationSlots', 'playerIds', 'formationPositions')
            t['whoscored_formation'].append({'_side': side, 'teamId': tid, '_index': i, **flat(f, skip=set(lists))})
            n = max(len(f.get(k) or []) for k in lists)
            for j in range(n):
                row = {'_side': side, 'teamId': tid, '_formation_index': i, '_index': j}
                for k in lists:
                    v = (f.get(k) or [None] * n)[j] if j < len(f.get(k) or []) else None
                    if isinstance(v, dict):
                        flat(v, k + '_', row)
                    elif not any(isinstance(x, dict) for x in f.get(k) or []):
                        row[k] = value(v)
                t['whoscored_formation_player'].append(row)
        for p in team.get('players') or []:
            t['whoscored_player'].append({'_side': side, 'teamId': tid, **flat(p, skip={'stats'})})
            for stat, per_minute in (p.get('stats') or {}).items():
                for m, v in per_minute.items():
                    t['whoscored_player_stat'].append({'_side': side, 'teamId': tid, 'playerId': value(p.get('playerId')),
                                                       'stat': stat, 'minute': m, 'value': value(v)})
    for i, e in enumerate(w.get('events') or []):
        t['whoscored_event'].append({'_index': i, **flat(e, skip={'qualifiers', 'satisfiedEventsTypes'})})
        for j, q in enumerate(e.get('qualifiers') or []):
            t['whoscored_event_qualifier'].append({'_event_index': i, 'id': value(e.get('id')), '_index': j, **flat(q)})
        for j, s in enumerate(e.get('satisfiedEventsTypes') or []):
            t['whoscored_event_satisfied_type'].append({'_event_index': i, 'id': value(e.get('id')), '_index': j,
                                                        'value': value(s)})
    return t


def fotmob(f):
    t = {k: [] for k in ('fotmob_match', 'fotmob_team', 'fotmob_lineup', 'fotmob_player', 'fotmob_player_event',
                         'fotmob_player_stat', 'fotmob_shot', 'fotmob_momentum', 'fotmob_team_stat',
                         'fotmob_referee_stat')}
    content = f.get('content') or {}
    facts = content.get('matchFacts') or {}
    info = facts.get('infoBox') or {}
    lineup = content.get('lineup') or {}
    row = {'ongoing': value(f.get('ongoing')), 'hasPendingVAR': value(f.get('hasPendingVAR'))}
    flat(f.get('general') or {}, 'general_', row)
    flat((f.get('header') or {}).get('status') or {}, 'status_', row)
    flat(info, 'infoBox_', row, skip={'Referee'})
    flat(info.get('Referee') or {}, 'infoBox_Referee_', row, skip={'stats'})
    flat(content.get('weather') or {}, 'weather_', row)
    flat({k: v for k, v in lineup.items() if k not in ('homeTeam', 'awayTeam')}, 'lineup_', row)
    flat({k: v for k, v in (content.get('momentum') or {}).get('main', {}).items() if k != 'data'}, 'momentum_', row)
    t['fotmob_match'].append(row)
    for i, s in enumerate((info.get('Referee') or {}).get('stats') or []):
        t['fotmob_referee_stat'].append({'_index': i, **flat(s)})
    for i, team in enumerate((f.get('header') or {}).get('teams') or []):
        t['fotmob_team'].append({'_index': i, **flat(team)})
    for side in ('homeTeam', 'awayTeam'):
        team = lineup.get(side) or {}
        t['fotmob_lineup'].append({'_side': side, **flat(team, skip={'starters', 'subs', 'unavailable'})})
        for role in ('starters', 'subs', 'unavailable'):
            for i, p in enumerate(team.get(role) or []):
                perf = p.get('performance') or {}
                r = {'_side': side, 'teamId': value(team.get('id')), '_role': role, '_index': i,
                     **flat(p, skip={'performance'})}
                flat(perf, 'performance_', r, skip={'events', 'substitutionEvents'})
                t['fotmob_player'].append(r)
                for kind in ('events', 'substitutionEvents'):
                    for j, e in enumerate(perf.get(kind) or []):
                        t['fotmob_player_event'].append({'_side': side, 'id': value(p.get('id')), '_list': kind,
                                                         '_index': j, **flat(e)})
    for pid, p in (content.get('playerStats') or {}).items():
        for i, section in enumerate(p.get('stats') or []):
            for name, s in (section.get('stats') or {}).items():
                t['fotmob_player_stat'].append({'id': pid, 'name': value(p.get('name')), 'optaId': value(p.get('optaId')),
                                                'teamId': value(p.get('teamId')), 'teamName': value(p.get('teamName')),
                                                'isGoalkeeper': value(p.get('isGoalkeeper')),
                                                'shirtNumber': value(p.get('shirtNumber')),
                                                'usualPosition': value(p.get('usualPosition')),
                                                '_section_index': i, 'section_title': value(section.get('title')),
                                                'section_key': value(section.get('key')), 'stat': name, **flat(s)})
    for i, s in enumerate((content.get('shotmap') or {}).get('shots') or []):
        t['fotmob_shot'].append({'_index': i, **flat(s)})
    for i, m in enumerate(((content.get('momentum') or {}).get('main') or {}).get('data') or []):
        t['fotmob_momentum'].append({'_index': i, **flat(m)})
    for period, p in ((content.get('stats') or {}).get('Periods') or {}).items():
        for i, section in enumerate(p.get('stats') or []):
            for j, s in enumerate(section.get('stats') or []):
                t['fotmob_team_stat'].append({'period': period, '_section_index': i, 'section_title': value(section.get('title')),
                                              'section_key': value(section.get('key')), '_index': j,
                                              **flat(s, skip={'rawStats'})})
    return t


def convert(raw):
    """raw: the folder holding whoscored.json and fotmob.json; writes raw/csv/*.csv, returns the rows per table."""
    tables = {}
    for name, fn in (('whoscored.json', whoscored), ('fotmob.json', fotmob)):
        p = os.path.join(raw, name)
        if os.path.exists(p):
            tables.update(fn(json.load(open(p, encoding='utf-8'))))
    write(os.path.join(raw, 'csv'), tables)
    return {k: len(v) for k, v in tables.items()}


if __name__ == '__main__':
    for folder in sys.argv[1:]:
        print(folder, convert(folder))
