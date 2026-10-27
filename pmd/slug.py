"""Name of a match in the 3D (file fabric/data/<slug>.js, page fabric/index.html?match=<slug>): its date and the two
teams, e.g. 2026-10-14_manchester-city_vs_paris-saint-germain. Shared by tools/build_data.py and pmd.make3d."""
import os
import re
import unicodedata

import pandas as pd


def _part(text):
    """'Paris Saint-Germain' -> 'paris-saint-germain' (ASCII, lower case, hyphens)."""
    t = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')


def match_slug(csv_path):
    """Date + home + away from <match>_match_info.csv next to the CSV; without it, the CSV's own name."""
    info_path = csv_path.replace('_qualifiers_expanded.csv', '_match_info.csv')
    if os.path.exists(info_path):
        info = pd.read_csv(info_path).set_index('side')
        date = str(info['matchTimeUTCDate'].iloc[0])[:10] if 'matchTimeUTCDate' in info else ''
        teams = f"{_part(info.loc['home', 'team_name'])}_vs_{_part(info.loc['away', 'team_name'])}"
        return f'{date}_{teams}' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else teams
    return re.sub(r'[^A-Za-z0-9_-]+', '_', os.path.basename(csv_path).replace('_qualifiers_expanded.csv', ''))
