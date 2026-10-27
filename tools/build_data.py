#!/usr/bin/env python3
"""Build the 3D data of one match, fabric/data/<match>.js (and fabric/data.js, the default page), from its CSV.

Usage: python tools/build_data.py [<match>_qualifiers_expanded.csv] [--home "Team name"]
  - open one match in the 3D with fabric/index.html?match=<date>_<home>_vs_<away> (printed at the end); without ?match: the last built
  - default CSV: data/France_vs_England/France_vs_England_qualifiers_expanded.csv
  - home team: --home, else FotMob's home side from <match>_match_info.csv, else the team of the first 'Start' event
  - the momentum file <match>_momentum.csv next to the CSV is used when present
  - team names, logos and colours come from <match>_match_info.csv next to the CSV (see 'team identity')

Coordinates: pitch 105 x 68 m. X runs along the length with the home side attacking toward X=105,
the away side toward X=0. Y runs across the width. Match time T = expandedMinute*60 + second.
"""
import json, math, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # project root (this file is in tools/)
args = [a for a in sys.argv[1:]]
home_arg = None
if '--home' in args:
    i = args.index('--home'); home_arg = args[i + 1]; del args[i:i + 2]
CSV = os.path.abspath(args[0]) if args else os.path.join(ROOT, 'data', 'France_vs_England', 'France_vs_England_qualifiers_expanded.csv')

df = pd.read_csv(CSV, low_memory=False)
teams = list(dict.fromkeys(df['teamName'].dropna()))
starts = df[df['type'] == 'Start']['teamName'].dropna()

def _home_from_match_info():
    """Home side from FotMob (<match>_match_info.csv, side = home): the WhoScored team whose name fits FotMob's home
    name better than the away name (names differ: 'Man City' / 'Manchester City'). None without the file."""
    import difflib, unicodedata
    path = CSV.replace('_qualifiers_expanded.csv', '_match_info.csv')
    if not os.path.exists(path) or len(teams) != 2:
        return None
    info = pd.read_csv(path).set_index('side')['team_name']
    n = lambda x: re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode().lower())
    sim = lambda a, b: difflib.SequenceMatcher(None, n(a), n(b)).ratio() + (0.5 if n(a) in n(b) or n(b) in n(a) else 0)
    t0, t1 = teams
    straight = sim(t0, info['home']) + sim(t1, info['away'])
    swapped = sim(t1, info['home']) + sim(t0, info['away'])
    return t0 if straight >= swapped else t1

# home team: --home, else FotMob's home side (match_info.csv), else the team of the first 'Start' event
HOME = home_arg or _home_from_match_info() or (starts.iloc[0] if len(starts) else teams[0])
AWAY = next(t for t in teams if t != HOME)
df['T'] = df['expandedMinute'].fillna(0) * 60 + df['second'].fillna(0)
# periods drawn: the two halves and, when played, the two periods of extra time. The penalty shoot-out is not drawn.
# WhoScored's expandedMinute can overlap from one period to the next (e.g. second half ending at 97:11, extra time
# starting at 97:00): an overlapping period is shifted by whole minutes so that it starts after the previous one ends,
# which keeps match time T strictly increasing (SHIFT[period] is applied to the momentum file too).
PERIOD_NAMES = ['FirstHalf', 'SecondHalf', 'FirstPeriodOfExtraTime', 'SecondPeriodOfExtraTime']
NOMINAL = {'FirstHalf': (0, 45), 'SecondHalf': (45, 90), 'FirstPeriodOfExtraTime': (90, 105), 'SecondPeriodOfExtraTime': (105, 120)}
PERIOD_GAP = 1.0
df = df[df['period'] != 'PenaltyShootout'].copy()
SHIFT, prev_end = {}, None
for p in PERIOD_NAMES:
    m = df['period'] == p
    if not m.any():
        continue
    start = float(df.loc[m, 'T'].min())
    SHIFT[p] = 0.0 if prev_end is None or start >= prev_end + PERIOD_GAP else (prev_end + PERIOD_GAP - start) // 60 * 60 + 60
    df.loc[m, 'T'] += SHIFT[p]
    prev_end = float(df.loc[m, 'T'].max())
df = df.sort_values(['T', 'Unnamed: 0']).reset_index(drop=True)
df['team'] = (df['teamName'] == HOME).map({True: 'home', False: 'away'})

def to_pitch(team, x, y):
    """WhoScored (0-100, attacking -> 100) to pitch metres with home attacking +X."""
    # the CSV is already in metres (x 0-105 toward the opponent goal, y 0-68)
    if team == 'home':
        return float(x), float(y)
    return 105.0 - float(x), 68.0 - float(y)

# ---------------------------------------------------------------- periods
PERIODS = []   # [{name, start, end, nom0, nom1}]: match-time span of each period drawn and its nominal minutes
for p in PERIOD_NAMES:
    sub = df[df['period'] == p]
    if len(sub):
        start = float(sub['T'].min()) // 60 * 60 if PERIODS else 0.0   # a period's clock starts on a whole minute
        PERIODS.append(dict(name=p, start=start, end=float(sub['T'].max()), nom0=NOMINAL[p][0], nom1=NOMINAL[p][1]))
SECOND_HALF_START = PERIODS[1]['start']
FIRST_HALF_END = PERIODS[0]['end']
MATCH_END = PERIODS[-1]['end']

def period_of(T):
    """The period a match time belongs to (the previous one during a break)."""
    cur = PERIODS[0]
    for p in PERIODS:
        if T >= p['start']:
            cur = p
    return cur

# displayed minute: each period restarts at its nominal minute at its own kick-off, whatever the stoppage time before:
# 1..45(+n), 46..90(+n), 91..105(+n), 106..120(+n)
def display_minute(T):
    p = period_of(T)
    return p['nom0'] + 1 + int((T - p['start']) // 60), p['nom1']

def label_minute(T):
    m, cap = display_minute(T)
    return f"{cap}+{m-cap}'" if m > cap else f"{m}'"

# ---------------------------------------------------------------- players
# from <match>_players.csv next to the CSV (FotMob line-ups, written by the export script): id, shirt, age, club or
# country, and the FotMob photo URL. Without that file, players have no card details (name only).
COUNTRY_FR = {
    'France': 'France', 'England': 'Angleterre', 'Spain': 'Espagne', 'Germany': 'Allemagne', 'Italy': 'Italie', 'Portugal': 'Portugal',
    'Netherlands': 'Pays-Bas', 'Belgium': 'Belgique', 'Switzerland': 'Suisse', 'Austria': 'Autriche', 'Croatia': 'Croatie', 'Serbia': 'Serbie',
    'Denmark': 'Danemark', 'Norway': 'Norvège', 'Sweden': 'Suède', 'Finland': 'Finlande', 'Poland': 'Pologne', 'Czechia': 'Tchéquie',
    'Czech Republic': 'Tchéquie', 'Slovakia': 'Slovaquie', 'Slovenia': 'Slovénie', 'Hungary': 'Hongrie', 'Romania': 'Roumanie', 'Greece': 'Grèce',
    'Turkey': 'Turquie', 'Türkiye': 'Turquie', 'Ukraine': 'Ukraine', 'Russia': 'Russie', 'Scotland': 'Écosse', 'Wales': 'Pays de Galles',
    'Ireland': 'Irlande', 'Northern Ireland': 'Irlande du Nord', 'Iceland': 'Islande', 'Albania': 'Albanie', 'Kosovo': 'Kosovo',
    'Bosnia and Herzegovina': 'Bosnie-Herzégovine', 'North Macedonia': 'Macédoine du Nord', 'Montenegro': 'Monténégro', 'Georgia': 'Géorgie',
    'Armenia': 'Arménie', 'Israel': 'Israël', 'Bulgaria': 'Bulgarie', 'Luxembourg': 'Luxembourg', 'Uzbekistan': 'Ouzbékistan',
    'Morocco': 'Maroc', 'Algeria': 'Algérie', 'Tunisia': 'Tunisie', 'Egypt': 'Égypte', 'Senegal': 'Sénégal', 'Ivory Coast': "Côte d'Ivoire",
    "Côte d'Ivoire": "Côte d'Ivoire", 'Cameroon': 'Cameroun', 'Nigeria': 'Nigeria', 'Ghana': 'Ghana', 'Mali': 'Mali', 'Guinea': 'Guinée',
    'Burkina Faso': 'Burkina Faso', 'DR Congo': 'RD Congo', 'Congo': 'Congo', 'Gabon': 'Gabon', 'South Africa': 'Afrique du Sud',
    'Cape Verde': 'Cap-Vert', 'Gambia': 'Gambie', 'Zambia': 'Zambie', 'Angola': 'Angola', 'Equatorial Guinea': 'Guinée équatoriale',
    'Brazil': 'Brésil', 'Argentina': 'Argentine', 'Uruguay': 'Uruguay', 'Colombia': 'Colombie', 'Chile': 'Chili', 'Ecuador': 'Équateur',
    'Peru': 'Pérou', 'Paraguay': 'Paraguay', 'Venezuela': 'Venezuela', 'Mexico': 'Mexique', 'USA': 'États-Unis', 'United States': 'États-Unis',
    'Canada': 'Canada', 'Jamaica': 'Jamaïque', 'Japan': 'Japon', 'South Korea': 'Corée du Sud', 'Korea Republic': 'Corée du Sud',
    'Australia': 'Australie', 'Iran': 'Iran', 'Saudi Arabia': 'Arabie saoudite', 'Qatar': 'Qatar', 'China': 'Chine', 'New Zealand': 'Nouvelle-Zélande',
}
players = {}
plcsv = CSV.replace('_qualifiers_expanded.csv', '_players.csv')
if os.path.exists(plcsv):
    for _, p in pd.read_csv(plcsv, dtype={'shirt': str}).iterrows():
        players[p['name']] = dict(id=int(p['fotmob_player_id']), age=int(p['age']) if pd.notna(p['age']) else None,
                                  club=p['club'] if isinstance(p['club'], str) else None,   # (FotMob gives the club for national-team matches only)
                                  country=COUNTRY_FR.get(p['country'], p['country']) if isinstance(p['country'], str) else None,
                                  shirt=p['shirt'] if isinstance(p['shirt'], str) else None, photo=p['photo'] if isinstance(p['photo'], str) else None,
                                  side=p['side'])
else:
    print('players: no', os.path.basename(plcsv), '-> no player photos / details')

def norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z]', '', s)

pnorm = {norm(k): v for k, v in players.items()}
def player_info(name, team_side):
    if not isinstance(name, str) or not name.strip():
        # no player (a card shown to the bench or the staff, who are not in the line-ups)
        return dict(name='Banc', short='Banc', id=None, age=None, club=None, country=None, shirt=None, photo=None)
    p = pnorm.get(norm(name))
    if p is None:  # try last name match within the team
        last = norm(name.split()[-1])
        cands = [v for k, v in pnorm.items() if k.endswith(last) and v['side'] == team_side]
        p = cands[0] if cands else None
    short = name.split()[-1]
    if p:
        return dict(name=name, short=short, id=p['id'], age=p.get('age'), club=p.get('club'), country=p.get('country'), shirt=p.get('shirt'),
                    photo=p.get('photo'))
    return dict(name=name, short=short, id=None, age=None, club=None, country=None, shirt=None, photo=None)

# ---------------------------------------------------------------- shots / goals
shots = []
def body_part(r):
    """'head', 'right', 'left' or 'other' (WhoScored qualifiers Head / RightFoot / LeftFoot / OtherBodyPart), '' if none."""
    for col, key in (('Head', 'head'), ('RightFoot', 'right'), ('LeftFoot', 'left'), ('OtherBodyPart', 'other')):
        if col in r.index and str(r[col]) == 'True':
            return key
    return ''
for _, r in df[df['isShot'] == True].iterrows():
    X, Y = to_pitch(r['team'], r['x'], r['y'])
    is_goal = (r['type'] == 'Goal')
    if is_goal and 'OwnGoal' in str(r['qualifiers']):
        # own goal: the spot is where it happened, but the goal counts for the other side
        shots.append(dict(T=float(r['T']), team='away' if r['team'] == 'home' else 'home', X=round(X, 2), Y=round(Y, 2), xg=0.0,
                          type='Goal', situation='OwnGoal', goal=True, own=True, body=body_part(r), player=player_info(r['name'], r['team']), label=label_minute(r['T']) + ' (o.g.)'))
        continue
    xg = float(r['xg']) if not pd.isna(r['xg']) else 0.02
    shots.append(dict(T=float(r['T']), team=r['team'], X=round(X, 2), Y=round(Y, 2), xg=round(xg, 4),
                      type=r['type'], situation=r['situation'] if isinstance(r['situation'], str) else '', body=body_part(r),
                      goal=bool(is_goal), player=player_info(r['name'], r['team']), label=label_minute(r['T'])))

penalties = []
for _, r in df[df['type'] == 'PenaltyFaced'].iterrows():
    penalties.append(dict(T=float(r['T'])))
# penalty goals: tag the goal that follows a PenaltyFaced within 60 s or situation == 'Penalty'
for s in shots:
    s['penalty'] = (s['situation'] == 'Penalty') or any(abs(s['T'] - p['T']) < 60 for p in penalties)

# ---------------------------------------------------------------- progression (territory)
# for every on-ball action: how far up the pitch the team got with it.
# successful passes count where the team-mate received the ball (endX/endY), everything else where it happened.
# a pass played after a carry (carry_distance >= CARRY_MIN m, see the export script) also counts its origin:
# the ball got there on the player's feet, half a second before the pass.
CARRY_MIN = 3.0
prog = []
for _, r in df.iterrows():
    if pd.isna(r['x']) or not bool(r.get('isTouch', False)) or (r['x'] == 0 and r['y'] == 0):
        continue
    side = 1 if r['team'] == 'home' else -1
    if r['type'] == 'Pass' and r.get('carry_distance', 0) >= CARRY_MIN:
        Xc, Yc = to_pitch(r['team'], r['x'], r['y'])
        prog.append([round(float(r['T']) - 0.5, 1), side, round(Xc, 2), round(Yc, 2), 0.0])
    if r['type'] == 'Pass' and r['outcomeType'] == 'Successful' and not pd.isna(r['endX']):
        X, Y = to_pitch(r['team'], r['endX'], r['endY'])
    elif r['outcomeType'] != 'Successful' and r['type'] not in ('SavedShot', 'MissedShots', 'Goal', 'ShotOnPost'):
        continue   # lost duels, failed take-ons etc. gain nothing
    else:
        X, Y = to_pitch(r['team'], r['x'], r['y'])
    xt = float(r['xT']) if r['type'] == 'Pass' and r['outcomeType'] == 'Successful' and not pd.isna(r.get('xT')) else 0.0
    prog.append([round(float(r['T']), 1), side, round(X, 2), round(Y, 2), round(xt, 4)])   # [T, side, X, Y, xT]
prog.sort(key=lambda e: e[0])

# tackles won (WhoScored 'Tackle', Successful): the 3D raises the cloth where the ball was won, wherever it was
tackles = []
for _, r in df[(df['type'] == 'Tackle') & (df['outcomeType'] == 'Successful') & df['x'].notna()].iterrows():
    X, Y = to_pitch(r['team'], r['x'], r['y'])
    tackles.append([round(float(r['T']), 1), 1 if r['team'] == 'home' else -1, round(X, 2), round(Y, 2)])   # [T, side, X, Y]

# ---------------------------------------------------------------- momentum
# preferred: the xT momentum recomputed from the events by the export script (<match>_momentum.csv, per expandedMinute),
# put on the chart's minute axis (first half capped at 45, second half 45 -> 90) and scaled so the peak is +-100
mom_csv = None
mcsv = CSV.replace('_qualifiers_expanded.csv', '_momentum.csv')
if os.path.exists(mcsv):
    mdf = pd.read_csv(mcsv)
    peak = float(mdf['smoothed_momentum'].abs().max()) or 1.0
    mom_csv = []
    for _, r in mdf.iterrows():
        if r['period'] not in SHIFT:
            continue
        T = (r['expandedMinute'] + 0.5) * 60 + SHIFT[r['period']]
        p = next(q for q in PERIODS if q['name'] == r['period'])
        cm = min(p['nom0'] + max(0.0, T - p['start']) / 60, p['nom1'])
        mom_csv.append([round(cm, 2), round(100 * float(r['smoothed_momentum']) / peak, 1)])
    mom_csv = [p for i, p in enumerate(mom_csv) if i == len(mom_csv) - 1 or mom_csv[i + 1][0] > p[0]]   # one value per chart minute

mom_fotmob = None   # (the old France-England FotMob momentum file is no longer used: the momentum comes from the CSV)

# ---------------------------------------------------------------- subs / cards / stats
subs = []
names_by_id = df.dropna(subset=['playerId']).drop_duplicates('playerId').set_index('playerId')['name'].to_dict()
for _, r in df[df['type'] == 'SubstitutionOn'].iterrows():
    # the player coming on is linked (relatedPlayerId) to the player going off
    off = names_by_id.get(r['relatedPlayerId'], '') if not pd.isna(r.get('relatedPlayerId')) else ''
    subs.append(dict(T=float(r['T']), team=r['team'], player=r['name'], off=off if isinstance(off, str) else '', label=label_minute(r['T'])))
cards = []
for _, r in df[df['type'].str.contains('Card', na=False)].iterrows():
    q = str(r['qualifiers'])
    kind = 'red' if ('Red' in q or 'SecondYellow' in q) else 'yellow'
    X, Y = to_pitch(r['team'], r['x'], r['y'])
    cards.append(dict(T=float(r['T']), team=r['team'], kind=kind, player=player_info(r['name'], r['team']), X=X, Y=Y, label=label_minute(r['T'])))

# fouls: one record per foul, located where it happened (pitch frame), with who committed it
fouls = []
fdf = df[df['type'] == 'Foul']
for _, r in fdf[fdf['outcomeType'] == 'Successful'].iterrows():   # row of the fouled team
    X, Y = to_pitch(r['team'], r['x'], r['y'])
    other = fdf[(fdf['T'] == r['T']) & (fdf['outcomeType'] == 'Unsuccessful')]
    committer = other.iloc[0] if len(other) else None
    fouls.append(dict(T=float(r['T']), X=round(float(X), 2), Y=round(float(Y), 2),
                      team=committer['team'] if committer is not None else ('away' if r['team'] == 'home' else 'home'),
                      player=player_info(committer['name'], committer['team'])['short'] if committer is not None else '',
                      # side in possession: an offensive foul (WhoScored 'Offensive' on the committer) is made by the attacker
                      offensive=bool(committer is not None and committer.get('Offensive') is True),
                      label=label_minute(r['T'])))

# ---------------------------------------------------------------- attacking chains (for the percées)
# the team's uninterrupted sequence of on-ball actions leading to a shot or a foul: it starts after the last
# successful on-ball action of the opponent (or a gap of more than 30 s), at most 40 s back.
touch_df = df[(df['isTouch'] == True) & df['x'].notna()].sort_values('T')
def chain_start(T, team):
    t0, x0 = T, None
    for _, r in touch_df[(touch_df['T'] <= T) & (touch_df['T'] >= T - 40)].iloc[::-1].iterrows():
        if r['team'] != team and r['outcomeType'] == 'Successful':
            break
        if t0 - r['T'] > 30:
            break
        if r['team'] == team:
            t0, x0 = float(r['T']), to_pitch(team, r['x'], r['y'])[0]
    return t0, x0
# possession before a goal: the scorer's team has the ball from just after the opponent's last on-ball action
# (a successful touch, or any pass: a failed pass hands the ball over), back to at most POSS_MAX s and never before
# the start of the period. The 3D keeps the scorer's line from stepping back during the whole possession.
POSS_MAX = 120.0
# A foul committed by the team itself (its 'Unsuccessful' Foul row, e.g. an offensive foul) gives the ball away and also
# ends its possession; a foul it suffers does not (it keeps the ball with the free kick).
foul_given = df[(df['type'] == 'Foul') & (df['outcomeType'] == 'Unsuccessful')][['T', 'team']]
def possession_start(T, team, period_start):
    lo = max(period_start, T - POSS_MAX)
    given = foul_given[(foul_given['team'] == team) & (foul_given['T'] < T) & (foul_given['T'] >= lo)]
    if len(given):
        lo = float(given['T'].max()) + 0.01            # not before its own last foul
    t0 = T
    for _, r in touch_df[(touch_df['T'] < T) & (touch_df['T'] >= lo)].iloc[::-1].iterrows():
        if r['team'] != team and (r['outcomeType'] == 'Successful' or r['type'] == 'Pass'):
            break
        t0 = float(r['T'])
    return t0
COUNTER_DUR, COUNTER_GAIN = 15.0, 25.0     # a counter: >= 25 m upfield in <= 15 s
for s_ in shots:
    if s_['goal']:
        s_['poss'] = possession_start(s_['T'], s_['team'], period_of(s_['T'])['start'])
    t0, x0 = chain_start(s_['T'], s_['team'])
    s_['chainT'] = round(t0, 1)
    # counter: WhoScored 'FastBreak', or the shooting side's chain went >= COUNTER_GAIN m upfield in <= COUNTER_DUR s
    gain = 0 if x0 is None else (s_['X'] - x0 if s_['team'] == 'home' else x0 - s_['X'])
    s_['counter'] = bool(s_['situation'] == 'FastBreak' or (s_['T'] - t0 <= COUNTER_DUR and gain >= COUNTER_GAIN))
for f in fouls:
    fouled = 'away' if f['team'] == 'home' else 'home'
    attack = f['team'] if f['offensive'] else fouled          # the side that had the ball
    t0, x0 = chain_start(f['T'], attack)
    gain = 0 if x0 is None else (f['X'] - x0 if attack == 'home' else x0 - f['X'])
    f['fouled'] = fouled
    f['attack'] = attack
    f['chainT'] = round(t0, 1)
    f['counter'] = bool(f['T'] - t0 <= COUNTER_DUR and gain >= COUNTER_GAIN)

# ---------------------------------------------------------------- set pieces (corners, free kicks), for the relief
setpieces = []
for _, r in df[df['type'] == 'Pass'].iterrows():
    q = str(r['qualifiers'])
    kind = 'corner' if 'CornerTaken' in q else 'freekick' if 'FreekickTaken' in q else None
    if kind is None:
        continue
    X, Y = to_pitch(r['team'], r['x'], r['y'])
    if pd.isna(r['endX']):
        X2, Y2 = X, Y
    else:
        X2, Y2 = to_pitch(r['team'], r['endX'], r['endY'])
    setpieces.append(dict(T=float(r['T']), team=r['team'], kind=kind, X=round(X, 2), Y=round(Y, 2), X2=round(X2, 2), Y2=round(Y2, 2)))

sh = df[df['isShot'] == True]
corners = df[(df['type'] == 'CornerAwarded') & (df['outcomeType'] == 'Successful')]
stats = dict(
    xg=[round(float(sh[sh['team'] == 'home']['xg'].sum()), 2), round(float(sh[sh['team'] == 'away']['xg'].sum()), 2)],
    shots=[int((sh['team'] == 'home').sum()), int((sh['team'] == 'away').sum())],
    corners=[int((corners['team'] == 'home').sum()), int((corners['team'] == 'away').sum())],
    cards=[sum(1 for c in cards if c['team'] == 'home'), sum(1 for c in cards if c['team'] == 'away')])

# ---------------------------------------------------------------- team identity (names, logos, colours)
# Read from <match>_match_info.csv (FotMob, written by the export script) when it is next to the CSV: the scoreboard
# shows team_name as it is in that file, with team_logo.
# Colour rules, so any pair of teams reads well on the dark night scene:
#   1. each cloth takes the team's FotMob dark-mode colour (light-mode colour when dark-mode is missing);
#   2. HSL lightness kept in [MIN_LIGHT, MAX_LIGHT]: a black or navy cloth would vanish in the night, a pure white one
#      would burn out under the lights;
#   3. when the two cloths are too close (CIE76 delta E < MIN_DELTA_E), the away side takes its other FotMob colour,
#      then the first fallback (#ecedf0 white, #e5383b red, #f2c230 yellow) far enough from the home colour.
# Without the file the previous defaults are kept (blue #4a74f2 / white #ecedf0) and the WhoScored names are shown.
MIN_LIGHT, MAX_LIGHT, MIN_DELTA_E = 0.45, 0.93, 25.0
FALLBACK_COLOURS = ['#ecedf0', '#e5383b', '#f2c230']

def _rgb(hexs):
    h = str(hexs).strip().lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if re.fullmatch(r'[0-9a-fA-F]{6}', h) else None

def _hex(rgb):
    return '#' + ''.join(f'{round(max(0, min(1, c)) * 255):02x}' for c in rgb)

def lift(hexs):
    """Rule 2: clamp the HSL lightness to [MIN_LIGHT, MAX_LIGHT], keeping hue and saturation."""
    import colorsys
    r, g, b = _rgb(hexs); hh, l, ss = colorsys.rgb_to_hls(r, g, b)
    return _hex(colorsys.hls_to_rgb(hh, min(max(l, MIN_LIGHT), MAX_LIGHT), ss))

def delta_e(a, b):
    """CIE76 colour difference between two hex colours (sRGB, D65)."""
    def lab(hexs):
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(hexs)]
        X = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
        Y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        Z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
        f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
        return 116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))
    return math.dist(lab(a), lab(b))

def _norm_team(s):
    import unicodedata
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower())

def team_identity():
    info_path = CSV.replace('_qualifiers_expanded.csv', '_match_info.csv')
    home = dict(name=HOME, display=HOME, color='#4a74f2', logo=None, source='default')
    away = dict(name=AWAY, display=AWAY, color='#ecedf0', logo=None, source='default')
    if not os.path.exists(info_path):
        print('team identity: no', os.path.basename(info_path), '-> default names / colours')
        return home, away
    info = pd.read_csv(info_path)
    def row_for(name, side):   # by name first (works with --home), else by FotMob side
        hit = info[info['team_name'].map(_norm_team) == _norm_team(name)]
        return (hit if len(hit) else info[info['side'] == side]).iloc[0]
    out = []
    for t, side in ((home, 'home'), (away, 'away')):
        r = row_for(t['name'], side)
        modes = [c for c in (r.get('color_darkMode'), r.get('color_lightMode')) if _rgb(c)]
        t.update(display=str(r['team_name']), logo=r.get('team_logo') if isinstance(r.get('team_logo'), str) else None,
                 fotmob_team_id=int(r['fotmob_team_id']) if pd.notna(r.get('fotmob_team_id')) else None, source=os.path.basename(info_path), fotmob_side=str(r['side']),
                 fotmob_colors=[str(c) for c in modes])
        if modes:
            t['color'] = lift(modes[0])
        out.append(t)
    h, a = out
    if delta_e(h['color'], a['color']) < MIN_DELTA_E:   # rule 3
        for c in [lift(c) for c in a['fotmob_colors'][1:]] + FALLBACK_COLOURS:
            if delta_e(h['color'], c) >= MIN_DELTA_E:
                print(f"team identity: {a['display']} colour {a['color']} too close to {h['color']} -> {c}")
                a['color'] = c; break
    h['contrast'] = a['contrast'] = round(delta_e(h['color'], a['color']), 1)
    return h, a

HOME_ID, AWAY_ID = team_identity()
print('team identity:', {k: (v['display'], v['color'], v['source']) for k, v in (('home', HOME_ID), ('away', AWAY_ID))})

data = dict(
    home=HOME_ID, away=AWAY_ID,
    periods=dict(firstHalfEnd=FIRST_HALF_END, secondHalfStart=SECOND_HALF_START, matchEnd=MATCH_END, list=PERIODS),
    shots=shots, subs=subs, cards=cards, fouls=fouls, setpieces=setpieces, prog=prog, tackles=tackles,
    momentum=dict(csv=mom_csv, fotmob=mom_fotmob), stats=stats)
# ---------------------------------------------------------------- images kept in the project
# Player photos and team logos are downloaded once into assets/media/ (3 tries each) and the 3D page uses the local
# copies: no network needed while rendering, and a short network failure can no longer leave a card without its photo.
# An image that cannot be downloaded keeps its FotMob URL.
def local_image(url, kind):
    if not isinstance(url, str) or not url.startswith('http'):
        return url
    import time, ssl, urllib.request
    try:
        import certifi; ctx = ssl.create_default_context(cafile=certifi.where())   # Python builds without a CA bundle
    except ImportError:
        ctx = ssl.create_default_context()
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', url.rsplit('/', 1)[-1])
    rel = f'assets/media/{kind}/{name}'
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                    body = r.read()
                if body[:4] != b'\x89PNG' and body[:3] != b'\xff\xd8\xff':
                    raise ValueError('not an image')
                open(path, 'wb').write(body)
                break
            except Exception as e:
                if attempt == 2:
                    print('image not downloaded, keeping the URL:', url, '-', e)
                    return url
                time.sleep(1 + attempt)
    return '../' + rel   # relative to fabric/index.html

missing = 0
for t in (data['home'], data['away']):
    t['logo'] = local_image(t.get('logo'), 'logos')
for item in [*data['shots'], *data['cards']]:
    pl = item.get('player')
    if isinstance(pl, dict) and pl.get('photo'):
        pl['photo'] = local_image(pl['photo'], 'players')
        missing += pl['photo'].startswith('http')
print('images: local copies in assets/media/' + (f' ({missing} kept as URL)' if missing else ''))

sys.path.insert(0, ROOT)
from pmd.slug import match_slug   # date + teams, e.g. 2026-10-14_manchester-city_vs_paris-saint-germain
MATCH_SLUG = match_slug(CSV)
os.makedirs(os.path.join(ROOT, 'fabric', 'data'), exist_ok=True)
js = 'window.MATCH = ' + json.dumps(data, ensure_ascii=False) + ';\n'
for out in (os.path.join(ROOT, 'fabric', 'data', MATCH_SLUG + '.js'), os.path.join(ROOT, 'fabric', 'data.js')):
    open(out, 'w').write(js)
print('match', MATCH_SLUG, '-> fabric/index.html?match=' + MATCH_SLUG)
print('wrote', out, 'shots', len(shots), 'goals', sum(s['goal'] for s in shots), 'subs', len(subs), 'stats', stats)
print('periods', data['periods'])
for s in shots:
    if s['goal']: print(s['label'], s['team'], s['player']['short'], s['X'], s['Y'], s['xg'], 'pen' if s['penalty'] else '', s['player']['photo'])
