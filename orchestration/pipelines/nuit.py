"""Pipeline de la nuit (cron 23h30) : sources -> dbt (vues + tests) -> contrôles -> sauvegarde -> copie de lecture.

    charger_sources ─┐
                     ├─> dbt_build ─┬─> fraicheur        (non bloquante)
    maj_foot_db ─────┘              ├─> controle_matchs  (dim, lun, mar, mer, sam)
                                    └─> copie_lecture    (base de la page web en lecture seule)
    charger_sources ──> sauvegarde (export Parquet de toute la base, 7 dernières gardées)

Extraction et chargement en Python (foot_3d/tools/to_bronze.py) ; toute transformation dans dbt (projet foot_db).
"""
import datetime as dt

from orchestration.runner import Pipeline, Tache

BASE = '~/data/foot.duckdb'
LECTURE = '~/data/lecture/foot.duckdb'   # même nom de fichier : les vues dbt visent le catalogue « foot »
SAUVEGARDES = '~/data/sauvegardes'
PY = '~/data/foot_3d/.venv/bin/python'
DBT = '~/data/foot_3d/.venv/bin/dbt'
DUCKDB = '~/bin/duckdb'   # mémoire et threads limités dans les commandes : o2switch tue les processus trop gourmands

PIPELINE = Pipeline('nuit', description='sources, dbt, contrôles, sauvegarde et copie de lecture de la base foot', taches=[
    Tache('charger_sources', f'flock -w 3600 data/matches/.run.lock {PY} -u tools/to_bronze.py; c=$?; [ $c -eq 3 ] && exit 0 || exit $c',
          dossier='~/data/foot_3d', relances=2, attente_relance=300, delai_max=3600,
          description='nouveaux matchs (fichiers de data/matches/) -> tables raw'),
    Tache('maj_foot_db', 'git pull -q --ff-only && git log --oneline -1', dossier='~/data/foot_db', relances=2,
          description='modèles dbt à jour depuis GitHub'),
    Tache('dbt_build', f'DBT={DBT} scripts/dbt_build.sh', dossier='~/data/foot_db',
          depend_de=['charger_sources', 'maj_foot_db'], relances=1, delai_max=3600,
          description='bronze, silver, gold (vues) et tests'),
    Tache('fraicheur', f'{DBT} source freshness --profiles-dir .', dossier='~/data/foot_db', depend_de=['dbt_build'],
          bloquante=False, description='avertissement après 4 jours sans chargement, erreur après 15'),
    Tache('controle_matchs', f'{PY} tools/check_matches.py', dossier='~/data/foot_3d', depend_de=['dbt_build'],
          condition=lambda: dt.date.today().isoweekday() in (7, 1, 2, 3, 6), bloquante=False,
          description='chaque match joué : récupéré, publié, dans raw et gold (mail si un manque)'),
    Tache('sauvegarde',
          f'd={SAUVEGARDES}/foot-$(date +%Y%m%d) && rm -rf "$d" && mkdir -p {SAUVEGARDES} && '
          f'{DUCKDB} -readonly {BASE} -c "SET memory_limit=\'1GB\'; SET threads=2; EXPORT DATABASE \'$d\' (FORMAT parquet, COMPRESSION zstd)" && '
          f'du -sh "$d" && ls -1d {SAUVEGARDES}/foot-* | head -n -7 | xargs -r rm -rf',
          depend_de=['charger_sources'], relances=1, delai_max=3600,
          description='EXPORT DATABASE en Parquet (restauration : IMPORT DATABASE), 7 dernières gardées'),
    Tache('copie_lecture',
          f'mkdir -p ~/data/lecture && {DUCKDB} {BASE} -c "CHECKPOINT" && cp {BASE} {LECTURE}.tmp && mv -f {LECTURE}.tmp {LECTURE} && ls -la {LECTURE}',
          depend_de=['dbt_build'], description='copie de la base pour la page web en lecture seule'),
])
