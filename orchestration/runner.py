"""Mini-orchestrateur sans service permanent (o2switch n'autorise pas les démons) : des DAG de tâches, à la Airflow.

Un pipeline = des tâches (commande shell), leurs dépendances, des relances, un délai maximum, une condition
d'exécution. Le cron lance `python -m orchestration run <pipeline>` ; chaque exécution est enregistrée dans
~/data/pipelines/runs.sqlite (pipelines, tâches, statuts, durées) avec un journal par tâche, et un e-mail part si une
tâche bloquante échoue. Une tâche dont une dépendance a échoué n'est pas lancée (statut « sautee_dependance »).
Une tâche peut aussi finir sur « rien » (code_rien : rien de nouveau) ; les tâches seulement_si_nouveau qui n'ont que
des dépendances « rien » sont alors sautées (comme un ShortCircuitOperator d'Airflow). Les pipelines qui écrivent dans
la même base partagent un verrou : le second attend que le premier ait fini.
"""
import datetime as dt
import fcntl
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable, Optional

ACCUEIL = os.path.expanduser(os.environ.get('PIPELINES_HOME', '~/data/pipelines'))
BASE_RUNS = os.path.join(ACCUEIL, 'runs.sqlite')
MAIL_A = os.environ.get('PIPELINES_MAIL', 'krosamont@data-workers.com')
MAIL_DE = 'pipelines <noreply@data-workers.com>'
SENDMAIL = '/usr/sbin/sendmail'


@dataclass
class Tache:
    nom: str
    commande: str                                  # exécutée par bash, dans `dossier`
    dossier: str = '~'
    depend_de: list = field(default_factory=list)
    relances: int = 0                              # nouvelles tentatives après un échec
    attente_relance: int = 60                      # secondes entre deux tentatives
    delai_max: int = 3600                          # secondes ; au-delà la tâche est arrêtée (échec)
    bloquante: bool = True                         # False : un échec est signalé mais ne fait pas échouer le pipeline
    condition: Optional[Callable[[], bool]] = None # False -> tâche sautée (ex. : seulement certains jours)
    code_rien: Optional[int] = None                # ce code de sortie = réussite sans rien de nouveau (statut « rien »)
    seulement_si_nouveau: bool = False             # sautée si toutes ses dépendances ont fini sur « rien »
    description: str = ''


@dataclass
class Pipeline:
    nom: str
    taches: list
    description: str = ''
    verrou: str = ''                               # nom du verrou (par défaut le nom du pipeline) ; partagé = jamais en même temps
    attente_verrou: int = 0                        # secondes d'attente si le verrou est pris (0 : on abandonne)

    def ordre(self):
        """Ordre topologique (les dépendances d'abord), en gardant l'ordre de déclaration."""
        noms = {t.nom: t for t in self.taches}
        for t in self.taches:
            for d in t.depend_de:
                if d not in noms:
                    raise ValueError(f'{self.nom}.{t.nom} dépend de {d}, inconnue')
        vu, out = set(), []

        def visite(t, pile=()):
            if t.nom in pile:
                raise ValueError(f'cycle dans {self.nom} : {" -> ".join(pile + (t.nom,))}')
            if t.nom in vu:
                return
            for d in t.depend_de:
                visite(noms[d], pile + (t.nom,))
            vu.add(t.nom)
            out.append(t)

        for t in self.taches:
            visite(t)
        return out


def base():
    os.makedirs(ACCUEIL, exist_ok=True)
    con = sqlite3.connect(BASE_RUNS)
    con.executescript("""
        create table if not exists runs (id integer primary key, pipeline text, debut text, fin text, statut text);
        create table if not exists taches (run_id integer, tache text, debut text, fin text, statut text,
                                           tentatives integer, code integer, journal text);
    """)
    return con


def maintenant():
    return dt.datetime.now().isoformat(timespec='seconds')


def mail(sujet, corps):
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = MAIL_DE, MAIL_A, sujet
    msg.set_content(corps)
    try:
        subprocess.run([SENDMAIL, '-t', '-oi'], input=msg.as_bytes(), check=True, timeout=60)
    except Exception as e:   # noqa: BLE001  (le mail ne doit pas faire tomber le pipeline)
        print(f'[orchestration] mail non envoyé : {e}')


def queue(chemin, n=40):
    try:
        with open(chemin, errors='replace') as f:
            return ''.join(f.readlines()[-n:])
    except OSError:
        return ''


def executer(p: Pipeline):
    """Exécute un pipeline (un seul à la fois par pipeline : verrou), renvoie le statut final."""
    os.makedirs(os.path.join(ACCUEIL, 'logs', p.nom), exist_ok=True)
    verrou = open(os.path.join(ACCUEIL, f'.{p.verrou or p.nom}.lock'), 'w')
    limite = time.time() + p.attente_verrou
    while True:
        try:
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() >= limite:
                print(f'[{p.nom}] verrou {p.verrou or p.nom} pris (un autre pipeline tourne), abandon')
                return 'deja_en_cours'
            time.sleep(30)
    con = base()
    run_id = con.execute('insert into runs (pipeline, debut, statut) values (?, ?, ?)', (p.nom, maintenant(), 'en_cours')).lastrowid
    con.commit()
    dossier_run = os.path.join(ACCUEIL, 'logs', p.nom, f'{dt.datetime.now():%Y%m%d-%H%M%S}-{run_id}')
    os.makedirs(dossier_run, exist_ok=True)
    statuts, echecs = {}, []
    print(f'[{p.nom}] exécution {run_id} — journaux : {dossier_run}', flush=True)
    for t in p.ordre():
        journal = os.path.join(dossier_run, f'{t.nom}.log')
        debut = maintenant()
        if any(statuts.get(d) in ('echec', 'sautee_dependance') for d in t.depend_de if
               next(x for x in p.taches if x.nom == d).bloquante):
            statuts[t.nom] = 'sautee_dependance'
        elif t.condition and not t.condition():
            statuts[t.nom] = 'sautee'
        elif t.seulement_si_nouveau and t.depend_de and all(statuts.get(d) == 'rien' for d in t.depend_de):
            statuts[t.nom] = 'sautee_rien_de_nouveau'
        else:
            code, tentative = None, 0
            while True:
                tentative += 1
                t0 = time.time()
                with open(journal, 'a') as f:
                    f.write(f'=== tentative {tentative} — {maintenant()}\n$ {t.commande}\n')
                    f.flush()
                    try:
                        code = subprocess.run(['bash', '-c', t.commande], cwd=os.path.expanduser(t.dossier), stdout=f,
                                              stderr=subprocess.STDOUT, timeout=t.delai_max).returncode
                    except subprocess.TimeoutExpired:
                        f.write(f'\n!!! arrêtée après {t.delai_max} s\n')
                        code = -9
                    f.write(f'=== code {code} en {time.time() - t0:.0f} s\n')
                if code == 0 or code == t.code_rien or tentative > t.relances:
                    break
                time.sleep(t.attente_relance)
            statuts[t.nom] = 'ok' if code == 0 else 'rien' if code == t.code_rien else 'echec'
            if statuts[t.nom] == 'echec':
                echecs.append((t, journal))
            con.execute('insert into taches values (?, ?, ?, ?, ?, ?, ?, ?)',
                        (run_id, t.nom, debut, maintenant(), statuts[t.nom], tentative, code, journal))
            con.commit()
            print(f'[{p.nom}] {t.nom:<22} {statuts[t.nom]:<8} (code {code}, {tentative} tentative(s))', flush=True)
            continue
        con.execute('insert into taches values (?, ?, ?, ?, ?, ?, ?, ?)', (run_id, t.nom, debut, maintenant(), statuts[t.nom], 0, None, None))
        con.commit()
        print(f'[{p.nom}] {t.nom:<22} {statuts[t.nom]}', flush=True)
    bloquants = [t for t, _ in echecs if t.bloquante]
    final = 'echec' if bloquants else ('avertissement' if echecs else 'ok')
    con.execute('update runs set fin = ?, statut = ? where id = ?', (maintenant(), final, run_id))
    con.commit()
    if echecs:
        corps = f'Pipeline {p.nom}, exécution {run_id} : {final}\n\n' + '\n\n'.join(
            f'--- {t.nom} ({"bloquante" if t.bloquante else "non bloquante"}) : {j}\n{queue(j)}' for t, j in echecs)
        mail(f'[pipelines] {p.nom} : {final} ({", ".join(t.nom for t, _ in echecs)})', corps)
    print(f'[{p.nom}] terminé : {final}', flush=True)
    return final


def historique(n=15):
    con = base()
    return con.execute('select id, pipeline, debut, fin, statut from runs order by id desc limit ?', (n,)).fetchall()
