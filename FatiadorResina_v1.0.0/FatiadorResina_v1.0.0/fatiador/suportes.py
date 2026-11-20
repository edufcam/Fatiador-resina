"""Suportes inteligentes (Fase 4)."""
import logging

import numpy as np
import trimesh

logging.getLogger("trimesh").setLevel(logging.ERROR)
from scipy.spatial import cKDTree

PRESETS = {
    "leve": {"ponta": 0.30, "pilar": 0.8, "espaco": 5.0},
    "medio": {"ponta": 0.40, "pilar": 1.0, "espaco": 3.5},
    "pesado": {"ponta": 0.55, "pilar": 1.3, "espaco": 2.5},
}
SEGMENTOS = 10


class Parametros:
    def __init__(self, elevacao=5.0, angulo=45.0, ponta=0.4, pilar=1.0, espaco=3.5, base=1.0,
                 travamento=True, comprimento_ponta=2.5, internos=False):
        self.elevacao = elevacao
        self.angulo = angulo
        self.ponta = ponta
        self.pilar = pilar
        self.espaco = espaco
        self.base = base
        self.travamento = travamento
        self.comprimento_ponta = comprimento_ponta
        self.internos = internos

    def para_dict(self):
        return dict(self.__dict__)

    @classmethod
    def de_dict(cls, d):
        p = cls()
        p.__dict__.update(d)
        return p


class Ambiente:
    """Mapa de onde há peça e de onde é lado de fora (alcançável por fora, sem passar por furos pequenos)."""

    def __init__(self, m, raio_externo=2.0, max_lado=190):
        from scipy import ndimage
        from .ocar import grade
        passo = float(max(m.extents.max() / max_lado, 0.05))
        margem = int(np.ceil(max(raio_externo, passo * 1.5) * 1.5 / passo)) + 2
        occ, origem, passo = grade(m, passo=passo, margem=margem)
        self.occ, self.origem, self.passo = occ, origem, passo
        vazio = ~occ
        r = max(raio_externo, passo * 1.5)
        dist = ndimage.distance_transform_cdt(vazio, metric="chessboard").astype(np.float32) * passo
        cabe = dist > r
        lab, _ = ndimage.label(cabe)
        bordas = np.unique(np.r_[lab[0].ravel(), lab[-1].ravel(), lab[:, 0].ravel(), lab[:, -1].ravel(),
                                 lab[:, :, 0].ravel(), lab[:, :, -1].ravel()])
        bordas = bordas[bordas > 0]
        alcance = np.isin(lab, bordas)
        perto = ndimage.distance_transform_cdt(~alcance, metric="chessboard") * passo <= r + passo
        self.fora = perto & vazio

    def _idx(self, pts):
        pts = np.atleast_2d(pts)
        i = np.round((pts - self.origem) / self.passo).astype(int)
        lim = np.array(self.occ.shape[::-1]) - 1
        dentro_grade = np.all((i >= 0) & (i <= lim), axis=1)
        i = np.clip(i, 0, lim)
        return i, dentro_grade

    def solido(self, pts):
        i, ok = self._idx(pts)
        return self.occ[i[:, 2], i[:, 1], i[:, 0]] & ok

    def externo(self, pts):
        i, ok = self._idx(pts)
        return self.fora[i[:, 2], i[:, 1], i[:, 0]] | ~ok

    def segmento_livre(self, p0, p1, folga=0.6):
        """True se o segmento (sem as pontas) não passa por dentro da peça."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        comp = np.linalg.norm(p1 - p0)
        if comp <= 2 * folga:
            return True
        t = np.linspace(folga / comp, 1 - folga / comp, max(3, int(comp / (self.passo * 0.5))))
        pts = p0 + t[:, None] * (p1 - p0)
        return not self.solido(pts).any()


class Suportes:
    """Lista de suportes de uma peça. topo = onde toca a peça; fim = onde termina (mesa ou peça)."""

    def __init__(self, params, topos=None, fins=None, na_mesa=None):
        self.params = params
        self.topos = np.zeros((0, 3)) if topos is None else np.asarray(topos, float).reshape(-1, 3)
        self.fins = np.zeros((0, 3)) if fins is None else np.asarray(fins, float).reshape(-1, 3)
        self.na_mesa = np.zeros(0, bool) if na_mesa is None else np.asarray(na_mesa, bool)
        self.travas = np.zeros((0, 2, 3))
        self._malha = None
        self.volume_ml = 0.0

    def copia(self):
        s = Suportes(Parametros.de_dict(self.params.para_dict()), self.topos.copy(), self.fins.copy(),
                     self.na_mesa.copy())
        s.travas = self.travas.copy()
        s._malha, s.volume_ml = self._malha, self.volume_ml
        return s

    def __len__(self):
        return len(self.topos)

    def transladar(self, d):
        d = np.asarray(d, float)
        self.topos = self.topos + d
        self.fins = self.fins + d
        self.travas = self.travas + d
        if self._malha is not None:
            self._malha = self._malha.copy()
            self._malha.apply_translation(d)

    def para_dict(self):
        return {"params": self.params.para_dict(), "topos": self.topos.tolist(), "fins": self.fins.tolist(),
                "na_mesa": self.na_mesa.tolist(), "travas": self.travas.tolist()}

    @classmethod
    def de_dict(cls, d):
        s = cls(Parametros.de_dict(d["params"]), d["topos"], d["fins"], d["na_mesa"])
        if d.get("travas"):
            s.travas = np.asarray(d["travas"], float).reshape(-1, 2, 3)
        else:
            calcular_travas(s)
        return s

    def malha(self):
        if self._malha is None:
            self._malha, self.volume_ml = construir_malha(self)
        return self._malha

    def mudou(self):
        self._malha = None


# ---------------------------------------------------------------- geometria
def _tronco(p0, p1, r0, r1, seg=SEGMENTOS):
    """Tronco de cone fechado de p0 (raio r0) até p1 (raio r1)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    eixo = p1 - p0
    h = np.linalg.norm(eixo)
    if h < 1e-6:
        return None, 0.0
    eixo /= h
    a = np.array([1.0, 0, 0]) if abs(eixo[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(eixo, a)
    u /= np.linalg.norm(u)
    v = np.cross(eixo, u)
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    anel = np.c_[np.cos(ang), np.sin(ang)]
    a0 = p0 + r0 * (anel[:, :1] * u + anel[:, 1:] * v)
    a1 = p1 + r1 * (anel[:, :1] * u + anel[:, 1:] * v)
    vert = np.vstack([a0, a1, p0, p1])
    i = np.arange(seg)
    j = (i + 1) % seg
    c0, c1 = 2 * seg, 2 * seg + 1
    faces = np.vstack([
        np.c_[i, j, seg + j], np.c_[i, seg + j, seg + i],
        np.c_[np.full(seg, c0), j, i], np.c_[np.full(seg, c1), seg + i, seg + j],
    ])
    vol = np.pi * h * (r0 ** 2 + r0 * r1 + r1 ** 2) / 3
    return (vert, faces), vol


def construir_malha(s):
    pr = s.params
    partes, vol = [], 0.0

    def add(p0, p1, r0, r1):
        nonlocal vol
        t, v = _tronco(p0, p1, r0, r1)
        if t is not None:
            partes.append(t)
            vol += v

    rp, rf = pr.ponta / 2, pr.pilar / 2
    entra = 0.3  # quanto a ponta entra na peça
    pes = []
    for topo, fim, mesa in zip(s.topos, s.fins, s.na_mesa):
        altura = topo[2] - fim[2]
        cp = min(pr.comprimento_ponta, max(altura * 0.4, 0.6))
        ini_pilar = topo - [0, 0, cp]
        add(topo + [0, 0, entra], ini_pilar, rp, rf)
        if mesa:
            chao = pr.base
            pe = max(chao + 1.2, min(ini_pilar[2], chao + 1.2))
            if ini_pilar[2] > pe:
                add(ini_pilar, [topo[0], topo[1], pe], rf, rf)
            add([topo[0], topo[1], pe], [topo[0], topo[1], chao - (0.05 if chao > 0 else 0)], rf, rf * 2.4)
            pes.append(topo[:2])
        else:
            cb = min(pr.comprimento_ponta, max(altura * 0.3, 0.5))
            fim_pilar = fim + [0, 0, cb]
            if ini_pilar[2] > fim_pilar[2]:
                add(ini_pilar, fim_pilar, rf, rf)
            add(fim_pilar, fim - [0, 0, entra], rf, rp)
    for p0, p1 in s.travas:
        add(p0, p1, rf * 0.6, rf * 0.6)
    if pes and pr.base > 0:
        xy = np.array(pes)
        mn, mx = xy.min(0) - pr.pilar * 2.4 - 1.5, xy.max(0) + pr.pilar * 2.4 + 1.5
        caixa = trimesh.creation.box(extents=[mx[0] - mn[0], mx[1] - mn[1], pr.base])
        caixa.apply_translation([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, pr.base / 2])
        partes.append((caixa.vertices, caixa.faces))
        vol += caixa.volume
    if not partes:
        return trimesh.Trimesh(), 0.0
    verts, faces, k = [], [], 0
    for v, f in partes:
        verts.append(v)
        faces.append(f + k)
        k += len(v)
    return trimesh.Trimesh(np.vstack(verts), np.vstack(faces), process=False), vol / 1000.0


def calcular_travas(s, amb=None):
    """Hastes em X entre pilares altos vizinhos; pula as que passariam por dentro da peça."""
    pr = s.params
    travas = []
    if pr.travamento:
        idx = [k for k in range(len(s.topos)) if s.na_mesa[k] and s.topos[k][2] - pr.base > 12]
        if len(idx) > 1:
            xy = s.topos[idx, :2]
            arv = cKDTree(xy)
            feitos = set()
            for a, k in enumerate(idx):
                d, b = arv.query(xy[a], k=2)
                par = (min(a, b[1]), max(a, b[1]))
                if d[1] > pr.espaco * 4 or par in feitos:
                    continue
                feitos.add(par)
                k2 = idx[b[1]]
                topo_max = min(s.topos[k][2], s.topos[k2][2]) - pr.comprimento_ponta - 1
                z, lado = pr.base + 3, 0
                while z + 4 < topo_max:
                    p0 = np.array([s.topos[k][0], s.topos[k][1], z + (4 if lado else 0)])
                    p1 = np.array([s.topos[k2][0], s.topos[k2][1], z + (0 if lado else 4)])
                    if amb is None or amb.segmento_livre(p0, p1, folga=0.0):
                        travas.append((p0, p1))
                    z += 4
                    lado ^= 1
    s.travas = np.array(travas, float).reshape(-1, 2, 3)
    s.mudou()


# ---------------------------------------------------------------- análise
class Raios:
    """Raios verticais para baixo contra a peça."""

    def __init__(self, m):
        tri = m.triangles
        self.tri = tri
        self.mn = tri[:, :, :2].min(1)
        self.mx = tri[:, :, :2].max(1)

    def abaixo(self, p, margem=0.05):
        """Altura do primeiro ponto da peça abaixo de p, ou None."""
        sel = (self.mn[:, 0] <= p[0]) & (self.mx[:, 0] >= p[0]) & (self.mn[:, 1] <= p[1]) & (self.mx[:, 1] >= p[1])
        if not sel.any():
            return None
        t = self.tri[sel]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        v0, v1 = c[:, :2] - a[:, :2], b[:, :2] - a[:, :2]
        v2 = p[:2] - a[:, :2]
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d02, d12 = (v0 * v2).sum(1), (v1 * v2).sum(1)
        den = d00 * d11 - d01 * d01
        ok = np.abs(den) > 1e-14
        den = np.where(ok, den, 1)
        s = (d11 * d02 - d01 * d12) / den
        w = (d00 * d12 - d01 * d02) / den
        dentro = ok & (s >= -1e-9) & (w >= -1e-9) & (s + w <= 1 + 1e-9)
        if not dentro.any():
            return None
        z = a[dentro, 2] + s[dentro] * (c[dentro, 2] - a[dentro, 2]) + w[dentro] * (b[dentro, 2] - a[dentro, 2])
        z = z[z < p[2] - margem]
        return float(z.max()) if len(z) else None


def _acima(raios, p, ate):
    """Altura da primeira superfície da peça acima de p (até `ate` de distância), ou None."""
    sel = (raios.mn[:, 0] <= p[0]) & (raios.mx[:, 0] >= p[0]) & (raios.mn[:, 1] <= p[1]) & (raios.mx[:, 1] >= p[1])
    if not sel.any():
        return None
    t = raios.tri[sel]
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    v0, v1 = c[:, :2] - a[:, :2], b[:, :2] - a[:, :2]
    v2 = p[:2] - a[:, :2]
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d02, d12 = (v0 * v2).sum(1), (v1 * v2).sum(1)
    den = d00 * d11 - d01 * d01
    ok = np.abs(den) > 1e-14
    den = np.where(ok, den, 1)
    s_ = (d11 * d02 - d01 * d12) / den
    w = (d00 * d12 - d01 * d02) / den
    dentro = ok & (s_ >= -1e-9) & (w >= -1e-9) & (s_ + w <= 1 + 1e-9)
    if not dentro.any():
        return None
    z = a[dentro, 2] + s_[dentro] * (c[dentro, 2] - a[dentro, 2]) + w[dentro] * (b[dentro, 2] - a[dentro, 2])
    z = z[(z >= p[2]) & (z <= p[2] + ate)]
    return float(z.min()) if len(z) else None


def analisar_camadas(m, pr, amb, existentes=None, criar=True):
    """Percorre a peça camada por camada (da mesa para cima). Tudo que aparece sem apoio na camada
    de baixo precisa de suporte. Devolve (pontos_novos, pontos_descobertos)."""
    from scipy import ndimage
    occ, origem, passo = amb.occ, amb.origem, amb.passo
    lim = 1.0 / np.tan(np.radians(max(pr.angulo, 5))) + 0.5   # quanto cada camada pode avançar no ar (px)
    R = pr.espaco * 0.75
    pontos = [] if existentes is None else [np.asarray(x, float) for x in np.asarray(existentes).reshape(-1, 3)]
    arv = cKDTree(np.array(pontos)) if pontos else None
    novos, descobertos = [], []
    raios = Raios(m) if criar else None
    yy, xx = np.mgrid[0:occ.shape[1], 0:occ.shape[2]]
    for k in range(1, occ.shape[0]):
        atual = occ[k]
        if not atual.any():
            continue
        antes = occ[k - 1]
        if antes.any():
            longe = ndimage.distance_transform_edt(~antes) > lim
            sem = atual & longe
        else:
            sem = atual.copy()
        if not sem.any():
            continue
        if not pr.internos:
            sem &= amb.fora[k - 1]
            if not sem.any():
                continue
        z = origem[2] + (k - 0.5) * passo
        pts = np.c_[origem[0] + xx[sem] * passo, origem[1] + yy[sem] * passo, np.full(sem.sum(), z)]
        miolo = ndimage.binary_erosion(atual)[sem]
        if arv is not None:
            d, _ = arv.query(pts, distance_upper_bound=R)
            fica = ~np.isfinite(d)
            pts, miolo = pts[fica], miolo[fica]
        if not len(pts):
            continue
        if not criar:
            descobertos.append(pts)
            continue
        escolhidos = []
        # 1) uma ponta por célula de uma grade regular (espalha por igual)
        cel = np.floor(pts[:, :2] / pr.espaco).astype(int)
        centro = (cel + 0.5) * pr.espaco
        dist = np.linalg.norm(pts[:, :2] - centro, axis=1) + np.where(miolo, 0, pr.espaco)
        ordem = np.lexsort((dist, cel[:, 1], cel[:, 0]))
        _, primeiros = np.unique(cel[ordem], axis=0, return_index=True)
        escolhidos.extend(ordem[primeiros].tolist())
        # 2) o que ainda ficou longe de qualquer ponta (bordas, ilhas pequenas)
        cobre = cKDTree(pts[escolhidos])
        d, _ = cobre.query(pts, distance_upper_bound=R)
        resto = np.where(~np.isfinite(d))[0]
        while len(resto):
            prefer = resto[miolo[resto]] if miolo[resto].any() else resto
            i = int(prefer[0])
            escolhidos.append(i)
            resto = resto[np.linalg.norm(pts[resto] - pts[i], axis=1) > R]
        for i in escolhidos:
            p = pts[i].copy()
            zs = _acima(raios, p - [0, 0, passo], passo * 3)
            if zs is not None:
                p[2] = zs
            novos.append(p)
            pontos.append(p)
        arv = cKDTree(np.array(pontos))
    descobertos = np.vstack(descobertos) if descobertos else np.zeros((0, 3))
    return np.array(novos).reshape(-1, 3), descobertos


def faces_criticas(m, angulo):
    return np.where(m.face_normals[:, 2] < -np.cos(np.radians(angulo)))[0]


def minimos(m):
    """Vértices mais baixos que todos os vizinhos (pontas e ilhas que começam no ar)."""
    z = m.vertices[:, 2]
    arestas = m.edges_unique
    menor = np.full(len(z), np.inf)
    np.minimum.at(menor, arestas[:, 0], z[arestas[:, 1]])
    np.minimum.at(menor, arestas[:, 1], z[arestas[:, 0]])
    return np.where(z < menor - 1e-6)[0]


def _afinar(pts, raio, prioridade):
    """Mantém pontos com pelo menos `raio` de distância entre si, na ordem de prioridade."""
    ordem = np.argsort(prioridade, kind="stable")
    arv = cKDTree(pts)
    removido = np.zeros(len(pts), bool)
    fica = []
    for i in ordem:
        if removido[i]:
            continue
        fica.append(i)
        removido[arv.query_ball_point(pts[i], raio)] = True
    return np.array(fica, int)


def pontos_automaticos(m, pr):
    crit = faces_criticas(m, pr.angulo)
    candidatos, prio = [], []
    mins = minimos(m)
    if len(mins):
        candidatos.append(m.vertices[mins])
        prio.append(np.full(len(mins), -1e6) + m.vertices[mins, 2])
    if len(crit):
        sub = m.submesh([crit], append=True)
        qtd = int(np.clip(sub.area / (pr.espaco / 3) ** 2, 50, 60000))
        amostra, _ = trimesh.sample.sample_surface_even(sub, qtd, radius=pr.espaco / 4, seed=1)
        if len(amostra):
            candidatos.append(amostra)
            prio.append(amostra[:, 2])
    if not candidatos:
        return np.zeros((0, 3))
    pts = np.vstack(candidatos)
    return pts[_afinar(pts, pr.espaco, np.concatenate(prio))]


def montar(m, pr, pontos, raios=None, amb=None, normais=None, forcar=False):
    """Para cada ponto decide se o suporte vai até a mesa ou apoia na peça.
    Com `amb`, descarta suportes internos (se desligados) e os que atravessariam a peça."""
    raios = raios or Raios(m)
    topos, fins, mesa = [], [], []
    pontos = np.asarray(pontos, float).reshape(-1, 3)
    if amb is not None and not pr.internos and not forcar and len(pontos):
        sonda = pontos - np.array([0, 0, max(amb.passo * 1.5, 0.6)])
        pontos = pontos[amb.externo(sonda)]
    for p in pontos:
        z = raios.abaixo(p)
        if z is None:
            if p[2] - pr.base < 1.0:
                continue
            topos.append(p)
            fins.append([p[0], p[1], pr.base])
            mesa.append(True)
        else:
            if p[2] - z < pr.comprimento_ponta + 1.5:
                continue  # muito perto da peça: dentro de um canto
            topos.append(p)
            fins.append([p[0], p[1], z])
            mesa.append(False)
    if amb is not None and topos:
        ok = [amb.segmento_livre(t, f, folga=0.8) for t, f in zip(topos, fins)]
        topos = [t for t, o in zip(topos, ok) if o]
        fins = [f for f, o in zip(fins, ok) if o]
        mesa = [x for x, o in zip(mesa, ok) if o]
    return np.array(topos).reshape(-1, 3), np.array(fins).reshape(-1, 3), np.array(mesa, bool)


def gerar(m, pr, amb=None):
    """Eleva a peça e cria os suportes automáticos. Altera m (posição). Devolve (suportes, ambiente)."""
    d = pr.elevacao + pr.base - m.bounds[0][2]
    m.apply_translation([0, 0, d])
    if amb is None or abs(d) > 1e-9:
        amb = Ambiente(m)
    pts, _ = analisar_camadas(m, pr, amb)
    mins = m.vertices[minimos(m)]
    if len(mins):
        sonda = mins - np.array([0, 0, max(amb.passo * 1.5, 0.6)])
        if not pr.internos:
            mins = mins[amb.externo(sonda)]
        if len(pts) and len(mins):
            d, _ = cKDTree(pts).query(mins)
            mins = mins[d > pr.espaco * 0.6]
        pts = np.vstack([pts, mins]) if len(pts) else mins
    t, f, me = montar(m, pr, pts, amb=amb)
    s = Suportes(pr, t, f, me)
    calcular_travas(s, amb)
    return s, amb


def verificar(s, amb):
    """Devolve (atravessam, internos): suportes que passam por dentro da peça e os que ficam no vazio interno."""
    if not len(s):
        return np.zeros(0, bool), np.zeros(0, bool)
    atravessa = np.array([not amb.segmento_livre(t, f, folga=0.8) for t, f in zip(s.topos, s.fins)])
    sonda = s.topos - np.array([0, 0, max(amb.passo * 1.5, 0.6)])
    interno = ~amb.externo(sonda)
    return atravessa, interno


def remover_indices(s, remover):
    manter = ~np.asarray(remover, bool)
    s.topos, s.fins, s.na_mesa = s.topos[manter], s.fins[manter], s.na_mesa[manter]
    s.mudou()


def adicionar(m, s, ponto, amb=None):
    t, f, me = montar(m, s.params, [np.asarray(ponto, float)], amb=amb, forcar=True)
    if not len(t):
        return False
    s.topos = np.vstack([s.topos, t])
    s.fins = np.vstack([s.fins, f])
    s.na_mesa = np.concatenate([s.na_mesa, me])
    calcular_travas(s, amb)
    return True


def remover_perto(s, ponto, raio=3.0, amb=None):
    """Remove o suporte mais perto do clique (em planta, dentro da altura do suporte)."""
    if not len(s):
        return False
    ponto = np.asarray(ponto, float)
    dxy = np.linalg.norm(s.topos[:, :2] - ponto[:2], axis=1)
    na_altura = (ponto[2] <= s.topos[:, 2] + 1.0) & (ponto[2] >= s.fins[:, 2] - 1.5)
    dxy = np.where(na_altura, dxy, np.inf)
    k = int(np.argmin(dxy))
    if dxy[k] > raio:
        return False
    remover = np.zeros(len(s), bool)
    remover[k] = True
    remover_indices(s, remover)
    calcular_travas(s, amb)
    return True


def descobertos_por_camadas(m, s, pr, amb):
    """Pontos que ficam no ar (camada por camada) sem nenhuma ponta de suporte por perto."""
    existentes = s.topos if s is not None and len(s) else None
    _, desc = analisar_camadas(m, pr, amb, existentes, criar=False)
    mins = m.vertices[minimos(m)]
    if len(mins):
        sonda = mins - np.array([0, 0, max(amb.passo * 1.5, 0.6)])
        mins = mins[mins[:, 2] > 0.2]
        if not pr.internos and len(mins):
            mins = mins[amb.externo(mins - [0, 0, max(amb.passo * 1.5, 0.6)])]
        if existentes is not None and len(mins):
            d, _ = cKDTree(existentes).query(mins)
            mins = mins[d > max(pr.espaco, 1.0)]
    desc = desc[desc[:, 2] > 0.2] if len(desc) else desc
    return desc, mins, len(desc) * amb.passo ** 2


def sem_suporte(m, s, angulo, espaco, amb=None, internos=False):
    """Faces críticas e pontos baixos que ficaram sem suporte por perto."""
    crit = faces_criticas(m, angulo)
    mins = m.vertices[minimos(m)]
    if amb is not None and not internos:
        sonda = np.array([0, 0, max(amb.passo * 1.5, 0.6)])
        if len(crit):
            crit = crit[amb.externo(m.triangles_center[crit] - sonda)]
        if len(mins):
            mins = mins[amb.externo(mins - sonda)]
    raio = espaco * 1.0
    if s is not None and len(s):
        arv = cKDTree(s.topos)
        if len(crit):
            d, _ = arv.query(m.triangles_center[crit])
            crit = crit[d > raio]
        if len(mins):
            d, _ = arv.query(mins)
            mins = mins[d > max(raio, 1.0)]
    # ignora o que já encosta na mesa
    if len(crit):
        crit = crit[m.triangles_center[crit][:, 2] > 0.2]
    if len(mins):
        mins = mins[mins[:, 2] > 0.2]
    return crit, mins
