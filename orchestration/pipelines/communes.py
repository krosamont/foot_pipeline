"""Chemins et tâches partagés par les pipelines qui écrivent dans la base foot."""
from orchestration.runner import Tache

BASE = '~/data/foot.duckdb'
LECTURE = '~/data/lecture/foot.duckdb'   # même nom de fichier : les vues dbt visent le catalogue « foot »
PY = '~/data/foot_3d/.venv/bin/python'
DBT = '~/data/foot_3d/.venv/bin/dbt'
DUCKDB = '~/bin/duckdb'   # mémoire et threads limités dans les commandes : o2switch tue les processus trop gourmands


def charger_sources(**kw):
    """Nouveaux matchs -> tables brutes (z_raw). load_raw.py sort avec le code 3 quand il n'y a rien de nouveau (statut
    « rien »). Sous le verrou de run_missing.py (cron */15) pour ne pas lire un match en cours d'écriture."""
    return Tache('charger_sources', f'flock -w 3600 data/matches/.run.lock {PY} -u tools/load_raw.py',
                 dossier='~/data/foot_3d', code_rien=3, relances=2, attente_relance=300, delai_max=3600,
                 description='nouveaux matchs (JSON de data/matches/ en CSV) -> tables z_raw', **kw)


def nouveau_transfermarkt(table='transfermarkt_player', **kw):
    """Des fiches Transfermarkt chargées (tm.run load, depuis le Mac) après la dernière copie de lecture ? Code 3 (statut
    « rien ») sinon : sans cette tâche, un chargement Transfermarkt sans nouveau match ne relançait pas dbt."""
    return Tache('nouveau_transfermarkt',
                 f'n=$({DUCKDB} -readonly -noheader -list {BASE} -c "select count(*) from z_raw.{table} '
                 f'where epoch(_loaded_at) > $(stat -c %Y {LECTURE} 2>/dev/null || echo 0)") && [ "$n" -gt 0 ] || exit 3',
                 code_rien=3, description='fiches Transfermarkt chargées depuis la dernière copie de lecture', **kw)


def dbt_build(**kw):
    """dbt build de foot_db : vues a_staging, tables b_intermediate et c_marts (incrémentales : seuls les matchs chargés
    depuis le passage précédent sont recalculés), tests."""
    return Tache('dbt_build', f'DBT={DBT} scripts/dbt_build.sh', dossier='~/data/foot_db', relances=1, delai_max=3600,
                 description='a_staging (vues), b_intermediate et c_marts (tables incrémentales), tests', **kw)


def copie_lecture(**kw):
    """Copie de la base pour la page web en lecture seule, remplacée d'un coup (mv) : la page n'est jamais coupée."""
    return Tache('copie_lecture',
                 f'mkdir -p ~/data/lecture && {DUCKDB} {BASE} -c "CHECKPOINT" && cp {BASE} {LECTURE}.tmp && '
                 f'mv -f {LECTURE}.tmp {LECTURE} && ls -la {LECTURE}',
                 description='copie de la base pour la page web en lecture seule (~/data/lecture/foot.duckdb)', **kw)
