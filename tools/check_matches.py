"""Check that every match already played is everywhere it should be, and send an e-mail when it is not.

For each match of the FotMob calendars of the current season (data/fixtures/<competition>_<season>.csv) whose kick-off
is more than --after-hours ago (default 6: the 4 h before it is fetched + 2 h for the fetch itself), not cancelled:
  1. it has a WhoScored id (data/fixtures/whoscored_fixtures.csv, whoscored_schedule_*, whoscored_links_*);
  2. it was fetched (data/matches/<competition>_<season>/<id>_.../ with its exports);
  3. it is on the website (matches.json of ~/data-workers.com/projet/foot_3d/);
  4. it is in the database: in a_staging (a_staging.stg_whoscored_match_status) and in c_marts (c_marts.fct_team_match, so the dbt build
     after its load went through).
When something is missing, an e-mail goes to --to (sendmail); the same list is sent again only after 20 h (so once per evening run), and a short
"back to normal" e-mail follows when everything is there again (state in data/matches/alert_state.json).

    python tools/check_matches.py                  (check, e-mail when needed)
    python tools/check_matches.py --dry-run        (only print the report)
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import warnings  # noqa: E402

import pandas as pd  # noqa: E402

warnings.filterwarnings('ignore', category=DeprecationWarning)   # numpy 'generic' timedelta notice from pandas, harmless

from pmd.fixtures import LEAGUES  # noqa: E402

FIXTURES = os.path.join(ROOT, 'data', 'fixtures')
MATCHES = os.path.join(ROOT, 'data', 'matches')
SITE = os.path.expanduser('~/data-workers.com/projet/foot_3d/matches.json')
STATE = os.path.join(MATCHES, 'alert_state.json')
TO = 'krosamont@data-workers.com'
FROM = 'foot_3d <noreply@data-workers.com>'
SENDMAIL = '/usr/sbin/sendmail'


def current_season():
    """Latest season with a FotMob calendar, as '2026-2027'."""
    tags = {os.path.basename(p).rsplit('_', 1)[1][:-4] for slug in LEAGUES for p in glob.glob(os.path.join(FIXTURES, f'{slug}_20??-20??.csv'))}
    return max(tags)


def report(season, after_hours):
    """List of problems (one line each) for the matches of `season` played more than `after_hours` ago."""
    now = pd.Timestamp.now(tz='UTC')
    files = [os.path.join(FIXTURES, 'whoscored_fixtures.csv')] + glob.glob(os.path.join(FIXTURES, 'whoscored_schedule_*.csv')) \
        + glob.glob(os.path.join(FIXTURES, 'whoscored_links_*.csv'))
    pairs = pd.concat([pd.read_csv(f) for f in files if os.path.exists(f)], ignore_index=True).dropna(subset=['fotmob_match_id'])
    ws_of = dict(zip(pairs['fotmob_match_id'].astype(int), pairs['whoscored_match_id'].astype(int)))
    fetched = {int(os.path.basename(os.path.normpath(d)).split('_', 1)[0]) for d in glob.glob(os.path.join(MATCHES, '*', '*', ''))
               if glob.glob(os.path.join(d, '*_qualifiers_expanded.csv'))}
    site = {m.get('match_id') for m in json.load(open(SITE))} if os.path.exists(SITE) else set()
    in_raw, in_gold, md_error = motherduck(season)
    failed_path = os.path.join(MATCHES, 'failed.csv')
    last_error = pd.read_csv(failed_path).drop_duplicates('whoscored_match_id', keep='last').set_index('whoscored_match_id')['error'] \
        if os.path.exists(failed_path) else pd.Series(dtype=str)

    problems, played = [], 0
    for slug, (_, name) in LEAGUES.items():
        path = os.path.join(FIXTURES, f'{slug}_{season}.csv')
        if not os.path.exists(path):
            continue
        cal = pd.read_csv(path)
        ko = pd.to_datetime(cal['date_utc'], utc=True, format='ISO8601')
        past = cal[(ko <= now - pd.Timedelta(hours=after_hours)) & (cal['cancelled'] != True)]   # noqa: E712
        played += len(past)
        for _, m in past.iterrows():
            what = f"{name} · {pd.Timestamp(m['date_utc']).strftime('%d/%m %H:%M')} UTC · {m['home']} - {m['away']} (FotMob {int(m['match_id'])}"
            ws = ws_of.get(int(m['match_id']))
            if ws is None:
                problems.append(f'{what}) : pas d\'identifiant WhoScored (ajouter un export dans data/fixtures/sources/)')
                continue
            what += f', WhoScored {ws})'
            if ws not in fetched:
                err = last_error.get(ws)
                problems.append(f'{what} : pas récupéré' + (f' (dernière erreur : {str(err)[:120]})' if isinstance(err, str) else ''))
            elif ws not in site:
                problems.append(f'{what} : récupéré mais pas publié sur le site')
            elif md_error is None and ws not in in_raw:
                problems.append(f'{what} : absent de la base (a_staging), voir ~/data/pipelines/logs/')
            elif md_error is None and ws not in in_gold:
                problems.append(f'{what} : dans MotherDuck (raw) mais pas en gold, voir data/matches/dbt.log')
    if md_error is not None:
        problems.append(f'MotherDuck : lecture impossible ({md_error[:120]})')
    return played, problems


def motherduck(season):
    """WhoScored ids of `season` in the database: a_staging (stg_whoscored_match_status) and c_marts (fct_team_match), and the error
    if MotherDuck could not be read."""
    try:
        import duckdb
        con = duckdb.connect(os.environ.get('FOOT_DB', os.path.expanduser('~/data/foot.duckdb')), read_only=True)
        ids = lambda sql: {int(r[0]) for r in con.execute(sql, [season]).fetchall()}
        return (ids('select distinct match_id from a_staging.stg_whoscored_match_status where season = ?'),
                ids('select distinct match_id from c_marts.fct_team_match where season = ?'), None)
    except Exception as e:   # noqa: BLE001  (reported in the e-mail rather than crashing the check)
        return set(), set(), str(e)


def send(subject, body, to):
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = FROM, to, subject
    msg.set_content(body)
    subprocess.run([SENDMAIL, '-t', '-oi'], input=msg.as_bytes(), check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--season', help='season like 2026-2027 (default: the latest one with a FotMob calendar)')
    ap.add_argument('--after-hours', type=float, default=6)
    ap.add_argument('--to', default=TO)
    ap.add_argument('--dry-run', action='store_true', help='print the report, send nothing')
    a = ap.parse_args(argv)
    season = a.season or current_season()
    played, problems = report(season, a.after_hours)
    now = datetime.now(timezone.utc)
    print(f'[check] {now:%Y-%m-%d %H:%M} UTC, saison {season}: {played} matchs joués, {len(problems)} problème(s)', flush=True)
    for p in problems:
        print('   ', p, flush=True)
    if a.dry_run:
        return 0
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    signature = hashlib.md5('\n'.join(problems).encode()).hexdigest()
    if problems:
        last = datetime.fromisoformat(state['sent_at']) if state.get('sent_at') else None
        if state.get('signature') != signature or not last or (now - last).total_seconds() > 20 * 3600:
            body = (f'Bonjour,\n\nLa vérification automatique de foot_3d ({now:%d/%m/%Y %H:%M} UTC) a trouvé {len(problems)} problème(s) '
                    f'sur les {played} matchs déjà joués de la saison {season} :\n\n' + '\n'.join(f'- {p}' for p in problems)
                    + '\n\nJournaux sur le serveur : ~/data/foot_3d/data/matches/run.log, failed.csv, bronze.log et dbt.log.\n'
                    'Ce contrôle passe le mardi, mercredi, samedi, dimanche et lundi à 23 h 30.\n')
            send(f'[foot_3d] {len(problems)} match(s) manquant(s) - saison {season}', body, a.to)
            state = {'signature': signature, 'sent_at': now.isoformat(), 'problems': len(problems)}
            print(f'[check] e-mail envoyé à {a.to}', flush=True)
    elif state.get('problems'):
        send(f'[foot_3d] tout est revenu en ordre - saison {season}',
             f'Bonjour,\n\nLes {played} matchs déjà joués de la saison {season} sont maintenant tous récupérés, publiés et dans MotherDuck.\n', a.to)
        state = {'signature': None, 'sent_at': None, 'problems': 0}
        print(f'[check] e-mail "tout est revenu en ordre" envoyé à {a.to}', flush=True)
    with open(STATE, 'w') as f:
        json.dump(state, f)
    return 0


if __name__ == '__main__':
    sys.exit(main())
