"""Pipeline de la journée (cron toutes les 2 h, de 9h45 à 21h45) : les nouveaux matchs dans la base, recalculés par dbt
(incrémental : seulement ces matchs), puis la copie de lecture, pour que la page SQL les montre sans attendre la nuit.

    charger_sources ───────┐
                           ├──> dbt_build ──> copie_lecture   (seulement s'il y a de nouveaux matchs
    nouveau_transfermarkt ─┘                                    ou de nouvelles fiches Transfermarkt)

La mise à jour des modèles depuis GitHub, la sauvegarde et les contrôles restent la nuit (pipeline nuit). Même verrou
que la nuit : jamais deux écritures à la fois.
"""
from orchestration.runner import Pipeline
from orchestration.pipelines.communes import charger_sources, copie_lecture, dbt_build, nouveau_transfermarkt

PIPELINE = Pipeline('journee', description='nouveaux matchs dans la base et copie de lecture rafraîchie',
                    verrou='base_foot', attente_verrou=1800, taches=[
    charger_sources(),
    nouveau_transfermarkt(),
    dbt_build(depend_de=['charger_sources', 'nouveau_transfermarkt'], seulement_si_nouveau=True),
    copie_lecture(depend_de=['dbt_build'], seulement_si_nouveau=True),
])
