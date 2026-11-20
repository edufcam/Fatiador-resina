"""Fatiamento: transforma a mesa em imagens, camada por camada (Fase 6)."""
import io
import math
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np

IMPRESSORA = {"nome": "ELEGOO Saturn 2 8K", "res_x": 7680, "res_y": 4320, "pixel": 0.0285, "altura": 250.0}


class Perfil:
    CAMPOS = {
        # resina
        "densidade": 1.10, "preco_litro": 150.0,
        # camadas e exposição
        "altura_camada": 0.05, "exposicao": 2.5, "exposicao_base": 25.0, "camadas_base": 6,
        "camadas_transicao": 0, "espera_antes": 0.5, "espera_depois_expor": 0.0, "espera_depois_subir": 0.0,
        # movimento da mesa
        "subida": 5.0, "vel_subida": 65.0, "subida_base": 5.0, "vel_subida_base": 50.0,
        "duas_etapas": False, "dist_lenta": 3.0, "vel_subida_rapida": 180.0,
        "vel_descida": 150.0, "dist_descida_lenta": 3.0, "vel_descida_lenta": 60.0,
        "espelhar": False, "antialias": 1,
        # correção de medida (vem do cubo de calibração)
        "escala_x": 100.0, "escala_y": 100.0, "escala_z": 100.0,
    }
    ANTIGOS = {"luz_apagada": "espera_antes"}

    def __init__(self, **kw):
        for velho, novo in self.ANTIGOS.items():
            if velho in kw and novo not in kw:
                kw[novo] = kw[velho]
        for k, v in self.CAMPOS.items():
            setattr(self, k, type(v)(kw.get(k, v)) if not isinstance(v, bool) else bool(kw.get(k, v)))

    def para_dict(self):
        return {k: getattr(self, k) for k in self.CAMPOS}

    def exposicao_da_camada(self, k, normal=None, base=None):
        """Exposição com transição suave entre a base e as camadas normais."""
        normal = self.exposicao if normal is None else normal
        base = self.exposicao_base if base is None else base
        if k < self.camadas_base:
            return base
        t = k - self.camadas_base
        if t < self.camadas_transicao:
            f = (t + 1) / (self.camadas_transicao + 1)
            return base + (normal - base) * f
        return normal

    def movimento(self, k):
        """Lista de (altura relativa, velocidade mm/min) da subida e da descida, e o tempo em segundos."""
        base = k < self.camadas_base
        D = self.subida_base if base else self.subida
        v1 = self.vel_subida_base if base else self.vel_subida
        if self.duas_etapas and self.dist_lenta < D:
            dl = self.dist_lenta
            dd = min(self.dist_descida_lenta, D)
            passos = [(dl, v1), (D, self.vel_subida_rapida), (dd, self.vel_descida), (0.0, self.vel_descida_lenta)]
            t = dl / v1 + (D - dl) / self.vel_subida_rapida + (D - dd) / self.vel_descida + dd / self.vel_descida_lenta
        else:
            passos = [(D, v1), (0.0, self.vel_descida)]
            t = D / v1 + D / self.vel_descida
        return passos, t * 60


class Fatiador:
    def __init__(self, malhas, perfil, impressora=IMPRESSORA):
        self.perfil, self.imp = perfil, impressora
        tris, sinais = [], []
        esc = np.array([perfil.escala_x, perfil.escala_y, perfil.escala_z]) / 100.0
        corrigir = not np.allclose(esc, 1.0)
        for m in malhas:
            if m is None or not len(m.faces):
                continue
            if corrigir:  # correção de medida em volta do centro da peça, mantendo a base na mesa
                m = m.copy()
                c = m.bounds.mean(axis=0)
                c[2] = 0.0
                m.vertices = (m.vertices - c) * esc + c
            tris.append(np.asarray(m.triangles, np.float64))
            # sinal do cruzamento: entrando na peça (andando em +x) soma 1, saindo subtrai 1
            sinais.append(-np.sign(m.face_normals[:, 0]))
        self.tri = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
        sinal = np.concatenate(sinais) if sinais else np.zeros(0)
        zmin = self.tri[:, :, 2].min(1)
        ordem = np.argsort(zmin)
        self.tri, self.sinal, self.zmin = self.tri[ordem], sinal[ordem].astype(np.int8), zmin[ordem]
        self.zmax = self.tri[:, :, 2].max(1)
        self.altura = float(self.tri[:, :, 2].max()) if len(self.tri) else 0.0
        self.n_camadas = int(math.ceil(self.altura / perfil.altura_camada - 1e-6))

    def z_da_camada(self, k):
        return (k + 0.5) * self.perfil.altura_camada

    def _segmentos(self, z):
        fim = np.searchsorted(self.zmin, z)
        sel = self.zmax[:fim] > z
        if not sel.any():
            return None
        t = self.tri[:fim][sel]
        s = self.sinal[:fim][sel]
        acima = t[:, :, 2] > z
        sozinho = np.where(acima.sum(1) == 1, np.argmax(acima, 1), np.argmin(acima, 1))
        r = np.arange(len(t))
        a = t[r, sozinho]
        b1 = t[r, (sozinho + 1) % 3]
        b2 = t[r, (sozinho + 2) % 3]
        p1 = a + ((z - a[:, 2]) / (b1[:, 2] - a[:, 2]))[:, None] * (b1 - a)
        p2 = a + ((z - a[:, 2]) / (b2[:, 2] - a[:, 2]))[:, None] * (b2 - a)
        return p1[:, :2], p2[:, :2], s

    def camada(self, k, escala=1, ativas=None):
        """Imagem da camada k como (matriz booleana recortada, linha0, coluna0, largura, altura).
        Linha 0 = fundo da mesa (y menor); coluna 0 = esquerda (x menor)."""
        imp = self.imp
        W, H = imp["res_x"] // escala, imp["res_y"] // escala
        px = imp["pixel"] * escala
        x0, y0 = -W * px / 2, -H * px / 2
        seg = self._segmentos(self.z_da_camada(k) + 1e-7)
        if seg is None:
            return None, 0, 0, W, H
        p1, p2, s = seg
        ya, yb = (p1[:, 1] - y0) / px - 0.5, (p2[:, 1] - y0) / px - 0.5
        j0 = np.ceil(np.minimum(ya, yb)).astype(np.int64)
        j1 = np.ceil(np.maximum(ya, yb)).astype(np.int64)
        j0, j1 = np.clip(j0, 0, H), np.clip(j1, 0, H)
        n = j1 - j0
        ok = n > 0
        if not ok.any():
            return None, 0, 0, W, H
        p1, p2, s, ya, yb, j0, n = p1[ok], p2[ok], s[ok], ya[ok], yb[ok], j0[ok], n[ok]
        idx = np.repeat(np.arange(len(n)), n)
        linhas = np.repeat(j0, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
        xa, xb = (p1[idx, 0] - x0) / px - 0.5, (p2[idx, 0] - x0) / px - 0.5
        f = (linhas - ya[idx]) / (yb[idx] - ya[idx])
        col = np.clip(np.ceil(xa + f * (xb - xa)).astype(np.int64), 0, W)
        r0, r1 = linhas.min(), linhas.max() + 1
        c0, c1 = col.min(), col.max() + 1
        dif = np.zeros((r1 - r0, c1 - c0 + 1), np.int16)
        np.add.at(dif, (linhas - r0, col - c0), s[idx])
        img = np.cumsum(dif, axis=1, dtype=np.int16)[:, :-1] > 0
        if ativas is not None:
            img &= self._mascara(ativas, r0, c0, img.shape, escala)
        return img, int(r0), int(c0), W, H

    def _mascara(self, ativas, r0, c0, forma, escala):
        return np.ones(forma, bool)

    def area_mm2(self, k, escala=4):
        img, *_ = self.camada(k, escala)
        if img is None:
            return 0.0
        return float(img.sum()) * (self.imp["pixel"] * escala) ** 2

    # ------------------------------------------------------------ estimativas
    def tempos_regioes(self, k):
        """Exposição de cada região nesta camada (impressão normal: uma região só)."""
        return [self.perfil.exposicao_da_camada(k)]

    def tempo_camada(self, k):
        p = self.perfil
        _, mov = p.movimento(k)
        ts = sorted(set(self.tempos_regioes(k)))
        trocas = len(ts) - 1
        return max(ts) + p.espera_antes + p.espera_depois_expor + p.espera_depois_subir + mov + trocas * 0.2

    def tempo_total(self):
        return sum(self.tempo_camada(k) for k in range(self.n_camadas))

    def custo(self, volume_ml):
        return volume_ml / 1000 * self.perfil.preco_litro

    def peso_g(self, volume_ml):
        return volume_ml * self.perfil.densidade

    def volume_ml(self, amostras=60):
        if self.n_camadas == 0:
            return 0.0
        ks = np.unique(np.linspace(0, self.n_camadas - 1, min(amostras, self.n_camadas)).astype(int))
        media = np.mean([self.area_mm2(k) for k in ks])
        return media * self.perfil.altura_camada * self.n_camadas / 1000

    # ------------------------------------------------------------ imagem completa
    def plano(self):
        """Sequência de imagens: (k, ativas, tempo, primeira_da_camada). `ativas` = regiões acesas (None = todas)."""
        for k in range(self.n_camadas):
            yield k, None, self.perfil.exposicao_da_camada(k), True

    def camada_cinza(self, k, ativas=None):
        """Camada com bordas suavizadas (antialiasing): cada pixel recebe a fração coberta pela peça.
        Faz `aa` linhas de amostra por pixel e cobertura exata na horizontal. Devolve uint8 0-255 recortado."""
        aa = max(1, int(self.perfil.antialias))
        imp = self.imp
        W, H = imp["res_x"], imp["res_y"]
        px = imp["pixel"]
        x0, y0 = -W * px / 2, -H * px / 2
        seg = self._segmentos(self.z_da_camada(k) + 1e-7)
        if seg is None:
            return None, 0, 0, W, H
        p1, p2, s = seg
        ya, yb = (p1[:, 1] - y0) / px * aa - 0.5, (p2[:, 1] - y0) / px * aa - 0.5
        j0 = np.clip(np.ceil(np.minimum(ya, yb)).astype(np.int64), 0, H * aa)
        j1 = np.clip(np.ceil(np.maximum(ya, yb)).astype(np.int64), 0, H * aa)
        n = j1 - j0
        ok = n > 0
        if not ok.any():
            return None, 0, 0, W, H
        p1, p2, s, ya, yb, j0, n = p1[ok], p2[ok], s[ok], ya[ok], yb[ok], j0[ok], n[ok]
        idx = np.repeat(np.arange(len(n)), n)
        sub = np.repeat(j0, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
        xa, xb = (p1[idx, 0] - x0) / px, (p2[idx, 0] - x0) / px
        f = (sub - ya[idx]) / (yb[idx] - ya[idx])
        xc = np.clip(xa + f * (xb - xa), 0, W)
        r0 = (sub.min() // aa) * aa
        r1 = (sub.max() // aa + 1) * aa
        c0 = int(np.floor(xc.min()))
        c1 = int(np.floor(xc.max())) + 1
        piso = np.floor(xc).astype(np.int64)
        frac = (xc - piso).astype(np.float32)
        sinal = s[idx].astype(np.float32)
        dif = np.zeros((r1 - r0, c1 - c0 + 2), np.float32)
        np.add.at(dif, (sub - r0, piso - c0), sinal * (1 - frac))
        np.add.at(dif, (sub - r0, piso - c0 + 1), sinal * frac)
        cob = np.clip(np.cumsum(dif, axis=1)[:, :c1 - c0 + 1], 0, 1)
        cob = cob.reshape(-1, aa, cob.shape[1]).mean(axis=1)
        linha0 = int(r0 // aa)
        cob = cob[:, :max(0, min(cob.shape[1], W - c0))]
        if ativas is not None:
            cob = cob * self._mascara(ativas, linha0, c0, cob.shape, 1)
        return (cob * 255 + 0.5).astype(np.uint8), linha0, c0, W, H

    def png_camada(self, k, ativas=None):
        from PIL import Image
        if self.perfil.antialias > 1:
            img, r0, c0, W, H = self.camada_cinza(k, ativas)
            tela = Image.new("L", (W, H), 0)
        else:
            img, r0, c0, W, H = self.camada(k, 1, ativas)
            tela = Image.new("1", (W, H), 0)
        if img is not None and img.size:
            sub = np.flipud(img)            # imagem: linha 0 no alto
            topo = H - (r0 + img.shape[0])
            pedaco = Image.fromarray(sub)
            tela.paste(pedaco, (c0, topo))
        if self.perfil.espelhar:
            tela = tela.transpose(Image.FLIP_LEFT_RIGHT)
        buf = io.BytesIO()
        tela.save(buf, "PNG", optimize=False, compress_level=3)
        return buf.getvalue()


def _gcode(fat, nome, volume, passos):
    """passos: lista de (k, ativas, tempo, primeira) na ordem das imagens."""
    p, imp = fat.perfil, fat.imp
    W, H = imp["res_x"], imp["res_y"]
    mov0, _ = p.movimento(fat.n_camadas)
    movb, _ = p.movimento(0)
    L = [f";fileName:{nome}", f";machineType:{imp['nome']}", f";estimatedPrintTime:{int(fat.tempo_total())}",
         f";volume:{volume:.3f}", ";resin:normal", f";weight:{fat.peso_g(volume):.3f}",
         f";price:{fat.custo(volume):.2f}", f";layerHeight:{p.altura_camada}", f";normalExposureTime:{p.exposicao}",
         f";bottomLayExposureTime:{p.exposicao_base}", f";bottomLayerExposureTime:{p.exposicao_base}",
         f";normalDropSpeed:{p.vel_descida}", f";normalLayerLiftHeight:{p.subida}", ";zSlowUpDistance:0",
         f";normalLayerLiftSpeed:{p.vel_subida}", f";bottomLayCount:{p.camadas_base}",
         f";bottomLayerCount:{p.camadas_base}", f";mirror:{1 if p.espelhar else 0}", f";totalLayer:{len(passos)}",
         f";bottomLayerLiftHeight:{p.subida_base}", f";bottomLayerLiftSpeed:{p.vel_subida_base}",
         f";bottomLightOffTime:{p.espera_antes}", f";lightOffTime:{p.espera_antes}", ";bottomPWMLight:255",
         ";PWMLight:255", f";antiAliasLevel:{max(1, int(p.antialias))}", f";resolutionX:{W}", f";resolutionY:{H}",
         f";machineX:{W * imp['pixel']:.2f}", f";machineY:{H * imp['pixel']:.2f}", f";machineZ:{imp['altura']}",
         ";projectType:Normal", "", ";START_GCODE_BEGIN", "G21;", "G90;", "M106 S0;", "G28 Z0;",
         ";START_GCODE_END", ""]
    for n, (k, ativas, tempo, primeira) in enumerate(passos):
        z = round((k + 1) * p.altura_camada, 4)
        L += [f";LAYER_START:{n}", f";currPos:{z}", f'M6054 "{n + 1}.png";show Image']
        if primeira:
            mov, _ = p.movimento(k)
            for dz, v in mov:
                L.append(f"G0 Z{round(z + dz, 4)} F{v:g};")
            if p.espera_depois_subir:
                L.append(f"G4 P{int(p.espera_depois_subir * 1000)};")
            L.append(f"G4 P{int(p.espera_antes * 1000)};")
        else:
            L.append("G4 P200;")  # troca de imagem sem mover a mesa
        L += ["M106 S255;light on", f"G4 P{int(round(tempo * 1000))};", "M106 S0;light off"]
        if p.espera_depois_expor:
            L.append(f"G4 P{int(p.espera_depois_expor * 1000)};")
        L += [";LAYER_END", ""]
    L += [";END_GCODE_BEGIN", "M106 S0;", f"G1 Z{min(imp['altura'], fat.altura + 50):.1f} F25;", "M18;",
          ";END_GCODE_END", ""]
    return "\n".join(L)


def exportar_zip(fat, caminho, nome, preview_png=None, progresso=None, cancelado=None):
    """Grava no formato ZIP do ChituBox (imagens PNG + run.gcode)."""
    volume = fat.volume_ml()
    passos = list(fat.plano())
    tmp = caminho + ".parcial"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        z.writestr("run.gcode", _gcode(fat, nome, volume, passos))
        if preview_png:
            z.writestr("preview.png", preview_png)
            z.writestr("preview_cropping.png", preview_png)
        with ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1)) as ex:
            lote = 16
            for ini in range(0, len(passos), lote):
                if cancelado and cancelado():
                    break
                grupo = passos[ini:ini + lote]
                pngs = ex.map(lambda x: fat.png_camada(x[0], x[1]), grupo)
                for n, png in zip(range(ini, ini + len(grupo)), pngs):
                    z.writestr(f"{n + 1}.png", png)
                if progresso:
                    progresso(int(min(ini + lote, len(passos)) * 100 / max(len(passos), 1)))
    if cancelado and cancelado():
        os.remove(tmp)
        return False
    if os.path.exists(caminho):
        os.remove(caminho)
    os.rename(tmp, caminho)
    return True
