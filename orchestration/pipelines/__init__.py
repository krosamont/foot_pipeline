"""Les pipelines déclarés : un fichier par pipeline, chacun expose PIPELINE (orchestration.runner.Pipeline)."""
from . import journee, nuit

PIPELINES = {p.nom: p for p in (journee.PIPELINE, nuit.PIPELINE)}
