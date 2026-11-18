"""Procura versões novas no GitHub e instala."""
import json
import os
import re
import subprocess
import sys
import urllib.request

from . import VERSAO
from .recursos import pasta_dados

try:
    from ._repo import REPO  # gerado automaticamente na hora de montar o instalador
except ImportError:
    REPO = None


def _num(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def pode_atualizar():
    return bool(REPO) and getattr(sys, "frozen", False)


def procurar():
    """Devolve dados da versão nova, ou None se já está atualizado."""
    if not REPO:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "FatiadorResina"})
    with urllib.request.urlopen(req, timeout=10) as r:
        dados = json.load(r)
    tag = dados.get("tag_name", "")
    if _num(tag) <= _num(VERSAO):
        return None
    exe = next((a for a in dados.get("assets", []) if a["name"].lower().endswith(".exe")), None)
    if not exe:
        return None
    return {"versao": tag.lstrip("v"), "url": exe["browser_download_url"], "nome": exe["name"],
            "tamanho": exe.get("size", 0), "notas": dados.get("body") or ""}


def baixar(info, progresso=None):
    destino = os.path.join(pasta_dados(), info["nome"])
    req = urllib.request.Request(info["url"], headers={"User-Agent": "FatiadorResina"})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino + ".parcial", "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("tamanho") or 0)
        feito = 0
        while True:
            bloco = r.read(256 * 1024)
            if not bloco:
                break
            f.write(bloco)
            feito += len(bloco)
            if progresso and total:
                progresso(int(feito * 100 / total))
    if os.path.exists(destino):
        os.remove(destino)
    os.rename(destino + ".parcial", destino)
    return destino


def instalar(caminho):
    """Abre o instalador em modo silencioso; ele fecha este programa e reabre a versão nova."""
    subprocess.Popen([caminho, "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS"], close_fds=True)
