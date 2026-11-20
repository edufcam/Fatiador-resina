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
        "altura_camada": 0.05, "exposicao": 2.5, "exposicao_base": 25.0, "camadas_base": 6,
        "luz_apagada": 0.5, "subida": 5.0, "vel_subida": 65.0, "vel_descida": 150.0,
        "subida_base": 5.0, "vel_subida_base": 65.0, "espelhar": False,
    }

    def __init__(self, **kw):
        for k, v in self.CAMPOS.items():
            setattr(self, k, kw.get(k, v))

    def para_dict(self):
        return {k: getattr(self, k) for k in self.CAMPOS}


class Fatiador:
    def __init__(self, malhas, perfil, impressora=IMPRESSORA):
        self.perfil, self.imp = perfil, impressora
        tris, sinais = [], []
        for m in malhas:
            if m is None or not len(m.faces):
                continue
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

    def camada(self, k, escala=1):
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
        return img, int(r0), int(c0), W, H

    def area_mm2(self, k, escala=4):
        img, *_ = self.camada(k, escala)
        if img is None:
            return 0.0
        return float(img.sum()) * (self.imp["pixel"] * escala) ** 2

    # ------------------------------------------------------------ estimativas
    def tempo_camada(self, k):
        p = self.perfil
        base = k < p.camadas_base
        exp = p.exposicao_base if base else p.exposicao
        sub = p.subida_base if base else p.subida
        vs = p.vel_subida_base if base else p.vel_subida
        return exp + p.luz_apagada + sub / vs * 60 + sub / p.vel_descida * 60

    def tempo_total(self):
        return sum(self.tempo_camada(k) for k in range(self.n_camadas))

    def volume_ml(self, amostras=60):
        if self.n_camadas == 0:
            return 0.0
        ks = np.unique(np.linspace(0, self.n_camadas - 1, min(amostras, self.n_camadas)).astype(int))
        media = np.mean([self.area_mm2(k) for k in ks])
        return media * self.perfil.altura_camada * self.n_camadas / 1000

    # ------------------------------------------------------------ imagem completa
    def png_camada(self, k):
        from PIL import Image
        img, r0, c0, W, H = self.camada(k, 1)
        tela = Image.new("1", (W, H), 0)
        if img is not None:
            sub = np.flipud(img)            # imagem: linha 0 no alto
            topo = H - (r0 + img.shape[0])
            pedaco = Image.fromarray(sub)
            tela.paste(pedaco, (c0, topo))
        if self.perfil.espelhar:
            tela = tela.transpose(Image.FLIP_LEFT_RIGHT)
        buf = io.BytesIO()
        tela.save(buf, "PNG", optimize=False, compress_level=3)
        return buf.getvalue()


def _gcode(fat, nome, volume):
    p, imp = fat.perfil, fat.imp
    W, H = imp["res_x"], imp["res_y"]
    L = [f";fileName:{nome}", f";machineType:{imp['nome']}", f";estimatedPrintTime:{int(fat.tempo_total())}",
         f";volume:{volume:.3f}", ";resin:normal", f";weight:{volume * 1.1:.3f}", ";price:0",
         f";layerHeight:{p.altura_camada}", f";normalExposureTime:{p.exposicao}",
         f";bottomLayExposureTime:{p.exposicao_base}", f";bottomLayerExposureTime:{p.exposicao_base}",
         f";normalDropSpeed:{p.vel_descida}", f";normalLayerLiftHeight:{p.subida}", ";zSlowUpDistance:0",
         f";normalLayerLiftSpeed:{p.vel_subida}", f";bottomLayCount:{p.camadas_base}",
         f";bottomLayerCount:{p.camadas_base}", f";mirror:{1 if p.espelhar else 0}", f";totalLayer:{fat.n_camadas}",
         f";bottomLayerLiftHeight:{p.subida_base}", f";bottomLayerLiftSpeed:{p.vel_subida_base}",
         f";bottomLightOffTime:{p.luz_apagada}", f";lightOffTime:{p.luz_apagada}", ";bottomPWMLight:255",
         ";PWMLight:255", ";antiAliasLevel:1", f";resolutionX:{W}", f";resolutionY:{H}",
         f";machineX:{W * imp['pixel']:.2f}", f";machineY:{H * imp['pixel']:.2f}", f";machineZ:{imp['altura']}",
         ";projectType:Normal", "", ";START_GCODE_BEGIN", "G21;", "G90;", "M106 S0;", "G28 Z0;",
         ";START_GCODE_END", ""]
    for k in range(fat.n_camadas):
        base = k < p.camadas_base
        z = round((k + 1) * p.altura_camada, 4)
        sub = p.subida_base if base else p.subida
        vs = p.vel_subida_base if base else p.vel_subida
        exp = p.exposicao_base if base else p.exposicao
        L += [f";LAYER_START:{k}", f";currPos:{z}", f'M6054 "{k + 1}.png";show Image',
              f"G0 Z{round(z + sub, 4)} F{vs};", f"G0 Z{z} F{p.vel_descida};",
              f"G4 P{int(p.luz_apagada * 1000)};", "M106 S255;light on", f"G4 P{int(exp * 1000)};",
              "M106 S0;light off", ";LAYER_END", ""]
    L += [";END_GCODE_BEGIN", "M106 S0;", f"G1 Z{min(imp['altura'], fat.altura + 50):.1f} F25;", "M18;",
          ";END_GCODE_END", ""]
    return "\n".join(L)


def exportar_zip(fat, caminho, nome, preview_png=None, progresso=None, cancelado=None):
    """Grava no formato ZIP do ChituBox (imagens PNG + run.gcode)."""
    volume = fat.volume_ml()
    tmp = caminho + ".parcial"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        z.writestr("run.gcode", _gcode(fat, nome, volume))
        if preview_png:
            z.writestr("preview.png", preview_png)
            z.writestr("preview_cropping.png", preview_png)
        with ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1)) as ex:
            lote = 16
            for ini in range(0, fat.n_camadas, lote):
                if cancelado and cancelado():
                    break
                ks = range(ini, min(ini + lote, fat.n_camadas))
                for k, png in zip(ks, ex.map(fat.png_camada, ks)):
                    z.writestr(f"{k + 1}.png", png)
                if progresso:
                    progresso(int(min(ini + lote, fat.n_camadas) * 100 / max(fat.n_camadas, 1)))
    if cancelado and cancelado():
        os.remove(tmp)
        return False
    if os.path.exists(caminho):
        os.remove(caminho)
    os.rename(tmp, caminho)
    return True
