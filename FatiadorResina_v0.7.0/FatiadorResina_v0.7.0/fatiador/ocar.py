"""Ocar peças, furos de drenagem e detecção de sucção (Fase 5)."""
import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

QUALIDADE = {"rapida": 120, "normal": 180, "fina": 260}


# ---------------------------------------------------------------- grade de ocupação (camadas)
def grade(m, max_lado=180, passo=None, margem=1):
    """Fatia a peça em camadas e marca quais pontos estão dentro (respeita vazios internos)."""
    b = m.bounds
    tam = b[1] - b[0]
    if passo is None:
        passo = float(max(tam.max() / max_lado, 0.05))
    n = np.ceil(tam / passo).astype(int) + 2 * margem
    origem = b[0] - passo * (margem - 0.5)
    xs = origem[0] + passo * np.arange(n[0])
    ys = origem[1] + passo * np.arange(n[1])
    zs = origem[2] + passo * np.arange(n[2])
    tri = m.triangles
    zmin, zmax = tri[:, :, 2].min(1), tri[:, :, 2].max(1)
    ordem = np.argsort(zmin)
    tri, zmin, zmax = tri[ordem], zmin[ordem], zmax[ordem]
    occ = np.zeros((n[2], n[1], n[0]), bool)
    for k, z in enumerate(zs):
        z = z + 1e-7
        fim = np.searchsorted(zmin, z)
        sel = zmax[:fim] > z
        if not sel.any():
            continue
        t = tri[:fim][sel]
        acima = t[:, :, 2] > z
        # para cada triângulo: o vértice sozinho de um lado e os dois do outro
        sozinho = np.where(acima.sum(1) == 1, np.argmax(acima, 1), np.argmin(acima, 1))
        a = t[np.arange(len(t)), sozinho]
        b1 = t[np.arange(len(t)), (sozinho + 1) % 3]
        b2 = t[np.arange(len(t)), (sozinho + 2) % 3]
        f1 = ((z - a[:, 2]) / (b1[:, 2] - a[:, 2]))[:, None]
        f2 = ((z - a[:, 2]) / (b2[:, 2] - a[:, 2]))[:, None]
        p1 = a + f1 * (b1 - a)
        p2 = a + f2 * (b2 - a)
        y0, y1 = p1[:, 1], p2[:, 1]
        for j, y in enumerate(ys):
            cruza = (y0 > y) != (y1 > y)
            if not cruza.any():
                continue
            x = p1[cruza, 0] + (y - y0[cruza]) * (p2[cruza, 0] - p1[cruza, 0]) / (y1[cruza] - y0[cruza])
            x.sort()
            occ[k, j] = (np.searchsorted(x, xs) % 2) == 1
    return occ, origem, passo


# ---------------------------------------------------------------- ocar
def _para_trimesh(poly):
    poly = poly.triangulate().clean()
    f = poly.faces.reshape(-1, 4)[:, 1:]
    return trimesh.Trimesh(np.asarray(poly.points, float), f, process=True)


def cavidade(m, parede, qualidade="normal"):
    """Superfície interna (o vazio) a `parede` mm da superfície externa."""
    import pyvista as pv
    occ, origem, passo = grade(m, QUALIDADE.get(qualidade, 180))
    if passo > parede / 1.5:  # garante pelo menos ~1,5 pontos na parede
        occ, origem, passo = grade(m, passo=parede / 1.5)
    dist = ndimage.distance_transform_edt(occ) * passo
    if dist.max() <= parede + passo:
        return None
    img = pv.ImageData(dimensions=occ.shape[::-1], spacing=(passo,) * 3, origin=tuple(origem))
    img.point_data["d"] = dist.ravel(order="C").astype(np.float32)
    sup = img.contour(isosurfaces=[parede], scalars="d")
    if sup.n_points == 0:
        return None
    sup = sup.triangulate().clean()
    sup = sup.smooth_taubin(n_iter=20, pass_band=0.1)
    if sup.n_cells > 150000:
        sup = sup.decimate(1 - 150000 / sup.n_cells)
    cav = _para_trimesh(sup)
    partes = [c for c in cav.split(only_watertight=False) if len(c.faces) > 20]
    if not partes:
        return None
    cav = trimesh.util.concatenate(partes)
    trimesh.repair.fix_normals(cav, multibody=True)
    return cav


def ocar(m, parede=2.0, qualidade="normal"):
    """Devolve (peça oca, cavidade) ou (None, motivo)."""
    from .modelo import _para_manifold, _de_manifold, consertar
    cav = cavidade(m, parede, qualidade)
    if cav is None:
        return None, "A peça é fina demais para ocar com essa espessura de parede."
    try:
        import manifold3d
        base = m if m.is_watertight else consertar(m)
        mf, mc = _para_manifold(base), _para_manifold(cav)
        if mf.status() == manifold3d.Error.NoError and mc.status() == manifold3d.Error.NoError:
            r = _de_manifold(mf - mc)
            if r is not None and r.volume < m.volume * 0.999:
                return r, cav
    except ImportError:
        pass
    # plano B: casca externa + casca interna virada para dentro
    dentro = cav.copy()
    dentro.invert()
    return trimesh.util.concatenate([m, dentro]), cav


# ---------------------------------------------------------------- furos
def furo(m, ponto, direcao_para_dentro, diametro, comprimento):
    """Abre um furo cilíndrico. Devolve a nova malha ou None."""
    import manifold3d
    from .modelo import _para_manifold, _de_manifold
    d = np.asarray(direcao_para_dentro, float)
    d /= np.linalg.norm(d)
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    cil = manifold3d.Manifold.cylinder(comprimento + 1.0, diametro / 2, diametro / 2, 32)
    inicio = np.asarray(ponto, float) - d * 1.0
    cil = cil.transform(np.c_[u, v, d, inicio])
    mf = _para_manifold(m)
    if mf.status() != manifold3d.Error.NoError:
        return None
    return _de_manifold(mf - cil)


def sugerir_furos(m, cav, parede, quantidade=2):
    """Pontos perto da mesa onde a parede encosta na cavidade."""
    pts, idx = trimesh.sample.sample_surface_even(m, 4000, seed=2)
    if not len(pts):
        return []
    arv = cKDTree(cav.vertices)
    d, j = arv.query(pts)
    ok = d < parede * 1.8 + 0.5
    if not ok.any():
        return []
    pts, d, j = pts[ok], d[ok], j[ok]
    ordem = np.argsort(pts[:, 2])
    pts, d, j = pts[ordem], d[ordem], j[ordem]
    corte = max(1, int(len(pts) * 0.25))
    escolhidos = [0]
    for _ in range(quantidade - 1):
        cand = np.arange(corte)
        dist = np.min([np.linalg.norm(pts[cand] - pts[e], axis=1) for e in escolhidos], axis=0)
        k = int(cand[np.argmax(dist)])
        if dist.max() < 5:
            break
        escolhidos.append(k)
    res = []
    for k in escolhidos:
        alvo = cav.vertices[j[k]]
        direcao = alvo - pts[k]
        res.append((pts[k], direcao / max(np.linalg.norm(direcao), 1e-9), d[k] + 1.5))
    return res


# ---------------------------------------------------------------- sucção
def riscos_succao(m, max_lado=110, area_minima=2.0):
    """Regiões vazias fechadas por cima (lado da mesa) que viram ventosa durante a impressão."""
    occ, origem, passo = grade(m, max_lado)
    vazio = ~occ
    pai = [0]          # 0 = "lado de fora"
    fora = [True]

    def achar(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def unir(a, b):
        ra, rb = achar(a), achar(b)
        if ra != rb:
            pai[rb] = ra
            fora[ra] = fora[ra] or fora[rb]

    ant_lab, ant_base = None, 0
    riscos = {}
    for k in range(vazio.shape[0]):
        lab, n = ndimage.label(vazio[k])
        base = len(pai) - 1
        for i in range(n):
            pai.append(len(pai))
            fora.append(False)
        if n == 0:
            ant_lab, ant_base = lab, base
            continue
        borda = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
        for b in borda[borda > 0]:
            unir(0, base + int(b))
        if k == 0:
            for i in range(1, n + 1):
                unir(0, base + i)
        if ant_lab is not None:
            m2 = (lab > 0) & (ant_lab > 0)
            if m2.any():
                pares = np.unique(np.c_[lab[m2], ant_lab[m2]], axis=0)
                for a, b in pares:
                    unir(base + int(a), ant_base + int(b))
        for i in range(1, n + 1):
            r = achar(base + i)
            if not fora[r]:
                cel = lab == i
                area = cel.sum() * passo * passo
                if area < area_minima:
                    continue
                yy, xx = np.nonzero(cel)
                z = origem[2] + k * passo
                riscos.setdefault(base + i, []).append((z, area, origem[0] + xx * passo, origem[1] + yy * passo))
        ant_lab, ant_base = lab, base
    grupos = {}
    for chave, lista in riscos.items():
        grupos.setdefault(achar(chave), []).extend(lista)
    regioes = []
    for lista in grupos.values():
        zs = [x[0] for x in lista]
        maior = max(x[1] for x in lista)
        pts = np.vstack([np.c_[x[2], x[3], np.full(len(x[2]), x[0])] for x in lista])
        if len(pts) > 1500:
            pts = pts[np.random.default_rng(0).choice(len(pts), 1500, replace=False)]
        regioes.append({"z0": min(zs), "z1": max(zs), "area": maior, "pontos": pts})
    regioes.sort(key=lambda r: -r["area"])
    return regioes
