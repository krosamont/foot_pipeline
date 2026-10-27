"""From the raw WhoScored + FotMob data to the event table used by the exports and the dashboard.

build_events() returns a namespace (dict) with the event table `df` (pitch metres, team / player info, dashboard xT,
progressive distance, short names, FotMob xG / xGOT joined on the shots) and the team variables the dashboard uses.
"""
import os
import re
import unicodedata

import numpy as np
import pandas as pd

from .config import XT_GRID_DASHBOARD_URL


def build_events(result, data, workdir, xt_grid_source=XT_GRID_DASHBOARD_URL):
    """`result` = WhoScored matchCentreData, `data` = FotMob matchDetails; intermediate CSVs are written to `workdir`."""

    def extract_data_from_dict(data):
        # load data from json
        events_dict = data["events"]
        teams_dict = {data['home']['teamId']: data['home']['name'],
                      data['away']['teamId']: data['away']['name']}
        players_dict = data["playerIdNameDictionary"]
        # create players dataframe
        players_home_df = pd.DataFrame(data['home']['players'])
        players_home_df["teamId"] = data['home']['teamId']
        players_away_df = pd.DataFrame(data['away']['players'])
        players_away_df["teamId"] = data['away']['teamId']
        players_df = pd.concat([players_home_df, players_away_df])
        players_ids = data["playerIdNameDictionary"]
        return events_dict, players_df, teams_dict

    events_dict, players_df, teams_dict = extract_data_from_dict(result)

    df = pd.DataFrame(events_dict)
    dfp = pd.DataFrame(players_df)

    # the CSV round trip is part of the processing (it adds the 'Unnamed: 0' row id used by the merges below)
    df.to_csv(os.path.join(workdir, 'EventData.csv'))
    df = pd.read_csv(os.path.join(workdir, 'EventData.csv'))
    dfp.to_csv(os.path.join(workdir, 'PlayerData.csv'))
    dfp = pd.read_csv(os.path.join(workdir, 'PlayerData.csv'))

    # Extract the 'displayName' value
    df['type'] = df['type'].str.extract(r"'displayName': '([^']+)")
    df['outcomeType'] = df['outcomeType'].str.extract(r"'displayName': '([^']+)")
    df['period'] = df['period'].str.extract(r"'displayName': '([^']+)")

    # Assign xT values
    df_base  = df
    dfxT = df_base.copy()
    dfxT = dfxT[~dfxT['qualifiers'].str.contains('Corner') & ~dfxT['qualifiers'].str.contains('ThrowIn')]
    dfxT = dfxT[(dfxT['type']=='Pass') & (dfxT['outcomeType']=='Successful')]

    xT = pd.read_csv(xt_grid_source, header=None)
    xT = np.array(xT)
    xT_rows, xT_cols = xT.shape

    dfxT['x1_bin_xT'] = pd.cut(dfxT['x'], bins=xT_cols, labels=False)
    dfxT['y1_bin_xT'] = pd.cut(dfxT['y'], bins=xT_rows, labels=False)
    dfxT['x2_bin_xT'] = pd.cut(dfxT['endX'], bins=xT_cols, labels=False)
    dfxT['y2_bin_xT'] = pd.cut(dfxT['endY'], bins=xT_rows, labels=False)

    dfxT['start_zone_value_xT'] = dfxT[['x1_bin_xT', 'y1_bin_xT']].apply(lambda x: xT[x.iloc[1]][x.iloc[0]], axis=1)
    dfxT['end_zone_value_xT'] = dfxT[['x2_bin_xT', 'y2_bin_xT']].apply(lambda x: xT[x.iloc[1]][x.iloc[0]], axis=1)

    dfxT['xT'] = dfxT['end_zone_value_xT'] - dfxT['start_zone_value_xT']
    columns_to_drop = ['id', 'eventId', 'minute', 'second', 'teamId', 'x', 'y', 'expandedMinute', 'period', 'type', 'outcomeType', 'qualifiers',
                       'satisfiedEventsTypes', 'isTouch', 'playerId', 'endX', 'endY', 'relatedEventId', 'relatedPlayerId', 'blockedX', 'blockedY',
                       'goalMouthZ', 'goalMouthY', 'isShot']
    dfxT.drop(columns=columns_to_drop, inplace=True)

    df = df.merge(dfxT, on='Unnamed: 0', how='left')
    # Creating another column for teamName
    df['teamName'] = df['teamId'].map(teams_dict)

    # Reshaping the data from 100x100 to 105x68
    # goalMouthY is already in the 0-68 pitch scale (goalposts at 30.34-37.66) — do NOT scale it
    df['x'] = df['x']*1.05
    df['y'] = df['y']*0.68
    df['endX'] = df['endX']*1.05
    df['endY'] = df['endY']*0.68

    columns_to_drop = ['Unnamed: 0','height', 'weight', 'age', 'isManOfTheMatch', 'field', 'stats', 'subbedInPlayerId', 'subbedOutPeriod', 'subbedOutExpandedMinute',
                       'subbedInPeriod', 'subbedInExpandedMinute', 'subbedOutPlayerId', 'teamId']
    dfp.drop(columns=columns_to_drop, inplace=True, errors='ignore')   # no 'subbed*' columns when WhoScored lists no substitution
    df = df.merge(dfp, on='playerId', how='left').query("period != 'PenaltyShootout'")

    # Calculating passing distance, to find out progressive pass
    df['pro'] = np.where((df['type'] == 'Pass') & (df['outcomeType'] == 'Successful') & (df['x'] > 42),
                                np.sqrt((105 - df['x'])**2 + (34 - df['y'])**2) - np.sqrt((105 - df['endX'])**2 + (34 - df['endY'])**2), 0)

    # Function to extract short names
    def get_short_name(full_name):
        if pd.isna(full_name):
            return full_name
        parts = full_name.split()
        if len(parts) == 1:
            return full_name  # No need for short name if there's only one word
        elif len(parts) == 2:
            return parts[0][0] + ". " + parts[1]
        else:
            return parts[0][0] + ". " + parts[1][0] + ". " + " ".join(parts[2:])

    # Applying the function to create 'shortName' column
    df['shortName'] = df['name'].apply(get_short_name)

    # ══════════════════════════════════════════════════════════════════════════════
    # FOTMOB → WHOSCORED  fuzzy shot join
    # ══════════════════════════════════════════════════════════════════════════════
    # Pourquoi fuzzy ?
    #   • Minutes: Fotmob = displayed time (46'), WhoScored = continuous clock (52')
    #     → (halftime-45) min offset in the 2nd half. The minute is NOT used.
    #   • Noms    : "Leandro Trossard" vs "L. Trossard"
    #   • Types   : "AttemptSaved" vs "SavedShot"
    #   Main key: Euclidean x/y distance (same 0-105 × 0-68 scale).
    # ══════════════════════════════════════════════════════════════════════════════
    def join_fotmob_shots(fotmob_data, ws_df):
        """Enrich WhoScored events with xG, xGOT, shot_type and situation
        from the Fotmob shotmap. Works as a LEFT JOIN: every original row
        of ws_df is kept."""

        WS_TO_FM = {
            "SavedShot"  : "AttemptSaved",
            "Goal"       : "Goal",
            "MissedShots": "Miss",
            "ShotOnPost" : "ShotOnPost",
        }

        def _norm(n):
            if pd.isna(n):
                return ""
            return re.sub(r"[^a-z ]", "", str(n).lower().strip())

        # ── 1. Fotmob shots ──────────────────────────────────────────────────────
        fm_raw = fotmob_data["content"]["shotmap"]["shots"]
        fm = pd.DataFrame([{
            "_fm_idx"          : i,
            "_fm_type"         : s["eventType"],
            "_fm_last"         : _norm(s.get("lastName", "")),
            "_fm_x"            : s["x"],
            "_fm_y"            : s["y"],
            "xg"               : s["expectedGoals"],
            "xgot"             : s["expectedGoalsOnTarget"],
            "shot_type"        : s["shotType"],
            "situation"        : s["situation"],
            "fm_is_blocked"    : s["isBlocked"],
            "fm_goal_crossed_y": s.get("goalCrossedY"),
            "fm_goal_crossed_z": s.get("goalCrossedZ"),
        } for i, s in enumerate(fm_raw)])

        # ── 2. WhoScored events (all rows kept) ──────────────────────────────────
        ws = ws_df.copy()

        # Prepare the temporary columns used for matching
        ws["_ws_type_fm"] = ws["type"].map(WS_TO_FM)

        # Safety net in case 'shortName' is missing or NaN on other events
        if "shortName" in ws.columns:
            ws["_ws_last"] = ws["shortName"].apply(
                lambda s: _norm(s.split(".")[-1]) if pd.notna(s) and "." in str(s)
                          else _norm(s)
            )
        else:
            ws["_ws_last"] = ""

        # ── 3. Fuzzy matching (x/y distance + type/name penalties) ────────────────
        DIST_THRESH = 14.0
        TYPE_PEN    = 6.0
        NAME_PEN    = 4.0

        used = set()
        result_cols = ["xg", "xgot", "shot_type", "situation",
                       "fm_is_blocked", "fm_goal_crossed_y", "fm_goal_crossed_z"]
        results = {c: [] for c in result_cols}

        for _, ws_row in ws.iterrows():
            # Not a shot: skip matching and add empty values
            if pd.isna(ws_row["_ws_type_fm"]):
                for c in result_cols:
                    results[c].append(np.nan if c in ("xg", "xgot") else None)
                continue

            # A shot: look for the best match
            best, best_fm_idx = np.inf, None

            for _, fm_row in fm.iterrows():
                if fm_row["_fm_idx"] in used:
                    continue

                dist = np.hypot(ws_row["x"] - fm_row["_fm_x"],
                                ws_row["y"] - fm_row["_fm_y"])

                if dist > DIST_THRESH:
                    continue

                type_pen = 0.0 if ws_row["_ws_type_fm"] == fm_row["_fm_type"] else TYPE_PEN
                fl, wl = fm_row["_fm_last"], ws_row["_ws_last"]
                name_pen = 0.0 if (fl and wl and (fl in wl or wl in fl)) else NAME_PEN
                score = dist + type_pen + name_pen

                if score < best:
                    best, best_fm_idx = score, fm_row["_fm_idx"]

            if best_fm_idx is not None:
                used.add(best_fm_idx)
                r = fm[fm["_fm_idx"] == best_fm_idx].iloc[0]
                for c in result_cols:
                    results[c].append(r[c])
            else:
                for c in result_cols:
                    results[c].append(np.nan if c in ("xg", "xgot") else None)

        # ── 4. Merge the results into the full DataFrame ──────────────────────────
        for c in result_cols:
            ws[c] = results[c]

        ws.drop(columns=["_ws_type_fm", "_ws_last"], inplace=True)

        # Completion statistics
        n_tirs_ws = ws["type"].isin(WS_TO_FM).sum()
        n_match = ws["xg"].notna().sum()
        print(f"[Fotmob join] {n_match}/{n_tirs_ws} shots enriched with xG/xGOT (out of {len(ws)} events)")

        return ws


    def _xg_size(subset, scale=700, base=80, min_s=80, max_s=900):
        """Scatter marker size proportional to the Fotmob xG."""
        return np.clip(subset["xg"].fillna(0.08) * scale + base, min_s, max_s)

    # Assigning values into some variables which will be used later
    hteamID = list(teams_dict.keys())[0]
    ateamID = list(teams_dict.keys())[1]
    hteamName= teams_dict[hteamID]
    ateamName= teams_dict[ateamID]

    file_header = f'{hteamName}_vs_{ateamName}'.replace('/', '-')   # 'Bodoe/Glimt' must not open a folder


    # hcol= col2
    # acol= col1

    homedf = df[(df['teamId']==hteamID)]
    awaydf = df[(df['teamId']==ateamID)]
    hxT = homedf['xT'].sum().round(2)
    axT = awaydf['xT'].sum().round(2)

    hgoal_count = len(homedf[(homedf['teamId']==hteamID) & (homedf['type']=='Goal') & (~homedf['qualifiers'].str.contains('OwnGoal'))])
    agoal_count = len(awaydf[(awaydf['teamId']==ateamID) & (awaydf['type']=='Goal') & (~awaydf['qualifiers'].str.contains('OwnGoal'))])
    hgoal_count = hgoal_count + len(awaydf[(awaydf['teamId']==ateamID) & (awaydf['type']=='Goal') & (awaydf['qualifiers'].str.contains('OwnGoal'))])
    agoal_count = agoal_count + len(homedf[(homedf['teamId']==hteamID) & (homedf['type']=='Goal') & (homedf['qualifiers'].str.contains('OwnGoal'))])

    df = join_fotmob_shots(data, df)

    return dict(locals())
