"""The CSV exports of a match (any match).

  1. every qualifier becomes its own column (PassEndX/PassEndY converted to metres)
  2. every coordinate pair gets its zone (1-18), its phase zone and its channel
  3. distance from (x, y) to (endX, endY), and the carry before each pass
  4. xT of every pass / carry and the per-minute xT momentum            -> <match>_momentum.csv
  5. FotMob player id of every event; match information (teams, logos,
     colours, stadium...)                                                -> <match>_match_info.csv
  + the enriched event table                                             -> <match>_qualifiers_expanded.csv
  + FotMob's 'general' block                                             -> <match>_general.json

Coordinate frame (WhoScored/Opta, in metres, from the acting team's point of view):
  x: 0 -> 105, from the team's own goal to the opponent goal
  y: 0 -> 68,  from the right touchline (y = 0) to the left touchline (y = 68)
"""
import ast
import json
import os

import numpy as np
import pandas as pd

PITCH_LENGTH = 105.0   # m
PITCH_WIDTH = 68.0     # m
PENALTY_BOX_WIDTH = 40.32   # m (width of the penalty box)
SIX_YARD_BOX_WIDTH = 18.32  # m (width of the six-yard box)
PHASE_ZONES = ['Build', 'Progress', 'Penetrate', 'Finish']
MAX_CARRY_GAP_S = 20.0      # s, max time between reception and pass to count as one carry


def expand_qualifiers(events_df, col='qualifiers'):
    """Turn every qualifier found in column `col` into a column of its own.

    - qualifier with a value (e.g. PassEndX = '77.9', Zone = 'Right') -> that value,
      converted to a number when the whole column is numeric;
    - qualifier without a value (e.g. Longball, KeyPass)             -> True;
    - qualifier missing from the event                                 -> empty (NaN).
    PassEndX / PassEndY come on a 0-100 scale and are converted to metres
    (x 1.05 and x 0.68). The original `col` column is kept.
    """
    def parse(q):
        if isinstance(q, list):
            items = q
        elif isinstance(q, str) and q.strip():
            try:
                items = ast.literal_eval(q)
            except (ValueError, SyntaxError):
                return {}
        else:
            return {}
        row = {}
        for item in items:
            name = item.get('type', {}).get('displayName')
            if name:
                row[name] = item.get('value', True)
        return row

    qdf = pd.DataFrame([parse(q) for q in events_df[col]], index=events_df.index)

    # text values -> numbers, only when every value of the column is numeric
    for c in qdf.columns:
        if qdf[c].dropna().map(lambda v: isinstance(v, str)).all():
            num = pd.to_numeric(qdf[c], errors='coerce')
            if num.notna().sum() == qdf[c].notna().sum():
                qdf[c] = num

    # pass destination: 0-100 scale -> metres (105 x 68 pitch)
    if 'PassEndX' in qdf.columns:
        qdf['PassEndX'] = qdf['PassEndX'] * 1.05
    if 'PassEndY' in qdf.columns:
        qdf['PassEndY'] = qdf['PassEndY'] * 0.68

    # prefix with q_ when the name is already taken by an existing column
    qdf.columns = [c if c not in events_df.columns else f'q_{c}' for c in qdf.columns]
    return pd.concat([events_df, qdf], axis=1)


def pitch_zone(x, y):
    """Zone 1-18: 6 bands along the length (17.5 m) x 3 lanes across the width (22.67 m).

        left     1   4   7   10   13   16
        centre   2   5   8   11   14   17   -> opponent goal
        right    3   6   9   12   15   18

    Zones 1-3: band in front of the team's own goal; zones 16-18: band in front of the opponent goal.
    """
    if pd.isna(x) or pd.isna(y):
        return np.nan
    band = min(int(x // (PITCH_LENGTH / 6)), 5)           # 0 (own goal) -> 5 (opponent goal)
    lane = 2 - min(int(y // (PITCH_WIDTH / 3)), 2)        # 0 = left, 1 = centre, 2 = right
    return band * 3 + lane + 1


def pitch_phase(x):
    """Phase zone: 4 equal parts of 26.25 m (1.5 bands of zones each).

        Build     = zones 1-3          + first half of 4-6     (0     - 26.25 m)
        Progress  = second half of 4-6 + zones 7-9             (26.25 - 52.5 m)
        Penetrate = zones 10-12        + first half of 13-15   (52.5  - 78.75 m)
        Finish    = second half of 13-15 + zones 16-18         (78.75 - 105 m)
    """
    if pd.isna(x):
        return np.nan
    return PHASE_ZONES[min(int(x // (PITCH_LENGTH / 4)), 3)]


def pitch_channel(y):
    """Channel: 5 lanes along the pitch, bounded by the edges of the two boxes.

        Wide Left        : 54.16 - 68 m    (outside the penalty box)
        Half Space Left  : 43.16 - 54.16 m (between penalty-box edge and six-yard-box edge)
        Central          : 24.84 - 43.16 m (width of the six-yard box)
        Half Space Right : 13.84 - 24.84 m
        Wide Right       : 0     - 13.84 m
    """
    if pd.isna(y):
        return np.nan
    d = y - PITCH_WIDTH / 2                                # > 0: left side
    if abs(d) <= SIX_YARD_BOX_WIDTH / 2:
        return 'Central'
    side = 'Left' if d > 0 else 'Right'
    if abs(d) <= PENALTY_BOX_WIDTH / 2:
        return f'Half Space {side}'
    return f'Wide {side}'


def add_location_columns(events_df, xcol, ycol, tag):
    """Add zone_<tag>, phaseZone_<tag> and channel_<tag> for the coordinate pair (xcol, ycol)."""
    xs, ys = events_df[xcol], events_df[ycol]
    events_df[f'zone_{tag}'] = pd.array([pitch_zone(x, y) for x, y in zip(xs, ys)], dtype='Int64')
    events_df[f'phaseZone_{tag}'] = [pitch_phase(x) for x in xs]
    events_df[f'channel_{tag}'] = [pitch_channel(y) for y in ys]
    return events_df


def add_distance_column(events_df):
    """Add : straight-line distance in metres from (x, y) to (endX, endY).

    Empty (NaN) when the event has no end point (only passes, clearances... have one).
    """
    events_df['distance_start_end'] = np.hypot(events_df['endX'] - events_df['x'],
                                               events_df['endY'] - events_df['y'])
    return events_df


def add_carry_columns(events_df):
    """Estimate how far the player carried the ball before each pass.

    WhoScored does not log carries, so they are rebuilt from consecutive events:
      - reception point = where the previous successful team-mate pass ended (endX, endY),
        or where the player won the ball himself (ball recovery, interception, tackle...);
      - the player's own touches in between (take-ons, ball touches) keep the same reception point;
      - carry = straight line from the reception point to where the pass is played (x, y).
    New columns (pass rows only):
      carry_startX, carry_startY : estimated reception point (m)
      carry_distance             : length of the carry (m)
      carry_progress             : forward gain towards the opponent goal (m, negative = backwards)
    """
    df_ = events_df
    cols = ['carry_startX', 'carry_startY', 'carry_distance', 'carry_progress']
    out = {c: [np.nan] * len(df_) for c in cols}
    t = df_['minute'] * 60 + df_['second'].fillna(0)

    recv = None   # (player, team, period, x, y, time) of the current ball holder
    for i, (idx, ev) in enumerate(df_.iterrows()):
        if not bool(ev.get('isTouch', False)) or pd.isna(ev['x']):
            continue
        player, team, period = ev['playerId'], ev['teamId'], ev['period']
        if (recv is not None and recv[0] == 'receiver' and recv[1] == team and recv[2] == period
                and t.iloc[i] - recv[5] <= MAX_CARRY_GAP_S):
            # first touch of the team-mate who received the pass: he holds the ball from its end point
            recv = (player, team, period, recv[3], recv[4], t.iloc[i])
        same_holder = (recv is not None and recv[0] == player and recv[1] == team
                       and recv[2] == period and t.iloc[i] - recv[5] <= MAX_CARRY_GAP_S)
        start = (recv[3], recv[4]) if same_holder else (ev['x'], ev['y'])

        if ev['type'] == 'Pass':
            dx, dy = ev['x'] - start[0], ev['y'] - start[1]
            out['carry_startX'][i], out['carry_startY'][i] = start
            out['carry_distance'][i] = float(np.hypot(dx, dy))
            out['carry_progress'][i] = float(dx)
            # a completed pass hands the ball to a team-mate at its end point
            if ev['outcomeType'] == 'Successful' and not pd.isna(ev['endX']):
                recv = ('receiver', team, period, ev['endX'], ev['endY'], t.iloc[i])
            else:
                recv = None
            continue

        if same_holder:
            recv = (player, team, period, recv[3], recv[4], recv[5])
        elif ev['outcomeType'] == 'Successful':
            # ball won / kept by this player at this spot
            recv = (player, team, period, ev['x'], ev['y'], t.iloc[i])
        else:
            recv = None

    for c in cols:
        events_df[c] = out[c]
    return events_df


# -----------------------------------------------------------------------------
# xT and momentum, recomputed from the events (method of AKapich's WorldCup_App):
#   xT of a move  = xT(zone where it ends) - xT(zone where it starts), on a 12 x 8 grid laid on the 105 x 68 pitch
#   moves         = completed passes (start -> PassEnd) and carries (reception point -> pass origin)
#   momentum      = for each minute, per team: sum over the last MOMENTUM_WINDOW minutes of the team's best move of
#                   each minute (xT clipped to [0, XT_CLIP]) weighted by exp(-MOMENTUM_DECAY * age);
#                   home minus away, then a gaussian smoothing (MOMENTUM_SIGMA minutes)
# -----------------------------------------------------------------------------
XT_GRID_URL = 'https://raw.githubusercontent.com/AKapich/WorldCup_App/main/app/xT_Grid.csv'
XT_CLIP = 0.1
MOMENTUM_WINDOW = 4
MOMENTUM_DECAY = 0.25
MOMENTUM_SIGMA = 1


def load_xt_grid(source=XT_GRID_URL):
    """xT grid as a (rows, cols) array; rows run across the width, cols along the length (toward the opponent goal)."""
    return np.array(pd.read_csv(source, header=None), dtype=float)


def xt_zone_value(grid, x, y):
    """xT value of the grid cell holding the point (x, y) in metres; NaN when the point is missing."""
    if pd.isna(x) or pd.isna(y):
        return np.nan
    rows, cols = grid.shape
    ix = min(max(int(x / PITCH_LENGTH * cols), 0), cols - 1)
    iy = min(max(int(y / PITCH_WIDTH * rows), 0), rows - 1)
    return grid[iy, ix]


def add_xt_columns(events_df, grid):
    """Add `xT_pass` (completed passes) and `xT_carry` (carry before a pass), both in xT units.

    Needs the carry columns (add_carry_columns) for xT_carry.
    """
    is_pass = (events_df['type'] == 'Pass') & (events_df['outcomeType'] == 'Successful') & events_df['endX'].notna()
    events_df['xT_pass'] = [xt_zone_value(grid, ex, ey) - xt_zone_value(grid, x, y) if ok else np.nan
                            for ok, x, y, ex, ey in zip(is_pass, events_df['x'], events_df['y'], events_df['endX'], events_df['endY'])]
    has_carry = (events_df['type'] == 'Pass') & (events_df['carry_distance'] > 0)
    events_df['xT_carry'] = [xt_zone_value(grid, x, y) - xt_zone_value(grid, cx, cy) if ok else np.nan
                             for ok, x, y, cx, cy in zip(has_carry, events_df['x'], events_df['y'], events_df['carry_startX'], events_df['carry_startY'])]
    return events_df


def compute_momentum(events_df, home_team, away_team):
    """Per-minute xT momentum (home - away), on the continuous match clock (`expandedMinute`)."""
    from scipy.ndimage import gaussian_filter1d
    moves = pd.concat([
        events_df.loc[events_df['xT_pass'].notna(), ['teamName', 'expandedMinute', 'xT_pass']].rename(columns={'xT_pass': 'xT'}),
        events_df.loc[events_df['xT_carry'].notna(), ['teamName', 'expandedMinute', 'xT_carry']].rename(columns={'xT_carry': 'xT'}),
    ])
    moves['xT_clipped'] = moves['xT'].clip(0, XT_CLIP)
    best = moves.groupby(['teamName', 'expandedMinute'])['xT_clipped'].max()
    minutes = np.arange(int(events_df['expandedMinute'].min()), int(events_df['expandedMinute'].max()) + 1)

    def weighted(team, m):
        if team not in best.index.get_level_values(0):
            return 0.0
        b = best.loc[team]
        recent = b[(b.index <= m) & (b.index > m - MOMENTUM_WINDOW)]
        return float(np.sum(np.exp(-MOMENTUM_DECAY * (m - recent.index.values)) * recent.values))

    mom = np.array([weighted(home_team, m) - weighted(away_team, m) for m in minutes])
    period = events_df.groupby('expandedMinute')['period'].first().reindex(minutes).ffill().bfill()
    return pd.DataFrame({'expandedMinute': minutes, 'period': period.values, 'momentum': mom,
                         'smoothed_momentum': gaussian_filter1d(mom, sigma=MOMENTUM_SIGMA)})


# -----------------------------------------------------------------------------
# FotMob ids and match information (from the FotMob matchDetails JSON held in `data`)
#   player photo: https://images.fotmob.com/image_resources/playerimages/<fotmob_player_id>.png
#   team logo:    https://images.fotmob.com/image_resources/logo/teamlogo/<fotmob_team_id>.png
# -----------------------------------------------------------------------------
FOTMOB_PLAYER_PHOTO = 'https://images.fotmob.com/image_resources/playerimages/{}.png'
FOTMOB_TEAM_LOGO = 'https://images.fotmob.com/image_resources/logo/teamlogo/{}.png'


def _norm_name(n):
    """Lower-case name without accents, dots or hyphens (for matching WhoScored and FotMob names)."""
    import unicodedata
    n = unicodedata.normalize('NFKD', str(n)).encode('ascii', 'ignore').decode().lower()
    return ' '.join(n.replace('.', ' ').replace('-', ' ').split())


def add_fotmob_player_ids(events_df, fotmob_data, home_team):
    """Add `fotmob_player_id`: the FotMob id of the event's player (empty for team events).

    Players are taken from the FotMob line-ups (starters, substitutes, unavailable). Matching, per team:
    shirt number first (WhoScored `shirtNo`), then the full name, then the last name (accents ignored).
    `home_team` is the WhoScored name of the home side (FotMob's lineup 'homeTeam').
    """
    lineup = fotmob_data.get('content', {}).get('lineup', {}) or {}
    by_shirt, by_name, by_last = {}, {}, {}
    for side in ('homeTeam', 'awayTeam'):
        team = lineup.get(side) or {}
        for p in (team.get('starters') or []) + (team.get('subs') or []) + (team.get('unavailable') or []):
            pid = p.get('id')
            if pid is None:
                continue
            if p.get('shirtNumber') not in (None, ''):
                by_shirt[(side, str(p['shirtNumber']))] = pid
            by_name[(side, _norm_name(p.get('name', '')))] = pid
            last = p.get('lastName') or str(p.get('name', '')).split(' ')[-1]
            by_last.setdefault((side, _norm_name(last)), pid)

    def find(team_name, shirt, name):
        if pd.isna(name):
            return pd.NA
        side = 'homeTeam' if team_name == home_team else 'awayTeam'
        if not pd.isna(shirt) and (side, str(int(shirt))) in by_shirt:
            return by_shirt[(side, str(int(shirt)))]
        key = _norm_name(name)
        if (side, key) in by_name:
            return by_name[(side, key)]
        return by_last.get((side, key.split(' ')[-1]), pd.NA)

    events_df['fotmob_player_id'] = pd.array([find(t, sh, n) for t, sh, n in
                                              zip(events_df['teamName'], events_df['shirtNo'], events_df['name'])], dtype='Int64')
    return events_df


def build_match_info(fotmob_data):
    """One row per team with the match context from FotMob: teams, logos, colours, date, competition, stadium."""
    g = fotmob_data.get('general', {}) or {}
    info = (fotmob_data.get('content', {}).get('matchFacts', {}) or {}).get('infoBox', {}) or {}
    stadium = info.get('Stadium', {}) or {}
    colors = g.get('teamColors', {}) or {}
    header_teams = (fotmob_data.get('header', {}) or {}).get('teams', []) or []
    rows = []
    for k, side in enumerate(('home', 'away')):
        team = g.get(f'{side}Team', {}) or {}
        head = header_teams[k] if k < len(header_teams) else {}
        tid = team.get('id', head.get('id'))
        rows.append({
            'matchId': g.get('matchId'), 'side': side, 'team_name': team.get('name', head.get('name')), 'fotmob_team_id': tid,
            'score': head.get('score'),
            'team_logo': FOTMOB_TEAM_LOGO.format(tid) if tid is not None else None, 'team_logo_small': head.get('imageUrl'),
            'color_lightMode': (colors.get('lightMode') or {}).get(side), 'color_darkMode': (colors.get('darkMode') or {}).get(side),
            'font_lightMode': (colors.get('fontLightMode') or {}).get(side), 'font_darkMode': (colors.get('fontDarkMode') or {}).get(side),
            'matchTimeUTC': g.get('matchTimeUTC'), 'matchTimeUTCDate': g.get('matchTimeUTCDate'),
            'leagueName': g.get('leagueName'), 'leagueRoundName': g.get('leagueRoundName'), 'gender': g.get('gender'),
            'stadium': stadium.get('name'), 'city': stadium.get('city'), 'country': stadium.get('country'),
            'lat': stadium.get('lat'), 'long': stadium.get('long'), 'capacity': stadium.get('capacity'), 'surface': stadium.get('surface'),
            'attendance': info.get('Attendance'), 'referee': (info.get('Referee') or {}).get('text'),
        })
    return pd.DataFrame(rows)


def build_players(fotmob_data):
    """One row per player of the FotMob line-ups (starters, substitutes): id, name, team, shirt, age, country, club, photo."""
    lineup = (fotmob_data.get('content', {}) or {}).get('lineup', {}) or {}
    rows = []
    for side in ('home', 'away'):
        team = lineup.get(f'{side}Team', {}) or {}
        for role in ('starters', 'subs'):
            for p in team.get(role) or []:
                pid = p.get('id')
                rows.append({'fotmob_player_id': pid, 'name': p.get('name'), 'side': side, 'team_name': team.get('name'),
                             'role': role[:-1], 'shirt': p.get('shirtNumber'), 'age': p.get('age'), 'country': p.get('countryName'),
                             'club': p.get('primaryTeamName'),   # given for national teams only
                             'photo': FOTMOB_PLAYER_PHOTO.format(pid) if pid is not None else None})
    return pd.DataFrame(rows, columns=['fotmob_player_id', 'name', 'side', 'team_name', 'role', 'shirt', 'age', 'country', 'club', 'photo'])


# coordinate pairs to locate:
#   start   = where the action starts  (x, y)
#   end     = where the action ends    (endX, endY)
#   passEnd = pass destination         (PassEndX, PassEndY)
LOCATION_PAIRS = [('x', 'y', 'start'),
                  ('endX', 'endY', 'end'),
                  ('PassEndX', 'PassEndY', 'passEnd')]


def build_exports(df, fotmob, home_name, away_name, xt_grid_source=XT_GRID_URL):
    """Enriched event table, per-minute momentum and match information, from the event table `df` and FotMob JSON."""
    df_export = expand_qualifiers(df)
    for xcol, ycol, tag in LOCATION_PAIRS:
        if xcol in df_export.columns and ycol in df_export.columns:
            df_export = add_location_columns(df_export, xcol, ycol, tag)
    df_export = add_distance_column(df_export)
    df_export = add_carry_columns(df_export)
    df_export = add_xt_columns(df_export, load_xt_grid(xt_grid_source))
    momentum_df = compute_momentum(df_export, home_name, away_name)
    df_export = add_fotmob_player_ids(df_export, fotmob, home_name)
    match_info_df = build_match_info(fotmob)

    return df_export, momentum_df, match_info_df


def write_exports(out_dir, file_header, df_export, momentum_df, match_info_df, fotmob):
    """Write the five export files; returns their paths."""
    paths = [os.path.join(out_dir, f'{file_header}_qualifiers_expanded.csv'), os.path.join(out_dir, f'{file_header}_momentum.csv'),
             os.path.join(out_dir, f'{file_header}_match_info.csv'), os.path.join(out_dir, f'{file_header}_general.json')]
    df_export.to_csv(paths[0])
    momentum_df.to_csv(paths[1], index=False)
    match_info_df.to_csv(paths[2], index=False)
    with open(paths[3], 'w') as f:
        f.write(json.dumps(fotmob['general'], indent=4))
    paths.append(os.path.join(out_dir, f'{file_header}_players.csv'))   # line-ups, read by the 3D (tools/build_data.py)
    build_players(fotmob).to_csv(paths[4], index=False)
    return paths
