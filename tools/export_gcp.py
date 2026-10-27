"""The matches of data/matches/ as the four Parquet files of the old project (match_df, player_df, event_df,
metrics_df), sent to Google Cloud Storage (gs://foot-bucket/foot_3d/ by default).

    python tools/export_gcp.py              (build the four files in data/gcp/)
    python tools/export_gcp.py --upload     (and send the ones that changed to the bucket)

Same columns, types and conventions as ~/data/foot/whoscored/combined_data/*.parquet:
  - competition 'premier-league', 'laliga', 'serie-a', 'bundesliga', 'ligue-1', 'champions-league'; season '2025-2026';
    match_id = WhoScored id;
  - event_df: the WhoScored events as they come (x, y on the 0-100 scale), every qualifier its own column as text
    ('true' for a flag); player_df: the WhoScored line-ups; metrics_df: the old per-match team statistics.
Columns added after the old ones (foot_3d): FotMob ids, score, xG / xGOT and shot details, xT of passes and carries,
zones, phase zones and channels, carries, coordinates in metres (*_m), short names.

Each match is turned into four small Parquet files once (data/gcp/parts/, rebuilt when its export changes), then the
four big files are written part after part (never the whole season in memory).
Credentials: the old project's service-account key, or $GOOGLE_APPLICATION_CREDENTIALS.
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

MATCHES = os.path.join(ROOT, 'data', 'matches')
OUT = os.path.join(ROOT, 'data', 'gcp')
PARTS = os.path.join(OUT, 'parts')
TABLES = ['match_df', 'player_df', 'event_df', 'metrics_df']
BUCKET, PREFIX = 'foot-bucket', 'foot_3d/'
KEY = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                     os.path.expanduser('~/data/foot/whoscored/gcp/beaming-axon-458621-n8-e461d33e2be6.json'))
OLD_COMPETITION = {'serie': 'serie-a'}   # foot_3d folder slug -> name used in the old files

# old column types (combined_data/*.parquet); qualifier columns of event_df are text
OLD = {
    'match_df': {'title_match': 'string', 'match_id': 'int64', 'competition': 'string', 'season': 'string', 'date': 'timestamp',
                 'time_start': 'string', 'attendance': 'int64', 'stadium': 'string', 'refereeId': 'int64',
                 'refereeFirstName': 'string', 'refereeLastName': 'string'},
    'player_df': {'playerId': 'int64', 'shirtNo': 'int64', 'name': 'string', 'position': 'string', 'height': 'int64', 'weight': 'int64',
                  'age': 'int64', 'isFirstEleven': 'string', 'isManOfTheMatch': 'bool', 'field': 'string', 'teamId': 'int64',
                  'team': 'string', 'match_id': 'int64', 'competition': 'string', 'season': 'string', 'subbedInPlayerId': 'double',
                  'subbedOutExpandedMinute': 'double', 'subbedInExpandedMinute': 'double', 'subbedOutPlayerId': 'double'},
    'event_df': {'id': 'double', 'eventId': 'int64', 'minute': 'int64', 'second': 'double', 'teamId': 'int64', 'x': 'double', 'y': 'double',
                 'expandedMinute': 'int64', 'period': 'string', 'type': 'string', 'outcomeType': 'string', 'satisfiedEventsTypes': 'string',
                 'isTouch': 'bool', 'team': 'string', 'match_id': 'int64', 'competition': 'string', 'season': 'string', 'playerId': 'double',
                 'endX': 'double', 'endY': 'double', 'relatedEventId': 'double', 'relatedPlayerId': 'double', 'goalMouthZ': 'double',
                 'goalMouthY': 'double', 'isGoal': 'string', 'isShot': 'string', 'blockedX': 'double', 'blockedY': 'double'},
    'metrics_df': {'match_id': 'int64', **{c: 'int64' for c in [
        'hTotalShots', 'aTotalShots', 'hgoal_count', 'agoal_count', 'hShotsOnT', 'aShotsOnT']},
        'hPossession_pct': 'double', 'aPossession_pct': 'double', 'hFieldTilt_pct': 'double', 'aFieldTilt_pct': 'double',
        **{c: 'int64' for c in ['hTotalPass', 'aTotalPass', 'hAccPass', 'aAccPass', 'hCrosses', 'aCrosses', 'hAccCrosses', 'aAccCrosses',
                                'hFreekick', 'aFreekick', 'hCorner', 'aCorner', 'hThrowIn', 'aThrowIn', 'hGoalKicks', 'aGoalKicks',
                                'hDribbling', 'aDribbling', 'hAccDribbling', 'aAccDribbling']},
        'competition': 'string', 'season': 'string'},
}
# the 115 qualifier columns of the old event_df, in their order: always present (empty when a match has none)
OLD_QUALIFIERS = [
    'HighCentre', 'OutfielderBlock', 'Length', 'TeamFormation', 'SixYardBlock', 'HighLeft', 'KeyPass', 'ShotAssist',
    'DeepBoxLeft', 'Chipped', 'OutOfBoxCentre', 'ThrowIn', 'RightFoot', 'GoalDisallowed', 'FreekickTaken',
    'IntentionalAssist', 'KeeperSaveInTheBox', 'JerseyNumber', 'CaptainPlayerId', 'DivingSave', 'HeadPass', 'Cross',
    'Blocked', 'Hands', 'FromCorner', 'LastMan', 'BigChanceCreated', 'CornerTaken', 'LowRight', 'MissLeft',
    'PassEndY', 'InvolvedPlayers', 'SetPiece', 'BoxCentre', 'Zone', 'TeamPlayerFormation', 'PlayerPosition',
    'PlayerCaughtOffside', 'LowLeft', 'Foul', 'OtherBodyPart', 'BlockedY', 'BlockedX', 'LeadingToAttempt',
    'RegularPlay', 'OppositeRelatedEvent', 'IntentionalGoalAssist', 'Feet', 'IndirectFreekickTaken', 'MissRight',
    'SmallBoxRight', 'FormationSlot', 'Defensive', 'GoalKick', 'Head', 'StandingSave', 'BigChance', 'LowCentre',
    'Longball', 'GoalMouthY', 'BoxLeft', 'MissHigh', 'BoxRight', 'SmallBoxCentre', 'LeftFoot', 'KeeperSaveObox',
    'Offensive', 'OverRun', 'Assisted', 'Throughball', 'LayOff', 'KeeperThrow', 'BlockedCross', 'PassEndX',
    'GoalMouthZ', 'Collected', 'RelatedEventId', 'Angle', 'ParriedSafe', 'Yellow', 'Penalty', 'DirectFreekick',
    'HighRight', 'HighClaim', 'SavedOffline', 'ThirtyFivePlusLeft', 'KeeperWentWide', 'FastBreak', 'isOwnGoal',
    'SmallBoxLeft', 'ThrowinSetPiece', 'OwnGoal', 'VoidYellowCard', 'FromShotOffTarget', 'SecondYellow',
    'AerialFoul', 'OutOfBoxDeepLeft', 'ParriedDanger', 'KeeperMissed', 'LeadingToGoal', 'DeepBoxRight',
    'KeeperSaveInSixYard', 'ThirtyFivePlusCentre', 'OutOfBoxDeepRight', 'OutOfBoxLeft', 'KeeperSaved',
    'Obstruction', 'ThirtyFivePlusRight', 'Red', 'FirstTouch', 'OneOnOne', 'IndividualPlay', 'Volley',
    'OutOfBoxRight', 'DirectCorner',
]
# foot_3d columns of <match>_qualifiers_expanded.csv added to event_df (joined on the event id)
EXTRA_EVENT = ['zone_start', 'phaseZone_start', 'channel_start', 'zone_end', 'phaseZone_end', 'channel_end',
               'zone_passEnd', 'phaseZone_passEnd', 'channel_passEnd', 'distance_start_end',
               'carry_startX', 'carry_startY', 'carry_distance', 'carry_progress', 'xT_pass', 'xT_carry', 'xT', 'pro',
               'xg', 'xgot', 'shot_type', 'situation', 'fm_is_blocked', 'fm_goal_crossed_y', 'fm_goal_crossed_z',
               'fotmob_player_id', 'shortName']
METRES = {'x': 'x_m', 'y': 'y_m', 'endX': 'endX_m', 'endY': 'endY_m', 'PassEndX': 'PassEndX_m', 'PassEndY': 'PassEndY_m'}
# types of the foot_3d columns, fixed so that every match gives the same schema (a column empty in one match and
# filled in another must not change type); any other column: text, or double for numbers
_S, _I, _D = 'string', 'int64', 'double'
EXTRA = {
    'match_df': {'home_team': _S, 'away_team': _S, 'home_team_id': _I, 'away_team_id': _I, 'home_score': _I, 'away_score': _I,
                 'fotmob_match_id': _I, 'fotmob_home_team_id': _I, 'fotmob_away_team_id': _I, 'league_name': _S, 'league_round': _S,
                 'kickoff_utc': _S, 'city': _S, 'country': _S, 'capacity': _I, 'surface': _S, 'home_color': _S, 'away_color': _S},
    'player_df': {'subbedOutPeriod': _S, 'subbedInPeriod': _S, 'fotmob_player_id': _I, 'country': _S, 'photo_url': _S},
    'event_df': {**{f'zone_{k}': _I for k in ('start', 'end', 'passEnd')}, **{f'phaseZone_{k}': _S for k in ('start', 'end', 'passEnd')},
                 **{f'channel_{k}': _S for k in ('start', 'end', 'passEnd')}, 'shot_type': _S, 'situation': _S, 'fm_is_blocked': _S,
                 'fotmob_player_id': _I, 'shortName': _S},
    'metrics_df': {'fotmob_match_id': _I},
}


def _arrow(kind):
    return {'string': pa.string(), 'int64': pa.int64(), 'double': pa.float64(), 'bool': pa.bool_(),
            'timestamp': pa.timestamp('ns')}[kind]


def _typed(df, table):
    """Arrow table with the old types on the old columns, the EXTRA types on the foot_3d ones, text for the qualifiers."""
    fields = []
    for c in df.columns:
        kind = OLD[table].get(c) or EXTRA[table].get(c) or ('double' if df[c].dtype.kind in 'iuf' else 'string')
        fields.append(pa.field(c, _arrow(kind)))
    out = {}
    for f in fields:
        s = df[f.name]
        if pa.types.is_integer(f.type):
            s = pd.to_numeric(s, errors='coerce').astype('Int64')
        elif pa.types.is_floating(f.type):
            s = pd.to_numeric(s, errors='coerce').astype('float64')
        elif pa.types.is_boolean(f.type):
            s = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v)).astype('boolean')
        elif pa.types.is_timestamp(f.type):
            s = pd.to_datetime(s, errors='coerce')
        else:
            s = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
        out[f.name] = pa.array(s, type=f.type, from_pandas=True)
    return pa.table(out)


def _qualifiers(qs):
    """Old convention: one column per qualifier, its value as text, 'true' for a flag."""
    return {q['type']['displayName']: (str(q['value']) if 'value' in q else 'true') for q in qs or []}


def _metrics(ev, h, a):
    """The old per-match team statistics (create_csv_data.py), from the raw WhoScored events."""
    q = ev['qualifiers'].astype(str)
    team = ev['teamId']
    passes = ev['type'] == 'Pass'
    ok = ev['outcomeType'] == 'Successful'
    n = lambda m: int(m.sum())
    out = {}
    tp = n(passes)
    for side, t in (('h', h), ('a', a)):
        mine = team == t
        out[f'{side}Possession_pct'] = round(n(mine & passes) / tp * 100, 2) if tp else 0
    touches = (ev['isTouch'] == True) & (ev['x'] >= 70)   # noqa: E712
    tt = n(touches)
    for side, t in (('h', h), ('a', a)):
        out[f'{side}FieldTilt_pct'] = round(n((team == t) & touches) / tt * 100, 2) if tt else 0
    shots = ev['type'].isin(['Goal', 'MissedShots', 'SavedShot', 'ShotOnPost'])
    for side, t in (('h', h), ('a', a)):
        mine = team == t
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


def build_parts(folder):
    """The four tables of one match folder -> data/gcp/parts/<competition_season>/<whoscored id>/<table>.parquet."""
    csv = glob.glob(os.path.join(folder, '*_qualifiers_expanded.csv'))
    raw = os.path.join(folder, 'raw', 'whoscored.json')
    if not csv or not os.path.exists(raw):
        return None
    csv = csv[0]
    comp_season = os.path.basename(os.path.dirname(os.path.abspath(folder)))
    slug, season = comp_season.rsplit('_', 1)
    competition = OLD_COMPETITION.get(slug, slug)
    match_id = int(os.path.basename(os.path.normpath(folder)).split('_', 1)[0])
    dest = os.path.join(PARTS, comp_season, str(match_id))
    stamp = os.path.join(dest, 'source.txt')
    src = f'{os.path.getmtime(csv):.0f} {os.path.getmtime(raw):.0f}'
    if os.path.exists(stamp) and open(stamp).read() == src and all(os.path.exists(os.path.join(dest, t + '.parquet')) for t in TABLES):
        return dest

    w = json.load(open(raw, encoding='utf-8'))
    exp = pd.read_csv(csv, index_col=0, low_memory=False)
    info = pd.read_csv(csv.replace('_qualifiers_expanded.csv', '_match_info.csv')).set_index('side')
    players_fm = csv.replace('_qualifiers_expanded.csv', '_players.csv')
    players_fm = pd.read_csv(players_fm) if os.path.exists(players_fm) else pd.DataFrame()
    teams = {w['home']['teamId']: w['home']['name'], w['away']['teamId']: w['away']['name']}
    h, a = w['home']['teamId'], w['away']['teamId']
    tag = dict(match_id=match_id, competition=competition, season=season)
    fm = lambda side, col: info.loc[side, col] if col in info.columns else None

    # ---- match_df
    ref = w.get('referee') or {}
    start = pd.to_datetime(w.get('startDate') or w.get('startTime'), errors='coerce')
    title = re.sub(r'[^a-z0-9]+', '-', f"{w['home']['name']}-{w['away']['name']}".lower()).strip('-')
    match = pd.DataFrame([{
        'title_match': title, **tag, 'date': start.normalize() if not pd.isna(start) else None, 'time_start': w.get('timeStamp'),
        'attendance': w.get('attendance'), 'stadium': w.get('venueName'), 'refereeId': ref.get('officialId'),
        'refereeFirstName': ref.get('firstName'), 'refereeLastName': ref.get('lastName'),
        # foot_3d
        'home_team': w['home']['name'], 'away_team': w['away']['name'], 'home_team_id': h, 'away_team_id': a,
        'home_score': fm('home', 'score'), 'away_score': fm('away', 'score'), 'fotmob_match_id': info['matchId'].iloc[0],
        'fotmob_home_team_id': fm('home', 'fotmob_team_id'), 'fotmob_away_team_id': fm('away', 'fotmob_team_id'),
        'league_name': fm('home', 'leagueName'), 'league_round': fm('home', 'leagueRoundName'), 'kickoff_utc': fm('home', 'matchTimeUTCDate'),
        'city': fm('home', 'city'), 'country': fm('home', 'country'), 'capacity': fm('home', 'capacity'), 'surface': fm('home', 'surface'),
        'home_color': fm('home', 'color_darkMode'), 'away_color': fm('away', 'color_darkMode'),
    }])

    # ---- player_df (WhoScored line-ups, as in the old files) + FotMob id, country and photo
    rows = []
    for side in ('home', 'away'):
        for p in w[side]['players']:
            r = {k: v for k, v in p.items() if k != 'stats'}
            r.update(teamId=w[side]['teamId'], team=w[side]['name'], field=p.get('field', side), **tag)
            rows.append(r)
    player = pd.DataFrame(rows)
    player['isFirstEleven'] = player.get('isFirstEleven', pd.Series(dtype=object)).map(lambda v: None if pd.isna(v) else str(v))
    ids = exp[['playerId', 'fotmob_player_id']].dropna().drop_duplicates('playerId').set_index('playerId')['fotmob_player_id']
    player['fotmob_player_id'] = player['playerId'].map(ids)
    if len(players_fm):
        by_id = players_fm.dropna(subset=['fotmob_player_id']).drop_duplicates('fotmob_player_id').set_index('fotmob_player_id')
        for col, new in (('country', 'country'), ('photo', 'photo_url')):
            player[new] = player['fotmob_player_id'].map(by_id[col]) if col in by_id else None
    player = player[[c for c in OLD['player_df'] if c in player.columns] + [c for c in player.columns if c not in OLD['player_df']]]

    # ---- event_df: raw WhoScored events, qualifiers in columns (old way), then the foot_3d columns
    ev = pd.DataFrame(w['events'])
    for c in ('period', 'type', 'outcomeType'):
        ev[c] = ev[c].map(lambda d: d.get('displayName') if isinstance(d, dict) else d)
    ev['team'] = ev['teamId'].map(teams)
    ev['satisfiedEventsTypes'] = ev['satisfiedEventsTypes'].map(str) if 'satisfiedEventsTypes' in ev else None
    for k, v in tag.items():
        ev[k] = v
    metrics = pd.DataFrame([{'match_id': match_id, **_metrics(ev, h, a), 'competition': competition, 'season': season}])
    quals = pd.DataFrame([_qualifiers(q) for q in ev['qualifiers']], index=ev.index)
    quals = quals[[c for c in quals.columns if c not in ev.columns]]
    base = [c for c in OLD['event_df'] if c in ev.columns]
    event = pd.concat([ev[base], quals], axis=1)
    extra = exp.drop_duplicates('id').set_index('id')
    for c in EXTRA_EVENT:
        if c in extra.columns:
            event[c] = event['id'].map(extra[c])
    for c, new in METRES.items():
        if c in extra.columns:
            event[new] = event['id'].map(extra[c])
    # metrics: foot_3d totals
    for side, t in (('h', h), ('a', a)):
        mine = event['teamId'] == t
        metrics[f'{side}xT'] = round(float(event.loc[mine, ['xT_pass', 'xT_carry']].sum().sum()), 4) if 'xT_pass' in event else None
        metrics[f'{side}xG'] = round(float(event.loc[mine, 'xg'].sum()), 4) if 'xg' in event else None
        metrics[f'{side}xGOT'] = round(float(event.loc[mine, 'xgot'].sum()), 4) if 'xgot' in event else None
    metrics['fotmob_match_id'] = info['matchId'].iloc[0]

    os.makedirs(dest, exist_ok=True)
    for name, df in (('match_df', match), ('player_df', player), ('event_df', event), ('metrics_df', metrics)):
        pq.write_table(_typed(df.reset_index(drop=True), name), os.path.join(dest, name + '.parquet'), compression='zstd')
    open(stamp, 'w').write(src)
    return dest


def combine(parts):
    """data/gcp/<table>.parquet from every part, written part after part with one schema (union of the columns)."""
    paths = []
    for t in TABLES:
        files = [os.path.join(p, t + '.parquet') for p in parts]
        schemas = [pq.read_schema(f) for f in files]
        schema = pa.unify_schemas(schemas, promote_options='permissive')
        # old columns first, in the old order, then the others as they come
        if t == 'event_df':   # every old qualifier column, even one no match has used yet
            schema = pa.unify_schemas([schema, pa.schema([pa.field(c, pa.string()) for c in OLD_QUALIFIERS])], promote_options='permissive')
        old = list(OLD[t]) + (OLD_QUALIFIERS if t == 'event_df' else [])
        order = [c for c in old if c in schema.names] + [c for c in schema.names if c not in old]
        schema = pa.schema([schema.field(c) for c in order])
        out = os.path.join(OUT, t + '.parquet')
        tmp = out + '.tmp'
        with pq.ParquetWriter(tmp, schema, compression='zstd') as wr:
            buf, rows = [], 0   # matches are written in blocks of ~250,000 rows (one row group each), not one per match
            for f in files:
                tab = pq.read_table(f)
                cols = [tab.column(c).cast(schema.field(c).type) if c in tab.schema.names else pa.nulls(tab.num_rows, schema.field(c).type)
                        for c in schema.names]
                buf.append(pa.Table.from_arrays(cols, schema=schema)); rows += tab.num_rows
                if rows >= 250_000:
                    wr.write_table(pa.concat_tables(buf)); buf, rows = [], 0
            if buf:
                wr.write_table(pa.concat_tables(buf))
        os.replace(tmp, out)
        paths.append(out)
        print(f'[gcp] {t}: {pq.ParquetFile(out).metadata.num_rows} rows, {len(schema)} columns, {os.path.getsize(out) / 1e6:.1f} MB', flush=True)
    return paths


def upload(paths):
    """Send the files whose content changed to gs://BUCKET/PREFIX (compared with the MD5 Google keeps)."""
    from google.cloud import storage
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(KEY)
    bucket = storage.Client(project=creds.project_id, credentials=creds).bucket(BUCKET)
    state_path = os.path.join(OUT, 'uploaded.json')   # what the bucket holds (MD5 per file), read by tools/check_matches.py
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    for p in paths:
        blob = bucket.blob(PREFIX + os.path.basename(p))
        md5 = hashlib.md5()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                md5.update(chunk)
        local = base64.b64encode(md5.digest()).decode()
        remote = bucket.get_blob(blob.name)
        if remote is not None and remote.md5_hash == local:
            print(f'[gcp] unchanged: gs://{BUCKET}/{blob.name}', flush=True)
        else:
            blob.chunk_size = 32 * 1024 * 1024
            blob.upload_from_filename(p, timeout=600)
            print(f'[gcp] sent: gs://{BUCKET}/{blob.name}', flush=True)
        state[os.path.basename(p)[:-len('.parquet')]] = md5.hexdigest()
        with open(state_path, 'w') as f:
            json.dump(state, f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--upload', action='store_true', help=f'send the files that changed to gs://{BUCKET}/{PREFIX}')
    ap.add_argument('--limit', type=int, default=None, help='only the first N matches (test)')
    a = ap.parse_args(argv)
    folders = sorted(glob.glob(os.path.join(MATCHES, '*', '*', '')))[:a.limit]
    parts, failed = [], 0
    for f in folders:
        try:
            p = build_parts(f)
            if p:
                parts.append(p)
        except Exception as e:
            failed += 1
            print(f'[gcp] skipped {f}: {e!r}', flush=True)
    print(f'[gcp] {len(parts)} matches ({failed} skipped)', flush=True)
    if not parts:
        return 1
    paths = combine(parts)
    if a.upload:
        upload(paths)
    return 0


if __name__ == '__main__':
    sys.exit(main())
