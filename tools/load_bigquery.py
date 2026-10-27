"""Load the matches of data/matches/ into BigQuery, in four tables of their own (beaming-axon-458621-n8.foot_new:
match, player, event, metric), next to the tables of the old project (soccer.*, not touched), after the old scripts
~/data/foot/whoscored/gcp/0_ecrire_gcp_table.py and 2_update_gcp_table.py.

    python tools/load_bigquery.py --dry-run --limit 3     (build 3 matches, print the columns, load nothing)
    python tools/load_bigquery.py                         (load the matches not loaded yet, or changed since, from 2025-2026)

The data are loaded as they are in the match folders, not converted to the old conventions; every row has
data_convention = 'foot_3d' (the files of data/matches/ as they are: x, y in metres on a 105 x 68 pitch, flags
'True', missing values NULL), unlike soccer.* (old project: x, y on the 0-100 scale, flags 'true', missing text 'None').
Sources (one folder data/matches/<competition>_<season>/<whoscored id>_<Home>_vs_<Away>/):
  event  - <match>_qualifiers_expanded.csv, every column (xT, xG, xGOT, zones, carries, names...);
  player - PlayerData.csv (WhoScored line-ups, 'stats' kept as text) + FotMob id / country / photo (<match>_players.csv)
           + new per-match totals: WhoScored rating and stats summed over the match, minutes, goals, assists, shots,
           xG, xGOT, xT, key and progressive passes, cards;
  match  - raw/whoscored.json and <match>_match_info.csv (one row per match, FotMob columns as home_* / away_*);
  metric - the old per-match team statistics, computed as the old project did, + new ones per side (h/a): xG,
           xGOT, xT, big chances, key passes, assists, progressive passes, final-third passes, box touches, tackles,
           interceptions, clearances, recoveries, aerials won, fouls, cards, offsides, saves, PPDA, momentum.
Every row also gets match_id (WhoScored id), competition ('premier-league', 'laliga', 'serie-a', 'bundesliga',
'ligue-1', 'champions-league') and season ('2026-2027'), as in the old tables.
Only what BigQuery needs is changed: a column whose name differs from another only by case gets the suffix _q
(qualifier BlockedX next to blockedX...), names with other characters are cleaned; values are cast to the type of
the BigQuery column (text when the column is text).
Abandoned matches are left out. The column types are decided over all the matches of a run (text as soon as one
value is not a number), so that a column never changes type from one batch to the next.
What was loaded is kept in data/gcp/bigquery_loaded.json (match id -> date of its files); a match whose files
changed is deleted from the four tables and loaded again.
Credentials: the old project's service-account key, or $GOOGLE_APPLICATION_CREDENTIALS.
"""
import argparse
import ast
import glob
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', message='.*pandas-gbq.*')   # load_table_from_dataframe works without it
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATCHES = os.path.join(ROOT, 'data', 'matches')
STATE = os.path.join(ROOT, 'data', 'gcp', 'bigquery_loaded.json')
KEY = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                     os.path.expanduser('~/data/foot/whoscored/gcp/beaming-axon-458621-n8-e461d33e2be6.json'))
DATASET = 'foot_new'
OLD_DATASET = 'soccer'   # the old project's tables: same region, never written
TABLES = ['match', 'player', 'event', 'metric']
CONVENTION = 'foot_3d'
COMPETITION = {'serie': 'serie-a'}   # folder slug -> name used in the old tables
FIRST_SEASON = '2025-2026'         # seasons loaded: this one and the later ones
BATCH = 50                           # matches per load job
S, I, F, T = 'STRING', 'INTEGER', 'FLOAT', 'TIMESTAMP'
# types of new columns that pandas cannot guess from one batch (a column empty in a batch would become FLOAT)
NEW_TYPES = {
    'match': {'kickoff_utc': T, 'league_round': S, 'ht_score': S, 'home_manager': S, 'away_manager': S},
    'player': {'subbedOutPeriod': S, 'subbedInPeriod': S, 'stats': S, 'country': S, 'photo_url': S, 'fotmob_player_id': I,
               **{c: I for c in ('minutes_played', 'goals', 'own_goals', 'assists', 'key_passes', 'shots', 'shots_on_target',
                                 'progressive_passes', 'yellow_cards', 'red_cards')}},
    'event': {'qualifiers': S, 'cardType_x': S, 'cardType_y': S, 'isGoal_x': S, 'isGoal_y': S, 'teamName': S, 'name': S,
              'position': S, 'isFirstEleven': S, 'shortName': S, 'shot_type': S, 'situation': S, 'fm_is_blocked': S,
              'fotmob_player_id': I, **{f'{k}_{w}': S for k in ('phaseZone', 'channel') for w in ('start', 'end', 'passEnd')}},
    'metric': {},
}
CLUSTER = {'match': ['competition', 'season', 'match_id'], 'player': ['competition', 'season', 'match_id'],
           'event': ['competition', 'season', 'match_id', 'type'], 'metric': ['competition', 'season', 'match_id']}
RATIOS = {'passSuccess', 'aerialSuccess', 'tackleSuccess', 'dribbleSuccess', 'throwInAccuracy'}   # not summed
SHOTS = ['Goal', 'MissedShots', 'SavedShot', 'ShotOnPost']
PROGRESSIVE = 9.11   # metres gained towards the goal (column pro of the export)


def _one(pattern):
    found = glob.glob(pattern)
    return found[0] if found else None


def _true(s):
    return s.astype(str).str.lower() == 'true'


def stamp(folder):
    files = [os.path.join(folder, f) for f in ('EventData.csv', 'PlayerData.csv')] + glob.glob(os.path.join(folder, '*_*.csv'))
    return int(max(os.path.getmtime(f) for f in files if os.path.exists(f)))


def abandoned(folder):
    p = os.path.join(folder, 'raw', 'fotmob.json')
    if not os.path.exists(p):
        return False
    st = (json.load(open(p, encoding='utf-8')).get('header') or {}).get('status') or {}
    return bool(st.get('cancelled')) or (st.get('reason') or {}).get('longKey') in ('aborted', 'postponed', 'cancelled')


def bq_names(df):
    """Column names BigQuery accepts, unique without regard to case: the first one keeps its name, the others get _q."""
    seen, names = set(), []
    for c in df.columns:
        n = re.sub(r'[^A-Za-z0-9_]', '_', str(c))
        n = n if re.match(r'[A-Za-z_]', n) else '_' + n
        while n.lower() in seen:
            n += '_q'
        seen.add(n.lower())
        names.append(n)
    df.columns = names
    return df


def old_metrics(ev, h, a):
    """The old per-match team statistics, computed as the old project did (create_csv_data.py), from the raw events:
    possession = share of passes, field tilt = share of touches beyond x 70 (0-100 scale), qualifiers matched in their text."""
    q = ev['qualifiers'].astype(str)
    team = ev['teamId']
    passes = ev['type'] == 'Pass'
    ok = ev['outcomeType'] == 'Successful'
    n = lambda m: int(m.sum())
    out, tp = {}, n(passes)
    touches = _true(ev['isTouch']) & (ev['x'] >= 70)
    tt = n(touches)
    shots = ev['type'].isin(SHOTS)
    for side, t in (('h', h), ('a', a)):
        mine = team == t
        out[f'{side}Possession_pct'] = round(n(mine & passes) / tp * 100, 2) if tp else 0
        out[f'{side}FieldTilt_pct'] = round(n(mine & touches) / tt * 100, 2) if tt else 0
        s = shots & mine
        goals = n(s & (ev['type'] == 'Goal') & ~q.str.contains('OwnGoal'))
        out[f'{side}TotalShots'] = n(s)
        out[f'{side}goal_count'] = goals
        out[f'{side}ShotsOnT'] = n(s & (ev['type'] == 'SavedShot') & ~q.str.contains(': 82,')) + goals
        out[f'{side}TotalPass'] = n(mine & passes)
        out[f'{side}AccPass'] = n(mine & passes & ok)
        for key, word in (('Crosses', 'Cross'), ('Freekick', 'Freekick'), ('Corner', 'Corner'), ('ThrowIn', 'ThrowIn'), ('GoalKicks', 'GoalKick')):
            out[f'{side}{key}'] = n(mine & passes & q.str.contains(word))
        out[f'{side}AccCrosses'] = n(mine & passes & q.str.contains('Cross') & ok)
        drb = mine & (ev['type'] == 'TakeOn') & q.str.contains('Offensive')
        out[f'{side}Dribbling'] = n(drb)
        out[f'{side}AccDribbling'] = n(drb & ok)
    return out


def build(folder):
    """The four tables of one match folder, as DataFrames."""
    comp_season = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    slug, season = comp_season.rsplit('_', 1)
    tag = dict(match_id=int(os.path.basename(os.path.normpath(folder)).split('_', 1)[0]),
               competition=COMPETITION.get(slug, slug), season=season, data_convention=CONVENTION)

    raw_ev = pd.read_csv(os.path.join(folder, 'EventData.csv'), index_col=0, low_memory=False)
    pl = pd.read_csv(os.path.join(folder, 'PlayerData.csv'), index_col=0, low_memory=False)
    exp = pd.read_csv(_one(os.path.join(folder, '*_qualifiers_expanded.csv')), index_col=0, low_memory=False)
    info = pd.read_csv(_one(os.path.join(folder, '*_match_info.csv'))).set_index('side')
    fm_players = _one(os.path.join(folder, '*_players.csv'))
    fm_players = pd.read_csv(fm_players) if fm_players else pd.DataFrame()
    momentum = _one(os.path.join(folder, '*_momentum.csv'))
    momentum = pd.read_csv(momentum) if momentum else pd.DataFrame()
    raw = os.path.join(folder, 'raw', 'whoscored.json')
    w = json.load(open(raw, encoding='utf-8')) if os.path.exists(raw) else {}

    h = int(pl.loc[pl['field'] == 'home', 'teamId'].iloc[0])
    a = int(pl.loc[pl['field'] == 'away', 'teamId'].iloc[0])
    names = exp.dropna(subset=['teamName']).drop_duplicates('teamId').set_index('teamId')['teamName'].to_dict()
    for side, t in (('home', h), ('away', a)):
        names.setdefault(t, (w.get(side) or {}).get('name') or info.loc[side, 'team_name'])
    fmi = lambda side, col: info.loc[side, col] if col in info.columns and not pd.isna(info.loc[side, col]) else None

    # ---- event: the expanded CSV as it is
    event = exp.drop(columns=['Unnamed: 0'], errors='ignore').copy()
    for k, v in tag.items():
        event[k] = v

    # ---- match
    ref = w.get('referee') or {}
    start = pd.to_datetime(w.get('startDate'), errors='coerce')
    kickoff = pd.to_datetime(fmi('home', 'matchTimeUTCDate'), utc=True, errors='coerce')
    day = start if not pd.isna(start) else (kickoff.tz_localize(None).normalize() if not pd.isna(kickoff) else None)
    row = {
        'title_match': re.sub(r'[^a-z0-9]+', '-', f"{day.year if day is not None else ''}-{names[h]}-{names[a]}".lower()).strip('-'),
        **tag, 'date': day, 'time_start': w.get('timeStamp'), 'attendance': w.get('attendance', fmi('home', 'attendance')),
        'stadium': w.get('venueName') or fmi('home', 'stadium'), 'refereeId': ref.get('officialId'),
        'refereeFirstName': ref.get('firstName'), 'refereeLastName': ref.get('lastName'),
        'home_team': names[h], 'away_team': names[a], 'home_team_id': h, 'away_team_id': a,
        'ht_score': w.get('htScore') or None, 'ft_score': w.get('ftScore') or None,
        'home_manager': (w.get('home') or {}).get('managerName'), 'away_manager': (w.get('away') or {}).get('managerName'),
        'kickoff_utc': kickoff, 'fotmob_match_id': info['matchId'].iloc[0],
    }
    shared = ['matchTimeUTC', 'leagueName', 'leagueRoundName', 'gender', 'stadium', 'city', 'country', 'lat', 'long',
              'capacity', 'surface', 'attendance', 'referee']
    for col in shared:
        if col in info.columns:
            row[f'fotmob_{col}'] = fmi('home', col)
    row['league_round'] = None if fmi('home', 'leagueRoundName') is None else str(fmi('home', 'leagueRoundName'))
    for side in ('home', 'away'):
        for col in info.columns:
            if col not in shared and col not in ('matchId', 'side', 'matchTimeUTCDate'):
                row[f'{side}_{col}'] = fmi(side, col)
    match = pd.DataFrame([row])

    # ---- player: PlayerData.csv as it is + FotMob id, country, photo + per-match totals
    player = pl.copy()
    player['team'] = player['teamId'].map(names)
    for k, v in tag.items():
        player[k] = v
    ids = exp[['playerId', 'fotmob_player_id']].dropna().drop_duplicates('playerId').set_index('playerId')['fotmob_player_id'] \
        if 'fotmob_player_id' in exp else pd.Series(dtype=float)
    player['fotmob_player_id'] = player['playerId'].map(ids)
    if len(fm_players) and 'fotmob_player_id' in fm_players:
        by_id = fm_players.dropna(subset=['fotmob_player_id']).drop_duplicates('fotmob_player_id').set_index('fotmob_player_id')
        for col, new in (('country', 'country'), ('photo', 'photo_url')):
            if col in by_id:
                player[new] = player['fotmob_player_id'].map(by_id[col])
    totals = []
    for s in pl['stats'].fillna('{}'):
        d = ast.literal_eval(s) if isinstance(s, str) else {}
        r = {}
        for k, per_minute in d.items():
            if k == 'ratings':
                r['rating'] = per_minute[max(per_minute, key=int)] if per_minute else None
            elif k not in RATIOS:
                r[f'stat_{k}'] = float(sum(per_minute.values()))
        totals.append(r)
    player = pd.concat([player, pd.DataFrame(totals, index=pl.index)], axis=1)
    end = int(exp['expandedMinute'].max())
    on = pd.to_numeric(player.get('subbedInExpandedMinute'), errors='coerce')
    off = pd.to_numeric(player.get('subbedOutExpandedMinute'), errors='coerce')
    begin = pd.Series(np.where(_true(player['isFirstEleven']), 0, on), index=player.index)
    player['minutes_played'] = np.where(begin.isna(), 0, (off.fillna(end) - begin).clip(lower=0)).round()

    q = exp
    flag = lambda col: _true(q[col]) if col in q else pd.Series(False, index=q.index)
    card = q['cardType_x'].astype(str) if 'cardType_x' in q else pd.Series('', index=q.index)
    yellow, red = card.str.contains("'Yellow'|SecondYellow"), card.str.contains("'Red'|SecondYellow")
    own = flag('OwnGoal')
    shots = q['type'].isin(SHOTS) & ~own
    goal = (q['type'] == 'Goal') & ~own
    passes = q['type'] == 'Pass'
    ok = q['outcomeType'] == 'Successful'
    prog = passes & ok & (pd.to_numeric(q.get('pro'), errors='coerce') >= PROGRESSIVE) if 'pro' in q else pd.Series(False, index=q.index)
    count = lambda mask: player['playerId'].map(q[mask].groupby('playerId').size()).fillna(0)
    total = lambda mask, col: player['playerId'].map(q[mask].groupby('playerId')[col].sum()).round(4) if col in q else None
    player['goals'], player['own_goals'] = count(goal), count((q['type'] == 'Goal') & own)
    player['assists'], player['key_passes'] = count(flag('IntentionalGoalAssist')), count(flag('KeyPass'))
    player['shots'] = count(shots)
    player['shots_on_target'] = count(goal | (q['type'] == 'SavedShot') & ~flag('Blocked'))
    player['progressive_passes'] = count(prog)
    player['yellow_cards'], player['red_cards'] = count(yellow), count(red)
    player['xg'], player['xgot'] = total(shots, 'xg'), total(shots, 'xgot')
    player['xT'] = total(pd.Series(True, index=q.index), 'xT')

    # ---- metric: old statistics (old method, raw events on the 0-100 scale), then the new ones
    raw_ev = raw_ev.copy()
    for c in ('type', 'outcomeType'):
        raw_ev[c] = raw_ev[c].map(lambda v: ast.literal_eval(v).get('displayName') if isinstance(v, str) and v.startswith('{') else v)
    m = {'match_id': tag['match_id'], **old_metrics(raw_ev, h, a), 'competition': tag['competition'], 'season': season,
         'data_convention': CONVENTION}
    team = q['teamId']
    x = pd.to_numeric(q['x'], errors='coerce') / 1.05      # back on the 0-100 scale for the zones below
    y = pd.to_numeric(q['y'], errors='coerce') / 0.68
    end_x = pd.to_numeric(q['endX'], errors='coerce') / 1.05
    touch = _true(q['isTouch'])
    defensive = q['type'].isin(['Tackle', 'Interception', 'Challenge']) | ((q['type'] == 'Foul') & ~ok)
    for side, t, o in (('h', h, a), ('a', a, h)):
        mine = team == t
        n = lambda mask: int((mine & mask).sum())
        m[f'{side}xG'] = round(float(q.loc[mine & shots, 'xg'].sum()), 4) if 'xg' in q else None
        m[f'{side}xGOT'] = round(float(q.loc[mine & shots, 'xgot'].sum()), 4) if 'xgot' in q else None
        m[f'{side}xT'] = round(float(q.loc[mine, 'xT'].sum()), 4) if 'xT' in q else None
        m[f'{side}Goals'] = n(goal) + int(((team == o) & (q['type'] == 'Goal') & own).sum())   # own goals count for the other side
        m[f'{side}BigChances'] = n(shots & flag('BigChance'))
        m[f'{side}BigChancesCreated'] = n(flag('BigChanceCreated'))
        m[f'{side}KeyPasses'] = n(flag('KeyPass'))
        m[f'{side}Assists'] = n(flag('IntentionalGoalAssist'))
        m[f'{side}ProgPasses'] = n(prog)
        m[f'{side}FinalThirdPasses'] = n(passes & ok & (end_x >= 200 / 3))
        m[f'{side}BoxTouches'] = n(touch & (x >= 83) & y.between(21.1, 78.9))
        m[f'{side}Tackles'] = n(q['type'] == 'Tackle')
        m[f'{side}TacklesWon'] = n((q['type'] == 'Tackle') & ok)
        m[f'{side}Interceptions'] = n(q['type'] == 'Interception')
        m[f'{side}Clearances'] = n(q['type'] == 'Clearance')
        m[f'{side}Recoveries'] = n(q['type'] == 'BallRecovery')
        m[f'{side}AerialsWon'] = n((q['type'] == 'Aerial') & ok)
        m[f'{side}Fouls'] = n((q['type'] == 'Foul') & ~ok)
        m[f'{side}Yellow'], m[f'{side}Red'] = n(yellow), n(red)
        m[f'{side}Offsides'] = n(q['type'] == 'OffsideGiven')
        m[f'{side}Saves'] = n((q['type'] == 'Save') & ~flag('OutfielderBlock'))   # goalkeeper saves
        m[f'{side}CornersRealised'] = n(passes & flag('CornerTaken'))           # from the CornerTaken flag
        m[f'{side}CrossesRealised'] = n(passes & flag('Cross') & ~flag('CornerTaken'))
        # PPDA: opponent passes in its first 60 % of the pitch / our defensive actions in that area
        actions = n(defensive & (x >= 40))
        m[f'{side}PPDA'] = round(int(((team == o) & passes & (x <= 60)).sum()) / actions, 2) if actions else None
    m['home_score'], m['away_score'] = fmi('home', 'score'), fmi('away', 'score')
    m['fotmob_match_id'] = info['matchId'].iloc[0]
    if len(momentum) and 'momentum' in momentum:
        m['momentum_mean'] = round(float(momentum['momentum'].mean()), 5)
        m['hMomentumMinutes'] = int((momentum['momentum'] > 0).sum())
        m['aMomentumMinutes'] = int((momentum['momentum'] < 0).sum())
    metric = pd.DataFrame([m])
    return {t: bq_names(df.reset_index(drop=True)) for t, df in
            (('match', match), ('player', player), ('event', event), ('metric', metric))}


# ---------------------------------------------------------------- BigQuery
def client():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(KEY, scopes=['https://www.googleapis.com/auth/cloud-platform'])
    return bigquery.Client(credentials=creds, project=creds.project_id)


def _kind(s):
    """Type of one column of one match: None when empty."""
    v = s.dropna()
    if not len(v):
        return None
    if s.dtype == bool or v.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        return 'BOOLEAN'
    if pd.api.types.is_datetime64_any_dtype(s):
        return 'TIMESTAMP'
    num = pd.to_numeric(v, errors='coerce')
    if num.notna().all():
        return 'INTEGER' if s.dtype.kind in 'iu' else 'FLOAT'
    return 'STRING'


RANK = {'BOOLEAN': 0, 'INTEGER': 1, 'FLOAT': 2, 'TIMESTAMP': 3, 'STRING': 4}


def merge_types(types, tabs):
    """types[table][column]: the widest type seen so far (INTEGER < FLOAT < STRING; BOOLEAN or TIMESTAMP mixed with
    anything else: STRING)."""
    for t, df in tabs.items():
        cur = types.setdefault(t, {})
        for c in df.columns:
            k = _kind(df[c])
            old = cur.get(c)
            if k is None or old == k:
                cur.setdefault(c, None)
                continue
            if old is None:
                cur[c] = k
            elif {old, k} <= {'INTEGER', 'FLOAT'}:
                cur[c] = 'FLOAT'
            else:
                cur[c] = 'STRING'


def _missing(v):
    return v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v))


def conform(df, table, fields):
    """The frame with exactly the columns of `fields`, typed like them; missing values stay NULL."""
    out = {}
    for f in fields:
        s = df[f.name] if f.name in df.columns else pd.Series(None, index=df.index, dtype=object)
        if f.field_type == 'INTEGER':
            s = pd.to_numeric(s, errors='coerce').round().astype('Int64')
        elif f.field_type == 'FLOAT':
            s = pd.to_numeric(s, errors='coerce').astype('float64')
        elif f.field_type == 'BOOLEAN':
            s = s.map(lambda v: None if _missing(v) else str(v).lower() in ('true', '1')).astype('boolean')
        elif f.field_type == 'TIMESTAMP':
            s = pd.to_datetime(s, errors='coerce', utc=True)
        else:
            s = s.map(lambda v: None if _missing(v) else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))).astype(object)
        out[f.name] = s
    return pd.DataFrame(out)


def prepare(bq, types):
    """Dataset and tables created when missing; new columns appended; returns {table: schema}."""
    from google.cloud import bigquery
    from google.api_core.exceptions import NotFound
    ds_id = f'{bq.project}.{DATASET}'
    try:
        bq.get_dataset(ds_id)
    except NotFound:
        ds = bigquery.Dataset(ds_id)
        ds.location = bq.get_dataset(f'{bq.project}.{OLD_DATASET}').location
        ds.description = 'foot_3d matches (data/matches/ of the server), loaded by tools/load_bigquery.py'
        bq.create_dataset(ds)
        print(f'[bq] dataset {ds_id} created ({ds.location})', flush=True)
    schemas = {}
    for t in TABLES:
        cols = types.get(t, {})
        wanted = [bigquery.SchemaField(c, NEW_TYPES[t].get(c) or k or 'STRING') for c, k in cols.items()]
        table_id = f'{ds_id}.{t}'
        try:
            tb = bq.get_table(table_id)
        except NotFound:
            tb = bigquery.Table(table_id, schema=wanted)
            tb.clustering_fields = CLUSTER[t]
            tb = bq.create_table(tb)
            print(f'[bq] table {table_id} created: {len(wanted)} columns', flush=True)
        have = {f.name.lower(): f for f in tb.schema}
        holds = lambda old, new: old == new or old == 'STRING' or (old == 'FLOAT' and new == 'INTEGER')
        clash = [f'{f.name} ({have[f.name.lower()].field_type} <- {f.field_type})' for f in wanted
                 if f.name.lower() in have and not holds(have[f.name.lower()].field_type, f.field_type)]
        if clash:
            raise SystemExit(f'[bq] {t}: these columns cannot hold the new values, nothing loaded: {", ".join(clash)}')
        added = [f for f in wanted if f.name.lower() not in have]
        if added:
            tb.schema = list(tb.schema) + added
            tb = bq.update_table(tb, ['schema'])
            print(f'[bq] {t}: {len(added)} new column(s): {", ".join(f.name for f in added)}', flush=True)
        schemas[t] = list(tb.schema)
    return schemas


def load(bq, table, df, fields):
    from google.cloud import bigquery
    frame = conform(df, table, fields)
    cfg = bigquery.LoadJobConfig(schema=fields, write_disposition='WRITE_APPEND')
    bq.load_table_from_dataframe(frame, f'{bq.project}.{DATASET}.{table}', job_config=cfg).result()
    print(f'[bq] {table}: +{len(frame)} rows', flush=True)


def delete(bq, ids):
    from google.cloud import bigquery
    if not ids:
        return
    cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter('ids', 'INT64', sorted(ids))])
    for t in TABLES:
        job = bq.query(f'DELETE FROM `{bq.project}.{DATASET}.{t}` WHERE match_id IN UNNEST(@ids)', job_config=cfg)
        job.result()
        print(f'[bq] {t}: {job.num_dml_affected_rows} rows of earlier loads deleted', flush=True)


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def mid_of(folder):
    return os.path.basename(os.path.normpath(folder)).split('_', 1)[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help='build the tables and print their columns, load nothing')
    ap.add_argument('--limit', type=int, default=None, help='only the first N matches to load (test)')
    ap.add_argument('--seasons', nargs='+', default=None, help=f'only these seasons, like 2026-2027 (default: {FIRST_SEASON} and later)')
    a = ap.parse_args(argv)

    folders = sorted(d for d in glob.glob(os.path.join(MATCHES, '*_*-*', '*_*', ''))
                     if os.path.exists(os.path.join(d, 'EventData.csv')) and glob.glob(os.path.join(d, '*_qualifiers_expanded.csv')))
    season_of = lambda d: os.path.basename(os.path.dirname(os.path.normpath(d))).rsplit('_', 1)[1]
    folders = [d for d in folders if (season_of(d) in a.seasons if a.seasons else season_of(d) >= FIRST_SEASON)]
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    todo = [d for d in folders if state.get(mid_of(d)) != stamp(d) and not abandoned(d)][:a.limit]
    print(f'[bq] {len(folders)} match folders, {len(todo)} to load', flush=True)
    if not todo:
        return 0

    # pass 1: the type of every column over all the matches of the run
    types, built = {}, []
    for d in todo:
        try:
            merge_types(types, build(d))
            built.append(d)
        except Exception as e:
            print(f'[bq] skipped {d}: {e!r}', flush=True)
    print(f'[bq] {len(built)} matches read; columns: ' + ', '.join(f'{t} {len(types.get(t, {}))}' for t in TABLES), flush=True)
    if a.dry_run:
        tabs = build(built[0])
        for t in TABLES:
            print(f'[dry-run] {t}: {len(tabs[t])} rows; ' + ', '.join(f'{c}:{NEW_TYPES[t].get(c) or k}' for c, k in types[t].items()))
        print(tabs['metric'].T.to_string())
        return 0

    # pass 2: load, BATCH matches per load job
    bq = client()
    schemas = prepare(bq, types)
    for k in range(0, len(built), BATCH):
        frames, ok = {t: [] for t in TABLES}, []
        for d in built[k:k + BATCH]:
            tabs = build(d)
            for t in TABLES:
                frames[t].append(tabs[t])
            ok.append(d)
        # marked 'pending' before the load: if the run stops half-way, the next run deletes those rows first
        ids = [mid_of(d) for d in ok]
        again = {int(i) for i in ids if i in state}
        for i in ids:
            state[i] = 'pending'
        save_state(state)
        delete(bq, again)
        for t in TABLES:
            load(bq, t, pd.concat(frames[t], ignore_index=True), schemas[t])
        for d in ok:
            state[mid_of(d)] = stamp(d)
        save_state(state)
        print(f'[bq] {min(k + BATCH, len(built))}/{len(built)} matches done', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
