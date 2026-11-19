import os
import sys


def pasta_base():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def recurso(nome):
    return os.path.join(pasta_base(), "recursos", nome)


def pasta_dados():
    """Pasta onde o programa pode gravar (log de erros, downloads)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = os.path.join(base, "FatiadorResina")
    os.makedirs(p, exist_ok=True)
    return p
