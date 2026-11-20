"""Teste de calibração: a mesma peça em várias regiões da mesa, cada uma com um tempo de exposição.

Em cada camada a tela acende todas as regiões; quando o menor tempo acaba, a imagem é trocada
apagando aquela região (sem mover a mesa) e as outras continuam acesas. A mesa só sobe depois que
a região de maior tempo termina."""
import numpy as np
import trimesh

from .fatiar import Fatiador, IMPRESSORA

SEGMENTOS = {  # 7 segmentos: a (topo), b, c, d (baixo), e, f, g (meio)
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


def _caixa(x0, y0, x1, y1, z0, z1):
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return b


def texto(txt, altura, z0, z1, x=0.0, y=0.0, traco=None):
    """Números com vírgula em 7 segmentos (em relevo). (x, y) = canto inferior esquerdo."""
    a = altura
    w = a * 0.55
    t = traco or a * 0.16
    partes = []
    cx = x
    for ch in txt:
        if ch in ",.":
            partes.append(_caixa(cx, y - t * 0.6, cx + t, y + t, z0, z1))
            cx += t * 2.2
            continue
        segs = SEGMENTOS.get(ch)
        if segs is None:
            cx += w * 0.6
            continue
        meio = y + a / 2
        defs = {
            "a": (cx, y + a - t, cx + w, y + a), "d": (cx, y, cx + w, y + t), "g": (cx, meio - t / 2, cx + w, meio + t / 2),
            "f": (cx, meio, cx + t, y + a), "b": (cx + w - t, meio, cx + w, y + a),
            "e": (cx, y, cx + t, meio), "c": (cx + w - t, y, cx + w, meio),
        }
        for sgm in segs:
            partes.append(_caixa(*defs[sgm], z0, z1))
        cx += w + t * 1.6
    return partes, cx - x


def peca_padrao(rotulo):
    """Peça de calibração (22 x 18 mm) impressa direto na mesa, com detalhes que mostram falta ou
    excesso de cura: pinos finos, paredes finas, furos, ponte e o tempo gravado em relevo."""
    import manifold3d as m3
    from .modelo import _para_manifold, _de_manifold
    partes = [_caixa(-11, -9, 11, 9, 0, 1.6)]
    # pinos: 0,4 0,6 0,8 1,0 1,5 mm
    x = -9.0
    for d in (0.4, 0.6, 0.8, 1.0, 1.5):
        c = trimesh.creation.cylinder(radius=d / 2, height=3.4, sections=24)
        c.apply_translation([x, 5.8, 1.6 + 1.7 - 0.05])
        partes.append(c)
        x += 2.6
    # paredes finas: 0,2 0,3 0,5 0,8 mm
    x = 3.0
    for e in (0.2, 0.3, 0.5, 0.8):
        partes.append(_caixa(x, 3.6, x + e, 8.0, 1.55, 4.6))
        x += e + 1.4
    # ponte de 6 mm
    partes += [_caixa(-10, -2.5, -9, 1.5, 1.55, 4.6), _caixa(-3, -2.5, -2, 1.5, 1.55, 4.6),
               _caixa(-10, -2.5, -2, 1.5, 4.0, 4.6)]
    # bloco com furos de 0,5 0,8 1,2 1,6 mm
    bloco = _para_manifold(_caixa(0.5, -2.5, 10.5, 1.5, 1.55, 4.6))
    x = 1.8
    for d in (0.5, 0.8, 1.2, 1.6):
        furo = m3.Manifold.cylinder(5.0, d / 2, d / 2, 24).translate((x + d / 2, -0.5, 1.0))
        bloco = bloco - furo
        x += d + 1.2
    # tempo gravado em relevo
    letras, larg = texto(rotulo, 4.2, 1.55, 2.3)
    for l in letras:
        l.apply_translation([-larg / 2, -7.6, 0])
    base = _para_manifold(trimesh.util.concatenate(partes[:1]))
    for p in partes[1:] + letras:
        base = base + _para_manifold(p)
    base = base + bloco
    return _de_manifold(base)


def layout(n, impressora=IMPRESSORA, margem=6.0):
    """Divide a mesa em n regiões (retângulos) e devolve [(x0, y0, x1, y1), ...]."""
    colunas = {2: 2, 3: 3, 4: 4, 5: 5, 6: 3, 8: 4, 9: 3, 10: 5, 12: 4}.get(n, int(np.ceil(np.sqrt(n * 1.8))))
    linhas = int(np.ceil(n / colunas))
    X = impressora["res_x"] * impressora["pixel"] - 2 * margem
    Y = impressora["res_y"] * impressora["pixel"] - 2 * margem
    w, h = X / colunas, Y / linhas
    regs = []
    for i in range(n):
        c, r = i % colunas, i // colunas
        x0 = -X / 2 + c * w
        y0 = Y / 2 - (r + 1) * h
        regs.append((x0, y0, x0 + w, y0 + h))
    return regs


def montar_mesa(peca_ou_rotulos, regioes):
    """Coloca uma peça no centro de cada região. Recebe uma malha (mesma peça em todas) ou
    uma lista de rótulos (gera a peça padrão com o tempo gravado)."""
    malhas = []
    for i, (x0, y0, x1, y1) in enumerate(regioes):
        if isinstance(peca_ou_rotulos, (list, tuple)):
            m = peca_padrao(peca_ou_rotulos[i])
        else:
            m = peca_ou_rotulos.copy()
        b = m.bounds
        m.apply_translation([(x0 + x1) / 2 - (b[0][0] + b[1][0]) / 2, (y0 + y1) / 2 - (b[0][1] + b[1][1]) / 2,
                             -b[0][2]])
        malhas.append(m)
    return malhas


def cabe(malha, regioes):
    e = malha.extents
    return all(e[0] <= (x1 - x0) - 1 and e[1] <= (y1 - y0) - 1 for x0, y0, x1, y1 in regioes)


class FatiadorCalibracao(Fatiador):
    def __init__(self, malhas, perfil, regioes, tempos, tempos_base=None, impressora=IMPRESSORA):
        super().__init__(malhas, perfil, impressora)
        self.regioes = regioes
        self.tempos = list(tempos)
        self.tempos_base = list(tempos_base) if tempos_base else None

    def tempos_regioes(self, k):
        p = self.perfil
        res = []
        for i, t in enumerate(self.tempos):
            tb = self.tempos_base[i] if self.tempos_base else p.exposicao_base
            res.append(p.exposicao_da_camada(k, normal=t, base=tb))
        return res

    def plano(self):
        for k in range(self.n_camadas):
            ts = self.tempos_regioes(k)
            unicos = sorted(set(round(t, 3) for t in ts))
            anterior = 0.0
            for j, t in enumerate(unicos):
                ativas = [i for i, ti in enumerate(ts) if round(ti, 3) >= t]
                yield k, (None if len(ativas) == len(ts) else ativas), t - anterior, j == 0
                anterior = t

    def _mascara(self, ativas, r0, c0, forma, escala):
        imp = self.imp
        px = imp["pixel"] * escala
        W, H = imp["res_x"] // escala, imp["res_y"] // escala
        x0, y0 = -W * px / 2, -H * px / 2
        xs = x0 + (c0 + np.arange(forma[1]) + 0.5) * px
        ys = y0 + (r0 + np.arange(forma[0]) + 0.5) * px
        m = np.zeros(forma, bool)
        for i in ativas:
            a, b, c, d = self.regioes[i]
            cx = (xs >= a) & (xs < c)
            ry = (ys >= b) & (ys < d)
            m |= ry[:, None] & cx[None, :]
        return m
