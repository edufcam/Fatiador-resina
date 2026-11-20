"""Encaixes inteligentes: pinos de um lado do corte e furos do outro (Fase 3)."""
import numpy as np
from matplotlib.path import Path

PAREDE_PADRAO = 1.5


class Config:
    def __init__(self, tipo="redondo", quantidade=0, diametro=0.0, profundidade=0.0, folga=0.15,
                 parede=PAREDE_PADRAO):
        self.tipo = tipo              # "redondo" ou "quadrado"
        self.quantidade = quantidade  # 0 = automático
        self.diametro = diametro      # 0 = automático
        self.profundidade = profundidade  # 0 = automático
        self.folga = folga
        self.parede = parede


def base_do_plano(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _contornos(m, n, deslocamento):
    from .modelo import ponto_do_plano
    origem = ponto_do_plano(m, n, deslocamento)
    try:
        s = m.section(plane_origin=origem, plane_normal=n)
    except Exception:
        s = None
    if s is None:
        return origem, []
    u, v = base_do_plano(n)
    polis = []
    for d in s.discrete:
        d = np.asarray(d)
        if len(d) >= 4 and np.linalg.norm(d[0] - d[-1]) < 1e-3:
            rel = d - origem
            polis.append(np.c_[rel @ u, rel @ v])
    return origem, polis


def _dentro(pts, polis):
    dentro = np.zeros(len(pts), dtype=bool)
    for p in polis:
        dentro ^= Path(p).contains_points(pts)
    return dentro


def _dist_borda(pts, polis):
    a = np.vstack([p[:-1] for p in polis])
    b = np.vstack([p[1:] for p in polis])
    ab = b - a
    comp = np.maximum((ab ** 2).sum(1), 1e-12)
    melhor = np.full(len(pts), np.inf)
    for k in range(0, len(pts), 400):
        q = pts[k:k + 400, None, :]
        t = np.clip(((q - a) * ab).sum(2) / comp, 0, 1)
        proj = a + t[..., None] * ab
        melhor[k:k + 400] = np.sqrt(((q - proj) ** 2).sum(2)).min(1)
    return melhor


def _area(polis):
    tot = 0.0
    for i, p in enumerate(polis):
        x, y = p[:, 0], p[:, 1]
        ar = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        nivel = sum(bool(Path(q).contains_point(p[0])) for j, q in enumerate(polis) if j != i)
        tot += ar if nivel % 2 == 0 else -ar
    return max(tot, 0.0)


def _espalhar(pts, pesos, k):
    """Espalha k pontos pela região (k-médias) e prende cada um ao candidato mais próximo."""
    if k == 1:
        return pts[[int(np.argmax(pesos))]]
    rng = np.random.default_rng(1)
    amostra = pts if len(pts) <= 6000 else pts[rng.choice(len(pts), 6000, replace=False)]
    c = [amostra[int(np.argmax(((amostra - amostra.mean(0)) ** 2).sum(1)))]]
    for _ in range(k - 1):
        d = np.min([((amostra - x) ** 2).sum(1) for x in c], axis=0)
        c.append(amostra[int(np.argmax(d))])
    c = np.array(c, dtype=float)
    for _ in range(25):
        rot = np.argmin(((amostra[:, None] - c[None]) ** 2).sum(2), 1)
        for j in range(k):
            if (rot == j).any():
                c[j] = amostra[rot == j].mean(0)
    idx = [int(np.argmin(((pts - x) ** 2).sum(1))) for x in c]
    return pts[idx]


def _espessura(m, pontos, direcao):
    """Distância de cada ponto até a superfície da peça, andando na direção dada."""
    u, v = base_do_plano(direcao)
    V = m.vertices
    P = np.c_[V @ u, V @ v, V @ direcao]
    tri = P[m.faces]
    res = []
    for pt in pontos:
        q = np.array([pt @ u, pt @ v])
        h0 = pt @ direcao
        a, b, c = tri[:, 0, :2], tri[:, 1, :2], tri[:, 2, :2]
        v0, v1, v2 = c - a, b - a, q - a
        d00 = (v0 * v0).sum(1)
        d01 = (v0 * v1).sum(1)
        d02 = (v0 * v2).sum(1)
        d11 = (v1 * v1).sum(1)
        d12 = (v1 * v2).sum(1)
        den = d00 * d11 - d01 * d01
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1)
        s = (d11 * d02 - d01 * d12) / den
        t = (d00 * d12 - d01 * d02) / den
        dentro = ok & (s >= -1e-9) & (t >= -1e-9) & (s + t <= 1 + 1e-9)
        if not dentro.any():
            res.append(0.0)
            continue
        z = tri[dentro, 0, 2] + s[dentro] * (tri[dentro, 2, 2] - tri[dentro, 0, 2]) + \
            t[dentro] * (tri[dentro, 1, 2] - tri[dentro, 0, 2])
        acima = z[z > h0 + 1e-3] - h0
        res.append(float(acima.min()) if len(acima) else 0.0)
    return np.array(res)


def planejar(m, n, deslocamento, cfg):
    """Decide onde ficam os pinos. Devolve um dicionário com o plano ou com o motivo de não caber."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    origem, polis = _contornos(m, n, deslocamento)
    if not polis:
        return {"ok": False, "motivo": "O corte não forma uma face fechada."}
    area = _area(polis)
    todos = np.vstack(polis)
    lo, hi = todos.min(0), todos.max(0)
    passo = max(0.25, float(np.sqrt(max(area, 1) / 2500)))
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0], passo), np.arange(lo[1], hi[1], passo))
    pts = np.c_[gx.ravel(), gy.ravel()]
    pts = pts[_dentro(pts, polis)]
    if not len(pts):
        return {"ok": False, "motivo": "A face do corte é pequena demais para encaixes."}
    dist = _dist_borda(pts, polis)

    if cfg.quantidade > 0:
        qtd = cfg.quantidade
    else:
        qtd = 1 if area < 120 else 2 if area < 500 else 3 if area < 1500 else 4
    if cfg.diametro > 0:
        raios = [cfg.diametro / 2]
    else:
        r0 = float(np.clip(dist.max() * 0.35, 1.0, 3.0))
        raios = sorted({round(max(1.0, r0 * f) * 4) / 4 for f in (1.0, 0.85, 0.7, 0.55, 0.4)}, reverse=True)

    u, v = base_do_plano(n)
    melhor = None
    for raio in raios:
        prof = cfg.profundidade if cfg.profundidade > 0 else float(np.clip(raio * 3, 3.0, 8.0))
        validos = dist >= raio + cfg.folga + cfg.parede
        if not validos.any():
            continue
        cand, dcand = pts[validos], dist[validos]
        espaco = 2 * raio + 2 * cfg.parede + 2 * cfg.folga
        for k in range(qtd, 0, -1):
            centros = _espalhar(cand, dcand, k)
            if k > 1:
                dd = np.sqrt(((centros[:, None] - centros[None]) ** 2).sum(2)) + np.eye(k) * 1e9
                if dd.min() < espaco:
                    continue
            p3 = [origem + c[0] * u + c[1] * v for c in centros]
            ec = _espessura(m, p3, n)
            eb = _espessura(m, p3, -n)
            precisa = min(prof, 2.0) + 1.3
            bons = np.maximum(ec, eb) >= precisa
            if bons.sum() == 0:
                continue
            if melhor is None or bons.sum() > len(melhor[1]):
                melhor = (raio, [c for c, b in zip(centros, bons) if b], ec[bons], eb[bons], prof)
            break
        if melhor is not None and len(melhor[1]) >= qtd:
            break
    if melhor is None:
        if not (dist >= min(raios) + cfg.folga + cfg.parede).any():
            return {"ok": False, "motivo": "Não há espaço na face do corte para um pino com parede segura."}
        return {"ok": False, "motivo": "A peça é fina demais perto do corte para fazer furos."}
    raio, escolhidos, esp_cima, esp_baixo, prof = melhor
    esp_cima, esp_baixo = np.asarray(esp_cima), np.asarray(esp_baixo)
    # o furo vai no lado mais grosso
    lado_furo = "cima" if esp_cima.min() >= esp_baixo.min() else "baixo"
    esp_furo = esp_cima if lado_furo == "cima" else esp_baixo
    prof_final = float(min(prof, esp_furo.min() - 0.3 - 1.0))
    aviso = ""
    if prof_final < prof - 1e-6:
        aviso = (f"Profundidade reduzida para {prof_final:.1f} mm porque a peça é fina nessa região."
                 .replace(".", ",", 1))
    pontos = [origem + p[0] * u + p[1] * v for p in escolhidos]
    return {"ok": True, "pontos": pontos, "raio": raio, "profundidade": prof_final, "n": n, "u": u, "v": v,
            "lado_furo": lado_furo, "tipo": cfg.tipo, "folga": cfg.folga, "area": area, "aviso": aviso,
            "pedidos": qtd}


def _forma(tipo, altura, raio, raio_topo=None):
    import manifold3d as m3
    if tipo == "quadrado":
        r = raio * np.sqrt(2)
        rt = (raio_topo if raio_topo is not None else raio) * np.sqrt(2)
        return m3.Manifold.cylinder(altura, r, rt, 4)
    return m3.Manifold.cylinder(altura, raio, raio if raio_topo is None else raio_topo, 48)


def _posicionar(forma, ponto, eixo, u, v, z0, quadrado):
    if quadrado:  # gira 45° para os lados do quadrado ficarem alinhados
        c, s = np.cos(np.pi / 4), np.sin(np.pi / 4)
        u, v = c * u + s * v, -s * u + c * v
    R = np.c_[u, np.cross(eixo, u), eixo]
    t = ponto + eixo * z0
    return forma.transform(np.c_[R, t])


def aplicar(baixo, cima, plano):
    """Junta os pinos num lado e abre os furos no outro. Recebe e devolve malhas trimesh."""
    from .modelo import _para_manifold, _de_manifold
    n, u, v = plano["n"], plano["u"], plano["v"]
    r, prof, folga, tipo = plano["raio"], plano["profundidade"], plano["folga"], plano["tipo"]
    quad = tipo == "quadrado"
    if plano["lado_furo"] == "cima":
        lado_pino, lado_furo, eixo = baixo, cima, n
    else:
        lado_pino, lado_furo, eixo = cima, baixo, -n
    mp = _para_manifold(lado_pino)
    mf = _para_manifold(lado_furo)
    chanfro = min(0.5, r * 0.25)
    pinos, furos = [], []
    for p in plano["pontos"]:
        corpo = _forma(tipo, 1.0 + prof - chanfro, r)
        ponta = _forma(tipo, chanfro, r, r - chanfro)
        pinos.append(_posicionar(corpo, p, eixo, u, v, -1.0, quad))
        pinos.append(_posicionar(ponta, p, eixo, u, v, prof - chanfro, quad))
        rf = r + folga
        furos.append(_posicionar(_forma(tipo, prof + 0.3 + 0.05, rf), p, eixo, u, v, -0.05, quad))
        boca = min(0.4, rf * 0.2)
        furos.append(_posicionar(_forma(tipo, boca + 0.05, rf + boca, rf), p, eixo, u, v, -0.05, quad))
    for x in pinos:
        mp = mp + x
    for x in furos:
        mf = mf - x
    novo_pino, novo_furo = _de_manifold(mp), _de_manifold(mf)
    if plano["lado_furo"] == "cima":
        return novo_pino, novo_furo
    return novo_furo, novo_pino
