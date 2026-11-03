"""python -m orchestration <commande>

    run <pipeline>     exécute un pipeline (le cron : run nuit)
    liste              les pipelines et leurs tâches, dans l'ordre d'exécution
    historique [n]     les dernières exécutions (statut, début, fin)
"""
import sys

from orchestration.pipelines import PIPELINES
from orchestration.runner import executer, historique


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, *args = argv
    if cmd == 'run':
        statut = executer(PIPELINES[args[0]])
        return 1 if statut == 'echec' else 0
    if cmd == 'liste':
        for p in PIPELINES.values():
            print(f'{p.nom} : {p.description}')
            for t in p.ordre():
                dep = f'  (après {", ".join(t.depend_de)})' if t.depend_de else ''
                print(f'  - {t.nom}{dep}{"" if t.bloquante else "  [non bloquante]"} : {t.description}')
        return 0
    if cmd == 'historique':
        for r in historique(int(args[0]) if args else 15):
            print(*r, sep='  ')
        return 0
    print(__doc__)
    return 2


sys.exit(main(sys.argv[1:]))
