"""Les pipelines déclarés : un fichier par pipeline, chacun expose PIPELINE (orchestration.runner.Pipeline)."""
from . import nuit

PIPELINES = {p.nom: p for p in (nuit.PIPELINE,)}
