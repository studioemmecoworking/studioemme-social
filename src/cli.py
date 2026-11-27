"""Comandi: python -m src.cli tick | remind | sync | prova-reel [id del post]"""
import sys

from . import catalog as cat
from . import pipeline


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "tick"
    if cmd == "tick":
        pipeline.tick()
    elif cmd == "remind":
        pipeline.remind()
    elif cmd == "sync":
        c = cat.load()
        n = cat.sync(c)
        cat.save(c)
        print(f"Libreria sincronizzata: {n} elementi nuovi, {len(c['assets'])} in tutto.")
    elif cmd == "prova-reel":
        pipeline.trial_reel(argv[2].strip() if len(argv) > 2 else "")
    else:
        print("Comando sconosciuto. Usa: tick, remind, sync, prova-reel")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
