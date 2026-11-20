"""Arquivo .ctb (ChituBox, versão 5) para a Elegoo Saturn 2 8K.

Estrutura conferida com um arquivo real fatiado no ChituBox: as 264 camadas do exemplo, decodificadas e
codificadas de novo por este módulo, saem idênticas byte a byte."""
import struct
import time
from concurrent.futures import ThreadPoolExecutor
import os

import numpy as np

MAGICO = 0x12FD0086
VERSAO_CTB = 5
CHAVE = 0x21468535
NOME_MAQUINA = b"ELEGOO Saturn 2"
# Blocos fixos copiados do arquivo de exemplo do ChituBox (campos variáveis são preenchidos abaixo)
_CABECALHO = b'\x86\x00\xfd\x12\x05\x00\x00\x00H\xe1ZCq=\xf6B\x00\x00zC\x00\x00\x00\x00\x00\x00\x00\x0033SA\xcd\xccL=\x00\x00 @\x00\x00pA\x00\x00\x00\x00\x0c\x00\x00\x00\x00\x1e\x00\x00\xe0\x10\x00\x00p\x00\x00\x002\xd7\x00\x00\x08\x01\x00\x00\xa2\xae\x00\x00\x92\x0c\x00\x00\x01\x00\x00\x00T\xd3\x00\x00<\x00\x00\x00\x01\x00\x00\x00\xff\x00\xff\x005\x85F!\x90\xd3\x00\x00L\x00\x00\x00'
_SLICER = b'\x00\x00\x80@\x00\x004C\x00\x00\x80@\x00\x004C\x00\x00\xc0?\x00\x00\x82B\x00\x00\x00\x00\xdc\xd3\x00\x00\x0f\x00\x00\x00\x0f\x00\x00\x00N\x00\xc1\x01\x08\x00\x00\x00\x00\x00\t\x01\x00\x00\x00?\x00\x00\x00\x00\x07\x00\x00\x00+\xd5\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
_AVISO = b'Layout and record format for the ctb and cbddlp file types are the copyrighted programs or codes of CBD Technology (China) Inc..The Customer or User shall not in any manner reproduce, distribute, modify, decompile, disassemble, decrypt, extract, reverse engineer, lease, assign, or sublicense the said programs or codes.'
_V4 = b'\x00\x004C\x00\x00\x82B\x00\x00\x00\x00\x00\x00\x80@\x00\x00\x00\x00\x00\x00\x80@\x00\x00\x00?\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc0?\x00\x00\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x07\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xeb\xd3\x00\x00@\x01\x00\x00\xfb\xd6\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
_RESINA = b'\x00\x00\x00\x00\x00\x00\x00\x00#\xd7\x00\x00\x00\x00\x00\x00#\xd7\x00\x00\x00\x00\x00\x00#\xd7\x00\x00\x0f\x00\x00\x00\xcd\xcc\x8c?\x00\x00\x00\x00'


# ---------------------------------------------------------------- codificação
def cripto(dados, chave, camada):
    """Embaralhamento das camadas (XOR com chave por camada). Aplicar duas vezes devolve o original."""
    if chave == 0:
        return bytes(dados)
    M = 0xFFFFFFFF
    ini = (chave * 0x2d83cdac + 0xd8a83423) & M
    k = ((((camada * 0x1e1530cd) & M) + 0xec3d47cd) & M) * ini & M
    n = len(dados)
    ks = (k + np.arange((n + 3) // 4, dtype=np.uint64) * ini) & M
    fluxo = ks.astype("<u4").view(np.uint8)[:n]
    return (np.frombuffer(dados, np.uint8) ^ fluxo).tobytes()


def rle_codificar(img):
    """Imagem uint8 (0-255) -> RLE da camada: cor de 7 bits; bit 0x80 indica que vem o tamanho da corrida."""
    c = (np.asarray(img, np.uint8).ravel() >> 1).astype(np.uint8)
    corte = np.flatnonzero(c[1:] != c[:-1]) + 1
    ini = np.r_[0, corte]
    tam = np.diff(np.r_[ini, len(c)]).astype(np.int64)
    cor = c[ini]
    nb = np.where(tam == 1, 1, 1 + np.where(tam < 0x80, 1, np.where(tam < 0x4000, 2, np.where(tam < 0x200000, 3, 4))))
    pos = np.r_[0, np.cumsum(nb)[:-1]]
    out = np.zeros(int(nb.sum()), np.uint8)
    out[pos] = np.where(tam > 1, cor | 0x80, cor)
    for n_, bits, pref in ((2, (0,), 0x00), (3, (8, 0), 0x80), (4, (16, 8, 0), 0xC0), (5, (24, 16, 8, 0), 0xE0)):
        m = nb == n_
        if not m.any():
            continue
        for j, b in enumerate(bits):
            v = (tam[m] >> b) & 0xFF
            out[pos[m] + 1 + j] = (v | pref) if j == 0 else v
    return out.tobytes()


def rle_decodificar(b, total):
    out = np.zeros(total, np.uint8)
    i = pos = 0
    n = len(b)
    while i < n:
        c = b[i]
        i += 1
        cor = c & 0x7F
        run = 1
        if c & 0x80:
            x = b[i]
            i += 1
            if (x & 0x80) == 0:
                run = x
            elif (x & 0xC0) == 0x80:
                run = ((x & 0x3F) << 8) | b[i]
                i += 1
            elif (x & 0xE0) == 0xC0:
                run = ((x & 0x1F) << 16) | (b[i] << 8) | b[i + 1]
                i += 2
            else:
                run = ((x & 0x0F) << 24) | (b[i] << 16) | (b[i + 1] << 8) | b[i + 2]
                i += 3
        out[pos:pos + run] = (cor << 1) | (cor & 1)
        pos += run
    return out, pos


def previa_codificar(rgb):
    """(h, w, 3) uint8 -> prévia RLE de 16 bits (RGB 5-5-5; bit 0x20 = corrida de até 4096)."""
    rgb = np.asarray(rgb, np.uint8)
    v = (((rgb[..., 0].astype(np.uint16) >> 3) << 11) | ((rgb[..., 1].astype(np.uint16) >> 3) << 6)
         | (rgb[..., 2].astype(np.uint16) >> 3)).ravel()
    corte = np.flatnonzero(v[1:] != v[:-1]) + 1
    ini = np.r_[0, corte]
    tam = np.diff(np.r_[ini, len(v)])
    out = []
    for s, t in zip(ini, tam):
        cor = int(v[s])
        while t > 0:
            r = min(t, 4096)
            out += [cor | 0x20, (r - 1) | 0x3000] if r > 1 else [cor]
            t -= r
    return np.array(out, "<u2").tobytes()


def _imagem_previa(rgb, w, h):
    from PIL import Image
    tela = Image.new("RGB", (w, h), (0, 0, 0))
    if rgb is not None:
        im = Image.fromarray(np.asarray(rgb, np.uint8)).convert("RGB")
        im.thumbnail((w, h))
        tela.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return np.asarray(tela)


# ---------------------------------------------------------------- gravação
def _mov(p, base, primeira):
    """Valores de movimento por camada no formato do CTB."""
    if not primeira:  # troca de imagem na mesma altura (calibração): sem mover a mesa
        return dict(sub=0.0, vsub=p.vel_subida, sub2=0.0, vsub2=0.0, vdesc=p.vel_descida, desc2=0.0, vdesc2=0.0,
                    antes_subir=0.0, depois_subir=0.0, depois_descer=0.0)
    D = p.subida_base if base else p.subida
    v1 = p.vel_subida_base if base else p.vel_subida
    duas = p.duas_etapas and p.dist_lenta < D
    return dict(sub=D, vsub=v1, sub2=(D - p.dist_lenta) if duas else 0.0, vsub2=p.vel_subida_rapida if duas else 0.0,
                vdesc=p.vel_descida, desc2=min(p.dist_descida_lenta, D) if duas else 0.0,
                vdesc2=p.vel_descida_lenta if duas else 0.0, antes_subir=p.espera_depois_expor,
                depois_subir=p.espera_depois_subir, depois_descer=p.espera_antes)


def gravar(fat, caminho, previa_rgb=None, progresso=None, cancelado=None, chave=CHAVE):
    """Grava o fatiamento `fat` (Fatiador ou FatiadorCalibracao) como .ctb."""
    p, imp = fat.perfil, fat.imp
    W, H = imp["res_x"], imp["res_y"]
    passos = list(fat.plano())
    n = len(passos)
    volume = fat.volume_ml()
    agora_min = int(time.time() // 60)

    grande = previa_codificar(_imagem_previa(previa_rgb, 400, 300))
    pequena = previa_codificar(_imagem_previa(previa_rgb, 200, 125))
    o_pg = 112
    o_pp = o_pg + 32 + len(grande)
    o_par = o_pp + 32 + len(pequena)
    o_sl = o_par + 60
    o_nome = o_sl + 76
    o_aviso = o_nome + len(NOME_MAQUINA)
    o_v4 = o_aviso + len(_AVISO)
    o_res = o_v4 + len(_V4)
    o_nome2 = o_res + len(_RESINA)
    o_tab = o_nome2 + len(NOME_MAQUINA)
    o_dados = o_tab + 36 * n

    mb, mn = _mov(p, True, True), _mov(p, False, True)
    cab = bytearray(_CABECALHO)
    struct.pack_into("<2I3f2I", cab, 0, MAGICO, VERSAO_CTB, W * imp["pixel"], H * imp["pixel"], imp["altura"], 0, 0)
    struct.pack_into("<5fI2I", cab, 28, round(fat.n_camadas * p.altura_camada, 4), p.altura_camada, p.exposicao,
                     p.exposicao_base, 0.0, p.camadas_base, W, H)
    struct.pack_into("<9I", cab, 60, o_pg, o_tab, n, o_pp, int(fat.tempo_total()), 1, o_par, 60,
                     max(1, int(p.antialias)))
    struct.pack_into("<2HI2I", cab, 96, 255, 255, chave, o_sl, 76)

    par = struct.pack("<10f5I", mb["sub"], mb["vsub"], mn["sub"], mn["vsub"], mn["vdesc"], volume,
                      fat.peso_g(volume), fat.custo(volume), 0.0, 0.0, p.camadas_base, 0, 0, 0, 0)
    sl = bytearray(_SLICER)
    struct.pack_into("<6f", sl, 0, mb["sub2"], mb["vsub2"], mn["sub2"], mn["vsub2"], mn["desc2"], mn["vdesc2"])
    struct.pack_into("<f2I", sl, 24, mn["depois_subir"], o_nome, len(NOME_MAQUINA))
    struct.pack_into("<I", sl, 40, agora_min)
    struct.pack_into("<f", sl, 52, mn["depois_descer"])
    struct.pack_into("<2I", sl, 60, int(p.camadas_transicao), o_v4)
    v4 = bytearray(_V4)
    struct.pack_into("<2f", v4, 0, mb["vdesc"], mb["vdesc2"])
    struct.pack_into("<4f", v4, 24, mb["depois_descer"], mb["depois_subir"], mb["antes_subir"], mb["desc2"])
    struct.pack_into("<I", v4, 52, max(n - 1, 0))
    struct.pack_into("<3I", v4, 72, o_aviso, len(_AVISO), o_res)
    res = bytearray(_RESINA)
    struct.pack_into("<I", res, 8, o_nome2)
    struct.pack_into("<I", res, 16, o_nome2)
    struct.pack_into("<2If", res, 24, o_nome2, len(NOME_MAQUINA), float(p.densidade))

    def camada_bytes(i):
        k, ativas, tempo, primeira = passos[i]
        if p.antialias > 1:
            img, r0, c0, _, _ = fat.camada_cinza(k, ativas)
            val = img
        else:
            img, r0, c0, _, _ = fat.camada(k, 1, ativas)
            val = None if img is None else img.astype(np.uint8) * 255
        tela = np.zeros((H, W), np.uint8)
        if val is not None and val.size:
            sub = np.flipud(val)
            topo = H - (r0 + val.shape[0])
            tela[topo:topo + sub.shape[0], c0:c0 + sub.shape[1]] = sub
        if p.espelhar:
            tela = tela[:, ::-1]
        return cripto(rle_codificar(tela), chave, i)

    tmp = caminho + ".parcial"
    with open(tmp, "wb") as f:
        f.write(cab)
        f.write(struct.pack("<8I", 400, 300, o_pg + 32, len(grande), 0, 0, 0, 0) + grande)
        f.write(struct.pack("<8I", 200, 125, o_pp + 32, len(pequena), 0, 0, 0, 0) + pequena)
        f.write(par + sl + NOME_MAQUINA + _AVISO + v4 + res + NOME_MAQUINA)
        assert f.tell() == o_tab
        f.write(b"\0" * 36 * n)  # tabela, preenchida no fim
        tabela = []
        endereco = o_dados
        with ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1)) as ex:
            lote = 16
            for ini in range(0, n, lote):
                if cancelado and cancelado():
                    break
                ids = list(range(ini, min(ini + lote, n)))
                for i, dados in zip(ids, ex.map(camada_bytes, ids)):
                    k, ativas, tempo, primeira = passos[i]
                    base = k < p.camadas_base
                    m = _mov(p, base, primeira)
                    z = round((k + 1) * p.altura_camada, 4)
                    defin = struct.pack("<3f6I", z, tempo, 0.0, endereco + 84, len(dados), 0, 84, 0, 0)
                    extra = struct.pack("<I11f", 84 + len(dados), m["sub"], m["vsub"], m["sub2"], m["vsub2"],
                                        m["vdesc"], m["desc2"], m["vdesc2"], m["antes_subir"], m["depois_subir"],
                                        m["depois_descer"], 255.0)
                    f.write(defin + extra + dados)
                    tabela.append(defin)
                    endereco += 84 + len(dados)
                if progresso:
                    progresso(int(min(ini + lote, n) * 100 / max(n, 1)))
        if not (cancelado and cancelado()):
            f.seek(o_tab)
            f.write(b"".join(tabela))
    if cancelado and cancelado():
        os.remove(tmp)
        return False
    if os.path.exists(caminho):
        os.remove(caminho)
    os.rename(tmp, caminho)
    return True


# ---------------------------------------------------------------- leitura (para conferir)
def ler(caminho):
    d = open(caminho, "rb").read()
    h = struct.unpack_from("<2I3f2I5f3I9I2HI2I", d, 0)
    info = dict(magico=h[0], versao=h[1], mesa=h[2:5], altura=h[7], camada=h[8], exposicao=h[9], base=h[10],
                camadas_base=h[12], res=(h[13], h[14]), n=h[17], tempo=h[19], aa=h[23], chave=h[26])
    tab = h[16]
    info["camadas"] = [struct.unpack_from("<3f6I", d, tab + i * 36) for i in range(info["n"])]
    info["extras"] = [struct.unpack_from("<I11f", d, c[3] - 84 + 36) for c in info["camadas"]]
    sl = h[27]
    info["slicer"] = struct.unpack_from("<6ff2I", d, sl)
    info["nome"] = d[info["slicer"][7]:info["slicer"][7] + info["slicer"][8]]
    info["parametros"] = struct.unpack_from("<10f5I", d, h[21])

    def imagem(i):
        z, exp, _, ad, tam, *_ = info["camadas"][i]
        img, pos = rle_decodificar(cripto(d[ad:ad + tam], info["chave"], i), info["res"][0] * info["res"][1])
        return img.reshape(info["res"][1], info["res"][0]), pos
    info["imagem"] = imagem
    return info
