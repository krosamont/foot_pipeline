"""Pipeline de la journée (cron toutes les 2 h, de 9h45 à 21h45) : les nouveaux matchs dans la base, puis la copie de
lecture, pour que la page SQL les montre sans attendre la nuit.

    charger_sources ──> copie_lecture   (seulement s'il y a eu de nouveaux matchs)

Bronze, silver et gold sont des vues : ils voient les nouveaux matchs dès leur chargement, sans dbt. Les tests dbt, la
sauvegarde et les contrôles restent la nuit (pipeline nuit). Même verrou que la nuit : jamais deux écritures à la fois.
"""
from orchestration.runner import Pipeline
from orchestration.pipelines.communes import charger_sources, copie_lecture

PIPELINE = Pipeline('journee', description='nouveaux matchs dans la base et copie de lecture rafraîchie',
                    verrou='base_foot', attente_verrou=1800, taches=[
    charger_sources(),
    copie_lecture(depend_de=['charger_sources'], seulement_si_nouveau=True),
])
