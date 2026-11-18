"""Dados do projeto e operações nas peças (sem interface)."""
import io
import json
import zipfile

import numpy as np
import trimesh
from trimesh import transformations as tf

# Elegoo Saturn 2 8K
MESA_X, MESA_Y, MESA_Z = 219.0, 123.0, 250.0
LIMITE_DESFAZER = 40


class Peca:
    def __init__(self, nome, malha, visivel=True):
        self.nome = nome
        self.malha = malha
        self.visivel = visivel

    def copia(self):
        return Peca(self.nome, self.malha.copy(), self.visivel)


class Projeto:
    def __init__(self):
        self.pecas = []
        self._desfazer = []
        self._refazer = []

    def _foto(self):
        return [p.copia() for p in self.pecas]

    def registrar(self):
        """Chamar ANTES de qualquer alteração, para poder desfazer."""
        self._desfazer.append(self._foto())
        if len(self._desfazer) > LIMITE_DESFAZER:
            self._desfazer.pop(0)
        self._refazer.clear()

    def desfazer(self):
        if not self._desfazer:
            return False
        self._refazer.append(self._foto())
        self.pecas = self._desfazer.pop()
        return True

    def refazer(self):
        if not self._refazer:
            return False
        self._desfazer.append(self._foto())
        self.pecas = self._refazer.pop()
        return True

    def limpar_historico(self):
        self._desfazer.clear()
        self._refazer.clear()


# ---------------------------------------------------------------- arquivos
def carregar_malha(caminho):
    m = trimesh.load(caminho, force="mesh")
    if isinstance(m, trimesh.Scene):
        m = m.dump(concatenate=True)
    if m is None or len(m.faces) == 0:
        raise ValueError("O arquivo não tem nenhuma peça 3D.")
    m.merge_vertices()
    return m


def exportar_stl(malhas, caminho):
    junta = trimesh.util.concatenate([m for m in malhas]) if len(malhas) > 1 else malhas[0]
    junta.export(caminho, file_type="stl")


def salvar_projeto(projeto, caminho):
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        info = []
        for i, p in enumerate(projeto.pecas):
            arq = f"peca_{i}.stl"
            z.writestr(arq, p.malha.export(file_type="stl"))
            info.append({"nome": p.nome, "arquivo": arq, "visivel": p.visivel})
        z.writestr("projeto.json", json.dumps(
            {"versao": 1, "impressora": "Elegoo Saturn 2 8K", "pecas": info},
            ensure_ascii=False, indent=2))


def abrir_projeto(caminho):
    proj = Projeto()
    with zipfile.ZipFile(caminho) as z:
        dados = json.loads(z.read("projeto.json").decode("utf-8"))
        for item in dados["pecas"]:
            m = trimesh.load(io.BytesIO(z.read(item["arquivo"])), file_type="stl", force="mesh")
            m.merge_vertices()
            proj.pecas.append(Peca(item["nome"], m, item.get("visivel", True)))
    return proj


# ---------------------------------------------------------------- posição
def centro(m):
    return m.bounds.mean(axis=0)


def colocar_na_mesa(m):
    m.apply_translation([0, 0, -m.bounds[0][2]])


def centralizar(m):
    c = centro(m)
    m.apply_translation([-c[0], -c[1], 0])
    colocar_na_mesa(m)


def mover(m, dx, dy, dz):
    m.apply_translation([dx, dy, dz])


def _rotacionar(m, matriz):
    c = centro(m)
    t = tf.translation_matrix(c) @ matriz @ tf.translation_matrix(-c)
    m.apply_transform(t)
    colocar_na_mesa(m)


def girar(m, eixo, graus):
    vet = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}[eixo]
    _rotacionar(m, tf.rotation_matrix(np.radians(graus), vet))


def escalar(m, porcentagem):
    f = porcentagem / 100.0
    c = centro(m)
    m.apply_transform(tf.scale_matrix(f, origin=c))
    colocar_na_mesa(m)


def dentro_da_mesa(m, tol=0.01):
    (x0, y0, z0), (x1, y1, z1) = m.bounds
    return (x0 >= -MESA_X / 2 - tol and x1 <= MESA_X / 2 + tol and
            y0 >= -MESA_Y / 2 - tol and y1 <= MESA_Y / 2 + tol and
            z0 >= -tol and z1 <= MESA_Z + tol)


def medidas(m):
    ext = m.extents
    vol_ml = abs(m.volume) / 1000.0 if m.is_watertight else None
    return {"x": ext[0], "y": ext[1], "z": ext[2], "volume_ml": vol_ml,
            "triangulos": len(m.faces), "fechada": bool(m.is_watertight)}


# ---------------------------------------------------------------- orientação automática
def _direcoes(n=400):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.c_[np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]


def orientacao_sugerida(m, angulo_critico=45.0):
    """Procura a posição com menos área pendurada, menos faces planas viradas
    para baixo (que grudam no filme FEP) e altura moderada.
    Devolve a matriz de rotação 4x4."""
    normais = m.face_normals.astype(np.float32)
    areas = m.area_faces.astype(np.float32)
    total = float(areas.sum())
    if len(areas) > 60000:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(areas), 60000, replace=False, p=areas / areas.sum())
        normais = normais[idx]
        areas = np.full(len(idx), total / len(idx), dtype=np.float32)
    try:
        pts = m.convex_hull.vertices.astype(np.float32)
    except Exception:
        pts = m.vertices.astype(np.float32)

    dirs = _direcoes().astype(np.float32)
    lim = np.cos(np.radians(angulo_critico))
    pendurada, plana, altura = [], [], []
    for k in range(0, len(dirs), 50):
        d = dirs[k:k + 50].T
        baixo = normais @ d
        pendurada.append(((baixo > lim) * baixo * areas[:, None]).sum(0) / total)
        plana.append(((baixo > 0.985) * areas[:, None]).sum(0) / total)
        pr = pts @ d
        altura.append(pr.max(0) - pr.min(0))
    pendurada = np.concatenate(pendurada)
    plana = np.concatenate(plana)
    altura = np.concatenate(altura)
    nota = pendurada + 0.6 * plana + 0.25 * altura / altura.max()
    melhor = dirs[int(np.argmin(nota))]
    return trimesh.geometry.align_vectors(melhor, [0, 0, -1])


def aplicar_orientacao(m, matriz):
    _rotacionar(m, matriz)
