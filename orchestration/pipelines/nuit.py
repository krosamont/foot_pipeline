"""Pipeline de la nuit (cron 23h30) : sources -> dbt (vues + tests) -> contrôles -> sauvegarde -> copie de lecture.

    charger_sources ─┐
                     ├─> dbt_build ─┬─> fraicheur        (non bloquante)
    maj_foot_db ─────┘              ├─> controle_matchs  (dim, lun, mar, mer, sam)
                                    └─> copie_lecture    (base de la page web en lecture seule)
    sauvegarde (export Parquet de toute la base, 7 dernières gardées ; même si le chargement échoue)

Extraction et chargement en Python (foot_3d/tools/to_bronze.py) ; toute transformation dans dbt (projet foot_db).
"""
import datetime as dt

from orchestration.runner import Pipeline, Tache
from orchestration.pipelines.communes import BASE, DUCKDB, PY, charger_sources, copie_lecture

SAUVEGARDES = '~/data/sauvegardes'
DBT = '~/data/foot_3d/.venv/bin/dbt'

PIPELINE = Pipeline('nuit', description='sources, dbt, contrôles, sauvegarde et copie de lecture de la base foot',
                    verrou='base_foot', attente_verrou=3600, taches=[
    charger_sources(),
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
          relances=1, delai_max=3600,   # sans dépendance : sauvegardée même si le chargement échoue (lancée après lui)
          description='EXPORT DATABASE en Parquet (restauration : IMPORT DATABASE), 7 dernières gardées'),
    copie_lecture(depend_de=['dbt_build']),
])
