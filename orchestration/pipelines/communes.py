"""Chemins et tâches partagés par les pipelines qui écrivent dans la base foot."""
from orchestration.runner import Tache

BASE = '~/data/foot.duckdb'
LECTURE = '~/data/lecture/foot.duckdb'   # même nom de fichier : les vues dbt visent le catalogue « foot »
PY = '~/data/foot_3d/.venv/bin/python'
DUCKDB = '~/bin/duckdb'   # mémoire et threads limités dans les commandes : o2switch tue les processus trop gourmands


def charger_sources(**kw):
    """Nouveaux matchs -> tables raw. to_bronze.py sort avec le code 3 quand il n'y a rien de nouveau (statut « rien »).
    Sous le verrou de run_missing.py (cron */15) pour ne pas lire un match en cours d'écriture."""
    return Tache('charger_sources', f'flock -w 3600 data/matches/.run.lock {PY} -u tools/to_bronze.py',
                 dossier='~/data/foot_3d', code_rien=3, relances=2, attente_relance=300, delai_max=3600,
                 description='nouveaux matchs (fichiers de data/matches/) -> tables raw', **kw)


def copie_lecture(**kw):
    """Copie de la base pour la page web en lecture seule, remplacée d'un coup (mv) : la page n'est jamais coupée."""
    return Tache('copie_lecture',
                 f'mkdir -p ~/data/lecture && {DUCKDB} {BASE} -c "CHECKPOINT" && cp {BASE} {LECTURE}.tmp && '
                 f'mv -f {LECTURE}.tmp {LECTURE} && ls -la {LECTURE}',
                 description='copie de la base pour la page web en lecture seule (~/data/lecture/foot.duckdb)', **kw)
