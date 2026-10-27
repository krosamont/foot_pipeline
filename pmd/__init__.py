"""Post-match dashboard (pmd): WhoScored + FotMob -> enriched CSV exports + 18-panel dashboard.

    python -m pmd.run --fotmob 4653857 --whoscored 2007643 --out output

Modules, in pipeline order: config -> fetch -> events -> export -> dashboard (run.py chains them).
"""
