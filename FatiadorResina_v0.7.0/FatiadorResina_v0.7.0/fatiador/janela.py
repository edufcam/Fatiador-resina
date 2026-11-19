"""Janela principal do Fatiador Resina."""
import os
import sys
import threading
import traceback

import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt, QSize, QSettings, QTimer, QObject, Signal, QLocale
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QListWidget, QListWidgetItem, QPushButton, QToolButton, QLabel, QDoubleSpinBox,
    QComboBox, QFileDialog, QMessageBox, QScrollArea, QSplitter, QStyleFactory, QTabWidget,
    QButtonGroup, QMenu, QInputDialog, QProgressDialog, QSizePolicy, QSlider, QCheckBox, QProgressBar,
)
from pyvistaqt import QtInteractor

from . import modelo as md
from . import encaixe as en
from . import suportes as su
from . import ocar as oc
from . import tema, atualizador, VERSAO, NOME
from .recursos import recurso, pasta_dados

EXTENSOES = (".stl", ".obj", ".3mf")
EXT_PROJETO = ".resina"


def br(v, casas=1):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def trimesh_align(eixo):
    import trimesh
    return trimesh.geometry.align_vectors([0, 0, 1], eixo)


def para_polydata(m):
    faces = np.hstack([np.full((len(m.faces), 1), 3, dtype=np.int64), m.faces.astype(np.int64)]).ravel()
    return pv.PolyData(np.asarray(m.vertices, dtype=float), faces)


def numero(minimo, maximo, valor, sufixo, dica, casas=2):
    s = QDoubleSpinBox()
    s.setRange(minimo, maximo)
    s.setDecimals(casas)
    s.setValue(valor)
    s.setSuffix(sufixo)
    s.setToolTip(dica)
    return s


def rotulo(texto, nome="rotulo"):
    l = QLabel(texto)
    l.setObjectName(nome)
    return l


class Sinais(QObject):
    nova_versao = Signal(dict)
    sem_novidade = Signal(bool)
    busca_falhou = Signal(str)
    progresso = Signal(int)
    baixado = Signal(str)
    falhou = Signal(str)
    ambiente_pronto = Signal(object)


class Trabalho(QObject):
    pronto = Signal(object)
    erro = Signal(str)


class ItemPeca(QWidget):
    def __init__(self, janela, indice):
        super().__init__()
        self.janela, self.indice = janela, indice
        p = janela.proj.pecas[indice]
        c = janela.cores
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 8, 6)
        lay.setSpacing(6)
        olho = QToolButton()
        olho.setIcon(tema.icone("olho" if p.visivel else "olho_fechado", c["texto" if p.visivel else "suave"], 18))
        olho.setToolTip("Mostrar ou ocultar esta peça")
        olho.clicked.connect(lambda: janela.alternar_visivel(indice))
        lay.addWidget(olho)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        nome = QLabel(p.nome)
        nome.setStyleSheet("font-weight: 600;" + ("" if p.visivel else f"color: {c['suave']};"))
        e = p.malha.extents
        dims = rotulo(f"{br(e[0])} × {br(e[1])} × {br(e[2])} mm")
        if not md.dentro_da_mesa(p.limites()):
            dims.setText(dims.text() + "   fora da mesa")
            dims.setStyleSheet(f"color: {c['perigo']};")
        textos.addWidget(nome)
        textos.addWidget(dims)
        lay.addLayout(textos, 1)
        if p.tem_suportes():
            sup = rotulo(f"{len(p.suportes)}")
            sup.setToolTip(f"{len(p.suportes)} suportes")
            sup.setPixmap(tema.icone("suporte", c["suave"], 14).pixmap(14, 14))
            lay.addWidget(sup)


class Janela(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NOME} {VERSAO}")
        self.resize(1440, 880)
        self.setAcceptDrops(True)
        self.config = QSettings("FatiadorResina", "FatiadorResina")
        self.escuro = self.config.value("tema_escuro", True, type=bool)
        self.cores = tema.ESCURO if self.escuro else tema.CLARO
        self.proj = md.Projeto()
        self.caminho_projeto = None
        self._nomes = set()
        self._modo_clique = None
        self._icones = []
        self._cache_atores = {}
        self._cache_faltas = {}
        self._ambientes = {}
        self._calculando = set()
        self._ocupado = False
        self._baixando = False
        self._trabalhos = set()
        self.sinais = Sinais()
        self.sinais.nova_versao.connect(self._oferecer_atualizacao)
        self.sinais.sem_novidade.connect(self._sem_atualizacao)
        self.sinais.busca_falhou.connect(lambda m: QMessageBox.warning(self, "Atualizações", m))
        self.sinais.progresso.connect(lambda v: self.av_barra.setValue(v))
        self.sinais.baixado.connect(self._download_ok)
        self.sinais.falhou.connect(self._download_falhou)
        self.sinais.ambiente_pronto.connect(lambda _: self.atualizar_tudo() if self.abas.currentIndex() == self.ABA_SUPORTES else None)

        self._montar()
        self._aplicar_tema()
        self.atualizar_tudo(resetar_camera=True, reconstruir=True)
        self.statusBar().showMessage("Arraste um arquivo STL, OBJ ou 3MF para a janela, ou clique em Importar.")
        QTimer.singleShot(600, self._novidades_desta_versao)
        if atualizador.pode_atualizar():
            QTimer.singleShot(4000, lambda: self.procurar_atualizacao(silencioso=True))
            self._timer_atualizacao = QTimer(self)
            self._timer_atualizacao.timeout.connect(lambda: self.procurar_atualizacao(silencioso=True))
            self._timer_atualizacao.start(6 * 60 * 60 * 1000)

    # ================================================================ montagem
    def _ic(self, widget, nome, tamanho=18):
        self._icones.append((widget, nome, tamanho))
        widget.setIconSize(QSize(tamanho, tamanho))

    def _botao_barra(self, texto, icone, dica, func, atalho=None, so_icone=False):
        b = QToolButton()
        b.setText(texto)
        b.setToolButtonStyle(Qt.ToolButtonIconOnly if so_icone else Qt.ToolButtonTextBesideIcon)
        b.setToolTip(dica + (f"  ({QKeySequence(atalho).toString(QKeySequence.NativeText)})" if atalho else ""))
        b.clicked.connect(func)
        self._ic(b, icone)
        if atalho:
            a = QAction(self)
            a.setShortcut(atalho)
            a.triggered.connect(func)
            self.addAction(a)
        return b

    def _botao(self, texto, dica, func, icone=None, principal=False):
        b = QPushButton(texto)
        b.setToolTip(dica)
        b.clicked.connect(func)
        b.setCursor(Qt.PointingHandCursor)
        if principal:
            b.setObjectName("principal")
        if icone:
            self._ic(b, icone, 16)
            b._principal = principal
        return b

    def _montar(self):
        raiz = QWidget()
        raiz.setObjectName("raiz")
        lr = QVBoxLayout(raiz)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(0)
        lr.addWidget(self._montar_cabecalho())
        self.aviso = self._montar_aviso()
        lr.addWidget(self.aviso)

        div = QSplitter(Qt.Horizontal)
        div.setHandleWidth(1)
        div.addWidget(self._montar_lateral())
        div.addWidget(self._montar_visor())
        div.addWidget(self._montar_painel())
        div.setSizes([270, 820, 350])
        div.setStretchFactor(1, 1)
        lr.addWidget(div, 1)
        self.setCentralWidget(raiz)
        self.resumo = QLabel()
        self.statusBar().addPermanentWidget(self.resumo)

    def _montar_cabecalho(self):
        cab = QWidget()
        cab.setObjectName("cabecalho")
        l = QHBoxLayout(cab)
        l.setContentsMargins(12, 6, 12, 6)
        l.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(QPixmap(recurso("logo.png")).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        l.addWidget(logo)
        l.addSpacing(6)
        l.addWidget(rotulo(NOME, "marca"))
        l.addSpacing(24)
        l.addWidget(self._botao_barra("Importar", "importar", "Abrir um arquivo STL, OBJ ou 3MF", self.importar, QKeySequence("Ctrl+I")))
        l.addWidget(self._botao_barra("Abrir", "abrir", "Abrir um projeto salvo (.resina)", lambda: self.abrir_projeto(), QKeySequence("Ctrl+O")))
        l.addWidget(self._botao_barra("Salvar", "salvar", "Salvar o projeto com todas as peças", self.salvar_projeto, QKeySequence("Ctrl+S")))
        l.addWidget(self._botao_barra("Exportar STL", "exportar", "Gerar o STL para fatiar no ChituBox", self.exportar, QKeySequence("Ctrl+E")))
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(22)
        l.addSpacing(8)
        l.addWidget(sep)
        l.addSpacing(8)
        l.addWidget(self._botao_barra("Desfazer", "desfazer", "Voltar a última alteração", self.desfazer, QKeySequence("Ctrl+Z")))
        l.addWidget(self._botao_barra("Refazer", "refazer", "Refazer o que foi desfeito", self.refazer, QKeySequence("Ctrl+Y")))
        l.addStretch(1)
        self.b_tema = self._botao_barra("Tema", "sol", "Trocar entre tema claro e escuro", self.trocar_tema, so_icone=True)
        l.addWidget(self.b_tema)
        l.addWidget(self._botao_barra("Atualizações", "atualizar", "Procurar versão nova do programa",
                                      lambda: self.procurar_atualizacao(False), so_icone=True))
        l.addWidget(self._botao_barra("Sobre", "info", "Sobre o programa", self.sobre, so_icone=True))
        return cab

    def _montar_lateral(self):
        lat = QWidget()
        lat.setObjectName("lateral")
        lat.setMinimumWidth(230)
        l = QVBoxLayout(lat)
        l.setContentsMargins(12, 12, 12, 12)
        l.setSpacing(8)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Peças", "titulo"))
        topo.addStretch(1)
        self.contagem = rotulo("")
        topo.addWidget(self.contagem)
        l.addLayout(topo)

        self.lista = QListWidget()
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_lista)
        self.lista.currentRowChanged.connect(lambda _: self.atualizar_tudo())
        self.lista.itemDoubleClicked.connect(lambda _: self.renomear())
        self.lista.setToolTip("Clique para selecionar. Dois cliques para renomear.\nBotão direito para mais opções.")
        l.addWidget(self.lista, 1)
        self.vazio = rotulo("Nenhuma peça ainda.\n\nArraste um arquivo para a janela ou clique em Importar peça.", "vazio")
        self.vazio.setWordWrap(True)
        self.vazio.setAlignment(Qt.AlignCenter)
        l.addWidget(self.vazio, 1)

        l.addWidget(self._botao("Importar peça", "Abrir um arquivo STL, OBJ ou 3MF", self.importar, "importar", True))
        linha = QHBoxLayout()
        linha.addWidget(self._botao("Duplicar", "Criar uma cópia da peça selecionada", self.duplicar, "copiar"))
        linha.addWidget(self._botao("Excluir", "Remover a peça selecionada (tecla Delete)", self.excluir, "lixo"))
        l.addLayout(linha)
        a = QAction(self)
        a.setShortcut(QKeySequence.Delete)
        a.triggered.connect(self.excluir)
        self.addAction(a)
        return lat

    def _montar_visor(self):
        caixa = QWidget()
        l = QVBoxLayout(caixa)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        barra = QFrame()
        barra.setObjectName("barra3d")
        lb = QHBoxLayout(barra)
        lb.setContentsMargins(12, 8, 12, 8)
        lb.setSpacing(0)
        grupo = QButtonGroup(self)
        for i, (txt, chave) in enumerate((("3D", "iso"), ("Topo", "topo"), ("Frente", "frente"), ("Lado", "lado"))):
            b = QToolButton()
            b.setText(txt)
            b.setObjectName("segmento")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setToolTip(f"Ver a mesa: {txt.lower()}")
            b.clicked.connect(lambda _=False, k=chave: self._vista(k))
            grupo.addButton(b)
            lb.addWidget(b)
        lb.addStretch(1)
        lb.addWidget(rotulo(f"Mesa {br(md.MESA_X, 0)} × {br(md.MESA_Y, 0)} mm, altura {br(md.MESA_Z, 0)} mm"))
        l.addWidget(barra)

        self.plotter = QtInteractor(caixa)
        self.plotter.enable_anti_aliasing("fxaa")
        self.plotter.add_axes(line_width=2, labels_off=False)
        l.addWidget(self.plotter.interactor, 1)
        dica = rotulo("Botão esquerdo: girar a vista     Rodinha: zoom     Shift + botão esquerdo: arrastar")
        dica.setContentsMargins(12, 6, 12, 6)
        l.addWidget(dica)
        return caixa

    def _montar_painel(self):
        painel = QWidget()
        painel.setObjectName("painel")
        painel.setMinimumWidth(380)
        l = QVBoxLayout(painel)
        l.setContentsMargins(12, 12, 12, 12)
        l.setSpacing(10)

        # cartão de informações
        cartao = QFrame()
        cartao.setObjectName("cartao")
        lc = QVBoxLayout(cartao)
        lc.setContentsMargins(14, 12, 14, 12)
        self.i_nome = rotulo("Nenhuma peça selecionada", "titulo")
        self.i_nome.setWordWrap(True)
        lc.addWidget(self.i_nome)
        grade = QGridLayout()
        grade.setHorizontalSpacing(12)
        self.i_med = {}
        for col, (chave, txt) in enumerate((("x", "Largura"), ("y", "Profundidade"), ("z", "Altura"))):
            n = rotulo("–", "numero")
            grade.addWidget(n, 0, col)
            grade.addWidget(rotulo(f"{txt} (mm)"), 1, col)
            self.i_med[chave] = n
        lc.addLayout(grade)
        lc.addSpacing(6)
        linha = QHBoxLayout()
        self.i_resina = rotulo("–", "numero")
        linha.addWidget(self.i_resina)
        linha.addWidget(rotulo("de resina"), 0, Qt.AlignBottom)
        linha.addStretch(1)
        lc.addLayout(linha)
        self.i_mesa = QLabel("")
        lc.addWidget(self.i_mesa)
        l.addWidget(cartao)

        # abas de ferramentas
        self.abas = QTabWidget()
        self.abas.addTab(self._aba_posicionar(), "Posição")
        self.ABA_CORTAR = self.abas.addTab(self._aba_cortar(), "Cortar")
        self.ABA_ENCAIXES = self.abas.addTab(self._aba_encaixes(), "Encaixes")
        self.ABA_SUPORTES = self.abas.addTab(self._aba_suportes(), "Suportes")
        self.ABA_OCAR = self.abas.addTab(self._aba_ocar(), "Ocar")
        self.abas.currentChanged.connect(self._aba_mudou)
        l.addWidget(self.abas, 1)
        return painel

    def _aba_posicionar(self):
        conteudo = QWidget()
        l = QVBoxLayout(conteudo)
        l.setContentsMargins(2, 10, 6, 10)
        l.setSpacing(8)

        l.addWidget(rotulo("Mover", "titulo"))
        g = QGridLayout()
        self.dx = numero(-500, 500, 0, " mm", "Para a direita (negativo = esquerda)")
        self.dy = numero(-500, 500, 0, " mm", "Para trás (negativo = para a frente)")
        self.dz = numero(-500, 500, 0, " mm", "Para cima (negativo = para baixo)")
        for i, (txt, campo) in enumerate((("X", self.dx), ("Y", self.dy), ("Z", self.dz))):
            g.addWidget(rotulo(txt), i, 0)
            g.addWidget(campo, i, 1)
        g.addWidget(self._botao("Mover", "Mover a peça pelas distâncias acima", self.mover, principal=True), 0, 2, 3, 1)
        l.addLayout(g)
        linha = QHBoxLayout()
        linha.addWidget(self._botao("Centralizar", "Pôr a peça no meio da mesa", self.centralizar, "centro"))
        linha.addWidget(self._botao("Deitar na mesa", "Encostar o ponto mais baixo da peça na mesa", self.deitar, "deitar"))
        l.addLayout(linha)
        l.addWidget(self._botao("Organizar todas na mesa", "Arrumar todas as peças visíveis lado a lado",
                                self.organizar_mesa, "grade"))

        l.addSpacing(6)
        l.addWidget(rotulo("Girar", "titulo"))
        g = QGridLayout()
        for col, eixo in enumerate("XYZ"):
            g.addWidget(self._botao(f"{eixo} +90°", f"Girar 90° no eixo {eixo}", lambda _=False, e=eixo: self.girar(e, 90)), 0, col)
            g.addWidget(self._botao(f"{eixo} −90°", f"Girar −90° no eixo {eixo}", lambda _=False, e=eixo: self.girar(e, -90)), 1, col)
        self.eixo = QComboBox()
        self.eixo.addItems(["Eixo X", "Eixo Y", "Eixo Z"])
        self.angulo = numero(-360, 360, 30, "°", "Ângulo do giro", 1)
        g.addWidget(self.eixo, 2, 0)
        g.addWidget(self.angulo, 2, 1)
        g.addWidget(self._botao("Girar", "Girar pelo ângulo escolhido",
                                lambda: self.girar(self.eixo.currentText()[-1], self.angulo.value())), 2, 2)
        l.addLayout(g)

        l.addSpacing(6)
        l.addWidget(rotulo("Tamanho", "titulo"))
        linha = QHBoxLayout()
        self.escala = numero(1, 2000, 100, " %", "100% = tamanho original. 50% = metade. 200% = dobro.", 1)
        linha.addWidget(self.escala, 1)
        linha.addWidget(self._botao("Aplicar", "Mudar o tamanho da peça", self.escalar))
        l.addLayout(linha)

        l.addSpacing(6)
        l.addWidget(rotulo("Orientação automática", "titulo"))
        explica = rotulo("Gira a peça para ter menos partes penduradas e menos faces planas viradas "
                         "para baixo, que grudam no filme FEP.")
        explica.setWordWrap(True)
        l.addWidget(explica)
        l.addWidget(self._botao("Sugerir melhor posição", "Calcula e aplica. Ctrl+Z desfaz.", self.orientar, "varinha", True))
        l.addStretch(1)

        rol = QScrollArea()
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        return rol


    # ================================================================ aba cortar
    def _aba_cortar(self):
        conteudo = QWidget()
        l = QVBoxLayout(conteudo)
        l.setContentsMargins(2, 10, 6, 10)
        l.setSpacing(8)
        explica = rotulo("Escolha a direção, arraste a posição e confira a prévia em âmbar antes de cortar. "
                         "As faces cortadas são fechadas automaticamente.")
        explica.setWordWrap(True)
        l.addWidget(explica)

        l.addWidget(rotulo("Direção do corte", "titulo"))
        self.c_modo = QComboBox()
        self.c_modo.addItem("Horizontal (fatia na altura)", "horizontal")
        self.c_modo.addItem("Vertical, da esquerda para a direita", "x")
        self.c_modo.addItem("Vertical, da frente para trás", "y")
        self.c_modo.addItem("Inclinado", "inclinado")
        self.c_modo.currentIndexChanged.connect(self._modo_corte_mudou)
        l.addWidget(self.c_modo)

        self.c_incl_caixa = QWidget()
        gi = QGridLayout(self.c_incl_caixa)
        gi.setContentsMargins(0, 0, 0, 0)
        self.c_incl = numero(0, 90, 30, "°", "0° = corte horizontal, 90° = corte em pé", 0)
        self.c_dir = numero(0, 360, 0, "°", "Gira o plano de corte em volta da peça", 0)
        gi.addWidget(rotulo("Inclinação"), 0, 0)
        gi.addWidget(self.c_incl, 0, 1)
        gi.addWidget(rotulo("Girar o plano"), 1, 0)
        gi.addWidget(self.c_dir, 1, 1)
        self.c_incl.valueChanged.connect(self._direcao_mudou)
        self.c_dir.valueChanged.connect(self._direcao_mudou)
        self.c_incl_caixa.setVisible(False)
        l.addWidget(self.c_incl_caixa)

        l.addSpacing(4)
        l.addWidget(rotulo("Posição do corte", "titulo"))
        self.c_slider = QSlider(Qt.Horizontal)
        self.c_slider.setRange(0, 1000)
        self.c_slider.setValue(500)
        self.c_slider.setToolTip("Arraste para mudar onde a peça vai ser cortada")
        l.addWidget(self.c_slider)
        linha = QHBoxLayout()
        self.c_pos = numero(0, 1000, 0, " mm", "Distância do corte a partir da base (ou da borda) da peça")
        linha.addWidget(self.c_pos, 1)
        linha.addWidget(self._botao("No meio", "Pôr o corte no meio da peça", lambda: self.c_slider.setValue(500)))
        l.addLayout(linha)
        self._sincronizando = False
        self.c_slider.valueChanged.connect(self._slider_mudou)
        self.c_pos.valueChanged.connect(self._pos_mudou)
        self.c_info = rotulo("")
        self.c_info.setWordWrap(True)
        l.addWidget(self.c_info)

        l.addSpacing(4)
        l.addWidget(rotulo("Depois de cortar", "titulo"))
        self.c_encaixe = QCheckBox("Criar encaixes (pinos e furos)")
        self.c_encaixe.setChecked(True)
        self.c_encaixe.setToolTip("Os pinos aparecem em verde na prévia. Ajuste tipo, tamanho e folga na aba Encaixes.")
        self.c_encaixe.toggled.connect(lambda _: self._agendar_previa())
        l.addWidget(self.c_encaixe)
        self.c_organizar = QCheckBox("Organizar as partes lado a lado na mesa")
        self.c_organizar.setChecked(True)
        self.c_deitar = QCheckBox("Deitar a face cortada virada para a mesa")
        self.c_deitar.setToolTip("Bom para peças com base reta. Cada parte fica apoiada pela face do corte.\n"
                                 "A parte com pinos não é deitada pela face, porque os pinos ficam nela.")
        self.c_soltos = QCheckBox("Separar pedaços soltos em peças diferentes")
        self.c_soltos.setChecked(True)
        self.c_soltos.setToolTip("Se o corte gerar pedaços que não se tocam, cada um vira uma peça na lista")
        for cb in (self.c_organizar, self.c_deitar, self.c_soltos):
            l.addWidget(cb)
        l.addSpacing(6)
        l.addWidget(self._botao("Cortar peça", "Cortar no plano mostrado. Ctrl+Z desfaz.", self.cortar, "tesoura", True))
        l.addStretch(1)
        rol = QScrollArea()
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        self._timer_previa = QTimer(self)
        self._timer_previa.setSingleShot(True)
        self._timer_previa.timeout.connect(self._desenhar_previa)
        return rol

    def _normal_corte(self):
        return md.normal_do_corte(self.c_modo.currentData(), self.c_incl.value(), self.c_dir.value())

    def _faixa_corte(self):
        p = self.peca(avisar=False)
        if p is None:
            return None
        return md.faixa_na_direcao(p.malha, self._normal_corte())

    def _ajustar_limites_corte(self):
        f = self._faixa_corte()
        if f is None:
            return
        tamanho = max(f[1] - f[0], 0.01)
        self._sincronizando = True
        self.c_pos.setRange(0, tamanho)
        self.c_pos.setValue(tamanho * self.c_slider.value() / 1000)
        self._sincronizando = False

    def _modo_corte_mudou(self):
        self.c_incl_caixa.setVisible(self.c_modo.currentData() == "inclinado")
        self._direcao_mudou()

    def _direcao_mudou(self):
        self._ajustar_limites_corte()
        self._agendar_previa()

    def _slider_mudou(self, v):
        if self._sincronizando:
            return
        self._sincronizando = True
        self.c_pos.setValue(self.c_pos.maximum() * v / 1000)
        self._sincronizando = False
        self._agendar_previa()

    def _pos_mudou(self, v):
        if self._sincronizando:
            return
        self._sincronizando = True
        mx = self.c_pos.maximum() or 1
        self.c_slider.setValue(int(round(1000 * v / mx)))
        self._sincronizando = False
        self._agendar_previa()

    def _agendar_previa(self):
        if hasattr(self, "_timer_previa"):
            self._timer_previa.start(120)

    def _apagar_previa(self):
        for nome in ("previa_plano", "previa_contorno", "previa_pinos"):
            self.plotter.remove_actor(nome, render=False)
        self._plano_encaixe = None

    def _desenhar_previa(self):
        self._apagar_previa()
        if hasattr(self, "e_info"):
            self.e_info.setText("")
        p = self.peca(avisar=False)
        if self.abas.currentIndex() not in (self.ABA_CORTAR, getattr(self, "ABA_ENCAIXES", -1)) \
                or p is None or not p.visivel:
            self.c_info.setText("" if p is not None else "Selecione uma peça na lista para cortar.")
            self.plotter.render()
            return
        c = self.cores
        n = self._normal_corte()
        lo, _ = md.faixa_na_direcao(p.malha, n)
        desloc = lo + self.c_pos.value()
        origem = md.ponto_do_plano(p.malha, n, desloc)
        tam = float(np.linalg.norm(p.malha.extents)) * 1.15
        self.plotter.add_mesh(pv.Plane(center=origem, direction=n, i_size=tam, j_size=tam),
                              color=c["destaque"], opacity=0.28, name="previa_plano", pickable=False, render=False)
        linhas, area = md.secao(p.malha, n, desloc)
        if linhas:
            pts, cel, k = [], [], 0
            for ln in linhas:
                pts.append(ln)
                cel.append(np.r_[len(ln), np.arange(k, k + len(ln))])
                k += len(ln)
            contorno = pv.PolyData(np.vstack(pts), lines=np.concatenate(cel))
            self.plotter.add_mesh(contorno, color=c["destaque"], line_width=4, name="previa_contorno",
                                  pickable=False, render=False)
            texto = f"Área do corte: {br(area)} mm²"
            self.c_info.setStyleSheet("")
            self._plano_encaixe = None
            if self.c_encaixe.isChecked():
                pl = en.planejar(p.malha, n, desloc, self._config_encaixe())
                if pl["ok"]:
                    self._plano_encaixe = pl
                    pinos = pv.MultiBlock()
                    for pt in pl["pontos"]:
                        ax = pl["n"] if pl["lado_furo"] == "cima" else -pl["n"]
                        if pl["tipo"] == "quadrado":
                            lado = 2 * pl["raio"]
                            cx = pv.Cube(center=pt + ax * pl["profundidade"] / 2, x_length=lado, y_length=lado,
                                         z_length=pl["profundidade"])
                            rot = trimesh_align(ax)
                            cx = cx.translate(-(pt + ax * pl["profundidade"] / 2), inplace=False) \
                                .transform(rot, inplace=False).translate(pt + ax * pl["profundidade"] / 2, inplace=False)
                            pinos.append(cx)
                        else:
                            pinos.append(pv.Cylinder(center=pt + ax * pl["profundidade"] / 2, direction=ax,
                                                     radius=pl["raio"], height=pl["profundidade"], resolution=32))
                    self.plotter.add_mesh(pinos.combine(), color=c["ok"], name="previa_pinos", pickable=False,
                                          render=False)
                    forma = "redondos" if pl["tipo"] == "redondo" else "quadrados"
                    um = len(pl["pontos"]) == 1
                    texto += (f"\n{len(pl['pontos'])} pino{'' if um else 's'} {forma[:-1] if um else forma} de "
                              f"{br(2 * pl['raio'])} mm, entrando {br(pl['profundidade'])} mm")
                    if len(pl["pontos"]) < pl["pedidos"]:
                        texto += f" (só couberam {len(pl['pontos'])} de {pl['pedidos']})"
                    if pl["aviso"]:
                        texto += "\n" + pl["aviso"]
                    if pl["tipo"] == "redondo" and um:
                        texto += "\nCom 1 pino redondo a peça pode girar. Use pino quadrado se precisar travar."
                else:
                    texto += "\nSem encaixes: " + pl["motivo"]
            self.c_info.setText(texto)
            if not self.c_encaixe.isChecked():
                texto += "\nA opção “Criar encaixes” está desligada na aba Cortar."
            self.e_info.setText(texto)
        else:
            self.c_info.setText("O plano não passa pela peça.")
            self.c_info.setStyleSheet(f"color: {c['perigo']};")
        if not p.malha.is_watertight:
            self.c_info.setText(self.c_info.text() + "\nA malha tem furos. Vou tentar consertar antes de cortar.")
        self.plotter.render()

    def cortar(self):
        i = self.indice()
        if i < 0:
            self.peca()
            return
        p = self.proj.pecas[i]
        if p.tem_suportes():
            r = QMessageBox.question(self, "Peça com suportes",
                                     "Esta peça já tem suportes. Para cortar, os suportes serão removidos "
                                     "e você gera de novo depois. Continuar?")
            if r != QMessageBox.Yes:
                return
        n = self._normal_corte()
        lo, hi = md.faixa_na_direcao(p.malha, n)
        desloc = lo + self.c_pos.value()
        if desloc <= lo + 1e-3 or desloc >= hi - 1e-3:
            QMessageBox.information(self, "Corte fora da peça", "Mova a posição do corte para dentro da peça.")
            return
        malha = p.malha.copy()
        com_encaixe = self.c_encaixe.isChecked()
        cfg = self._config_encaixe()
        soltos, deitar, organizar = self.c_soltos.isChecked(), self.c_deitar.isChecked(), self.c_organizar.isChecked()

        def tarefa():
            baixo, cima = md.cortar(malha, n, desloc)
            if baixo is None or cima is None:
                return None
            lado_pino = None
            if com_encaixe:
                pl = en.planejar(malha, n, desloc, cfg)
                if pl["ok"]:
                    b2, c2 = en.aplicar(baixo, cima, pl)
                    if b2 is not None and c2 is not None:
                        baixo, cima = b2, c2
                        lado_pino = "A" if pl["lado_furo"] == "cima" else "B"
            lados = []
            for mm, face, sufixo in ((baixo, n, "A"), (cima, -n, "B")):
                pedacos = md.separar_pedacos(mm) if soltos else [mm]
                for k, pd in enumerate(pedacos):
                    nome = f"{p.nome} {sufixo}" + (f"{k + 1}" if len(pedacos) > 1 else "")
                    if deitar and sufixo != lado_pino:
                        md.deitar_face(pd, face)
                    else:
                        md.colocar_na_mesa(pd)
                    lados.append((nome, pd, face))
            if not organizar:
                for _, pd, face in lados:
                    if np.allclose(face, -n):
                        md.mover(pd, *(n * 10))
                        md.colocar_na_mesa(pd)
            return lados, lado_pino

        def depois(res):
            if res is None:
                QMessageBox.warning(self, "Não foi possível cortar",
                                    "O corte não gerou duas partes. Tente outra posição ou direção.")
                return
            lados, lado_pino = res
            self.proj.registrar()
            k = self.proj.pecas.index(p)
            self.proj.pecas[k:k + 1] = [md.Peca(nome, pd) for nome, pd, _ in lados]
            if organizar:
                self._organizar([q for q in self.proj.pecas if q.visivel])
            self.atualizar_tudo(reconstruir=True, selecionar=k)
            extra = " com encaixes" if lado_pino else ""
            self.statusBar().showMessage(f"Peça cortada em {len(lados)} partes{extra}. Ctrl+Z desfaz.", 6000)
        self._rodar("Cortando a peça…", tarefa, depois)

    def _organizar(self, pecas):
        """Organiza levando os suportes em conta (a peça com suportes não desce para a mesa)."""
        import trimesh
        caixas = []
        for p in pecas:
            b = p.limites()
            caixas.append(trimesh.creation.box(extents=np.maximum(b[1] - b[0], 0.01)).apply_translation((b[0] + b[1]) / 2))
        antes = [c.bounds[0].copy() for c in caixas]
        md.organizar(caixas)
        for p, c, a in zip(pecas, caixas, antes):
            d = c.bounds[0] - a
            p.mover([d[0], d[1], 0 if p.tem_suportes() else d[2]])

    def organizar_mesa(self):
        visiveis = [p for p in self.proj.pecas if p.visivel]
        if not visiveis:
            return
        self.proj.registrar()
        self._organizar(visiveis)
        self.atualizar_tudo(reconstruir=True)
        foras = sum(not md.dentro_da_mesa(p.limites()) for p in visiveis)
        self.statusBar().showMessage("Peças organizadas." + (f" {foras} não couberam na mesa." if foras else ""), 6000)


    # ================================================================ aba encaixes
    def _aba_encaixes(self):
        conteudo = QWidget()
        l = QVBoxLayout(conteudo)
        l.setContentsMargins(2, 10, 6, 10)
        l.setSpacing(8)
        explica = rotulo("Os encaixes são criados quando você corta a peça na aba Cortar, com a opção "
                         "“Criar encaixes” ligada. O programa escolhe onde pôr os pinos, longe das bordas, "
                         "e confere se o furo não atravessa a parede.")
        explica.setWordWrap(True)
        l.addWidget(explica)

        l.addWidget(rotulo("Tipo de pino", "titulo"))
        self.e_tipo = QComboBox()
        self.e_tipo.addItem("Redondo", "redondo")
        self.e_tipo.addItem("Quadrado (não deixa girar)", "quadrado")
        l.addWidget(self.e_tipo)

        g = QGridLayout()
        self.e_qtd = QComboBox()
        self.e_qtd.addItem("Automática", 0)
        for k in range(1, 5):
            self.e_qtd.addItem(str(k), k)
        self.e_qtd.setToolTip("Automática: 1 a 4 pinos, conforme o tamanho da face cortada")
        self.e_diam = numero(0, 20, 0, " mm", "0 = automático, conforme o tamanho da face", 1)
        self.e_diam.setSpecialValueText("Automático")
        self.e_diam.setSingleStep(0.5)
        self.e_prof = numero(0, 25, 0, " mm", "Quanto o pino entra no furo. 0 = automático", 1)
        self.e_prof.setSpecialValueText("Automática")
        self.e_prof.setSingleStep(0.5)
        self.e_folga = numero(0, 1, 0.15, " mm", "Espaço entre o pino e o furo.\n0,10 = bem justo\n"
                              "0,15 = recomendado\n0,25 = folgado (se a sua resina encolhe pouco)")
        self.e_folga.setSingleStep(0.05)
        self.e_parede = numero(0.8, 5, en.PAREDE_PADRAO, " mm", "Distância mínima entre o furo e a borda da peça", 1)
        self.e_parede.setSingleStep(0.5)
        for i, (txt, w) in enumerate((("Quantidade", self.e_qtd), ("Diâmetro", self.e_diam),
                                      ("Profundidade", self.e_prof), ("Folga", self.e_folga),
                                      ("Parede mínima", self.e_parede))):
            g.addWidget(rotulo(txt), i, 0)
            g.addWidget(w, i, 1)
        l.addLayout(g)
        for w in (self.e_tipo, self.e_qtd):
            w.currentIndexChanged.connect(lambda _: self._agendar_previa())
        for w in (self.e_diam, self.e_prof, self.e_folga, self.e_parede):
            w.valueChanged.connect(lambda _: self._agendar_previa())

        self.e_info = rotulo("")
        self.e_info.setWordWrap(True)
        l.addSpacing(4)
        l.addWidget(self.e_info)
        dica = rotulo("Dica: imprima um teste pequeno com dois pedaços para acertar a folga da sua resina.")
        dica.setWordWrap(True)
        l.addSpacing(6)
        l.addWidget(dica)
        l.addWidget(self._botao("Ir para Cortar", "Voltar para a aba de corte",
                                lambda: self.abas.setCurrentIndex(self.ABA_CORTAR), "tesoura", True))
        l.addStretch(1)
        rol = QScrollArea()
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        return rol

    def _config_encaixe(self):
        return en.Config(tipo=self.e_tipo.currentData(), quantidade=self.e_qtd.currentData(),
                         diametro=self.e_diam.value(), profundidade=self.e_prof.value(),
                         folga=self.e_folga.value(), parede=self.e_parede.value())


    # ================================================================ aba suportes
    def _aba_suportes(self):
        conteudo = QWidget()
        l = QVBoxLayout(conteudo)
        l.setContentsMargins(2, 10, 6, 10)
        l.setSpacing(8)
        explica = rotulo("O programa levanta a peça, acha as partes penduradas e as pontas que começam no ar, "
                         "e cria os suportes. Áreas sem suporte aparecem em vermelho.")
        explica.setWordWrap(True)
        l.addWidget(explica)

        l.addWidget(rotulo("Densidade", "titulo"))
        self.s_dens = QComboBox()
        self.s_dens.addItem("Leve (peças pequenas e leves)", "leve")
        self.s_dens.addItem("Médio (recomendado)", "medio")
        self.s_dens.addItem("Pesado (peças grandes ou pesadas)", "pesado")
        self.s_dens.setCurrentIndex(1)
        self.s_dens.currentIndexChanged.connect(self._preset_suporte)
        l.addWidget(self.s_dens)

        g = QGridLayout()
        self.s_elev = numero(0, 30, 5, " mm", "Altura da peça em relação à mesa. Mais alto = mais fácil de tirar", 1)
        self.s_ang = numero(10, 80, 45, "°", "Superfícies mais deitadas que esse ângulo recebem suporte.\n"
                            "Menor = menos suportes; maior = mais seguro", 0)
        self.s_ponta = numero(0.1, 2, 0.4, " mm", "Diâmetro onde o suporte toca a peça. Menor = marca menor", 2)
        self.s_ponta.setSingleStep(0.05)
        self.s_pilar = numero(0.3, 4, 1.0, " mm", "Grossura do pilar do suporte", 2)
        self.s_pilar.setSingleStep(0.1)
        self.s_espaco = numero(1, 15, 3.5, " mm", "Distância entre um suporte e outro", 1)
        self.s_espaco.setSingleStep(0.5)
        self.s_base = numero(0, 5, 1.0, " mm", "Espessura da base (raft) embaixo dos suportes. 0 = sem base", 1)
        for i, (txt, w) in enumerate((("Elevação", self.s_elev), ("Ângulo crítico", self.s_ang),
                                      ("Ponta", self.s_ponta), ("Pilar", self.s_pilar),
                                      ("Espaçamento", self.s_espaco), ("Base (raft)", self.s_base))):
            g.addWidget(rotulo(txt), i, 0)
            g.addWidget(w, i, 1)
        l.addLayout(g)
        self.s_trava = QCheckBox("Travar pilares altos entre si")
        self.s_trava.setChecked(True)
        self.s_trava.setToolTip("Liga pilares vizinhos com hastes em X para não balançarem")
        l.addWidget(self.s_trava)
        self.s_internos = QCheckBox("Suportes internos (dentro de peças ocas)")
        self.s_internos.setChecked(False)
        self.s_internos.setToolTip("Desligado: só suportes por fora da peça.\n"
                                   "Ligado: também segura o teto do vazio de peças ocas grandes.")
        self.s_internos.toggled.connect(lambda _: self.atualizar_tudo())
        l.addWidget(self.s_internos)
        self.s_ang.valueChanged.connect(lambda _: self.atualizar_tudo())
        self.s_espaco.valueChanged.connect(lambda _: self.atualizar_tudo())

        l.addSpacing(4)
        l.addWidget(self._botao("Gerar suportes automáticos", "Cria os suportes na peça selecionada. Ctrl+Z desfaz.",
                                self.gerar_suportes, "suporte", True))
        self.b_todas_sup = self._botao("Gerar em todas as peças", "Cria suportes em todas as peças visíveis",
                                       self.gerar_suportes_todas, "suporte")
        l.addWidget(self.b_todas_sup)

        l.addSpacing(4)
        l.addWidget(rotulo("Ajuste manual", "titulo"))
        linha = QHBoxLayout()
        self.s_add = self._botao("Adicionar", "Clique na peça (sem arrastar) para pôr um suporte", lambda: None, "mais")
        self.s_rem = self._botao("Remover", "Clique num suporte (sem arrastar) para tirar", lambda: None, "menos")
        for b, modo in ((self.s_add, "adicionar"), (self.s_rem, "remover")):
            b.setCheckable(True)
            b.clicked.disconnect()
            b.toggled.connect(lambda ligado, m=modo: self._modo_manual(m, ligado))
            linha.addWidget(b)
        l.addLayout(linha)
        self.s_falta = QCheckBox("Mostrar em vermelho onde falta suporte")
        self.s_falta.setChecked(True)
        self.s_falta.toggled.connect(lambda _: self.atualizar_tudo())
        l.addWidget(self.s_falta)
        l.addSpacing(4)
        l.addWidget(rotulo("Verificação", "titulo"))
        linha = QHBoxLayout()
        linha.addWidget(self._botao("Verificar suportes", "Procura suportes que atravessam a peça (vermelho) "
                                    "ou que ficam no vazio interno (âmbar)", self.verificar_suportes, "lupa"))
        linha.addWidget(self._botao("Remover com problema", "Tira os suportes marcados na verificação",
                                    self.remover_problemas, "lixo"))
        l.addLayout(linha)
        l.addWidget(self._botao("Remover todos os suportes", "Tira os suportes da peça e a coloca de volta na mesa",
                                self.remover_suportes, "lixo"))
        self.s_info = rotulo("")
        self.s_info.setWordWrap(True)
        l.addWidget(self.s_info)
        l.addStretch(1)
        rol = QScrollArea()
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        return rol

    def _preset_suporte(self):
        pr = su.PRESETS[self.s_dens.currentData()]
        self.s_ponta.setValue(pr["ponta"])
        self.s_pilar.setValue(pr["pilar"])
        self.s_espaco.setValue(pr["espaco"])

    def _params_suporte(self):
        return su.Parametros(elevacao=self.s_elev.value(), angulo=self.s_ang.value(), ponta=self.s_ponta.value(),
                             pilar=self.s_pilar.value(), espaco=self.s_espaco.value(), base=self.s_base.value(),
                             travamento=self.s_trava.isChecked(), internos=self.s_internos.isChecked())

    def _aba_mudou(self, _):
        if self.abas.currentIndex() != self.ABA_SUPORTES:
            self.s_add.setChecked(False)
            self.s_rem.setChecked(False)
        if self.abas.currentIndex() != self.ABA_OCAR:
            self.o_furo.setChecked(False)
        self.atualizar_tudo()

    def _gerar_em(self, pecas, ao_terminar=None):
        pr = self._params_suporte()
        copias = [(p, p.malha.copy()) for p in pecas]

        def tarefa():
            res = []
            for p, m in copias:
                s_, amb = su.gerar(m, pr, self._ambientes.get(hash(m)))
                s_.malha()
                res.append((p, m, s_, amb))
            return res

        def depois(res):
            self.proj.registrar()
            for p, m, s_, amb in res:
                p.malha, p.suportes, p.problemas = m, s_, None
                self._ambientes[hash(m)] = amb
            self.atualizar_tudo(reconstruir=True)
            if ao_terminar:
                ao_terminar(res)
        self._rodar("Gerando suportes…", tarefa, depois)

    def gerar_suportes(self):
        p = self.peca()
        if p is None:
            return
        self._gerar_em([p], lambda res: self.statusBar().showMessage(
            f"{len(res[0][2])} suportes criados. Ctrl+Z desfaz.", 6000))

    def gerar_suportes_todas(self):
        visiveis = [p for p in self.proj.pecas if p.visivel]
        if visiveis:
            self._gerar_em(visiveis, lambda res: self.statusBar().showMessage(
                f"Suportes criados em {len(res)} peças.", 6000))

    def verificar_suportes(self):
        p = self.peca()
        if p is None:
            return
        if not p.tem_suportes():
            QMessageBox.information(self, "Sem suportes", "Esta peça ainda não tem suportes.")
            return
        s_ = p.suportes

        def tarefa():
            return su.verificar(s_, self._ambiente(p, esperar=True))

        def depois(r):
            p.problemas = (s_, r[0], r[1])
            self.atualizar_tudo()
            a, it = int(r[0].sum()), int((r[1] & ~r[0]).sum())
            if not a and not it:
                self.statusBar().showMessage("✔ Nenhum suporte atravessa a peça ou fica no vazio interno.", 6000)
        self._rodar("Verificando os suportes…", tarefa, depois)

    def remover_problemas(self):
        p = self.peca()
        if p is None or not self._problemas_visiveis(p):
            QMessageBox.information(self, "Nada para remover", "Clique antes em Verificar suportes.")
            return
        s_, at, it = p.problemas
        remover = at | it if not self.s_internos.isChecked() else at
        self.proj.registrar()
        su.remover_indices(p.suportes, remover)
        su.calcular_travas(p.suportes, self._ambientes.get(hash(p.malha)))
        p.problemas = None
        self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage(f"{int(remover.sum())} suportes removidos. Ctrl+Z desfaz.", 6000)

    def remover_suportes(self):
        p = self.peca()
        if p is None or p.suportes is None:
            return
        self.proj.registrar()
        p.suportes = None
        md.colocar_na_mesa(p.malha)
        self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage("Suportes removidos.", 4000)

    def _modo_manual(self, modo, ligado):
        if ligado:
            for outro, m_ in ((self.s_add, "adicionar"), (self.s_rem, "remover"), (self.o_furo, "furo")):
                if m_ != modo:
                    outro.blockSignals(True)
                    outro.setChecked(False)
                    outro.blockSignals(False)
            self._modo_clique = modo
            self.plotter.disable_picking()
            self.plotter.enable_surface_point_picking(callback=self._clicou, show_message=False, show_point=False,
                                                      left_clicking=True, pickable_window=False)
            self.statusBar().showMessage({"adicionar": "Clique na peça para adicionar um suporte.",
                                          "remover": "Clique num suporte para remover.",
                                          "furo": "Clique na peça onde quer o furo de drenagem."}[modo])
        elif self._modo_clique == modo:
            self._modo_clique = None
            self.plotter.disable_picking()
            self.statusBar().clearMessage()
        self.atualizar_tudo()

    def _clicou(self, ponto):
        p = self.peca(avisar=False)
        if p is None or ponto is None:
            return
        ponto = np.asarray(ponto, float)
        if self._modo_clique == "adicionar":
            b = p.malha.bounds
            if np.any(ponto < b[0] - 0.5) or np.any(ponto > b[1] + 0.5):
                return
            self.proj.registrar()
            if p.suportes is None:
                pr = self._params_suporte()
                d = pr.elevacao + pr.base - p.malha.bounds[0][2]
                p.malha.apply_translation([0, 0, d])
                ponto = ponto + [0, 0, d]
                p.suportes = su.Suportes(pr)
            if not su.adicionar(p.malha, p.suportes, ponto, self._ambientes.get(hash(p.malha))):
                self.statusBar().showMessage("Não dá para pôr suporte aí (muito perto de outra parte da peça).", 5000)
        elif self._modo_clique == "furo":
            b = p.malha.bounds
            if np.any(ponto < b[0] - 0.5) or np.any(ponto > b[1] + 0.5):
                return
            self._furar(p, ponto)
            return
        elif self._modo_clique == "remover" and p.suportes is not None:
            self.proj.registrar()
            if not su.remover_perto(p.suportes, ponto, max(2.0, p.suportes.params.pilar * 2.5),
                                    self._ambientes.get(hash(p.malha))):
                self.statusBar().showMessage("Nenhum suporte nesse ponto.", 3000)
        self.atualizar_tudo(reconstruir=True)

    def _ambiente(self, p, esperar=False):
        """Mapa de dentro/fora da peça. Se não estiver pronto, calcula em segundo plano."""
        chave = hash(p.malha)
        amb = self._ambientes.get(chave)
        if amb is not None or not esperar:
            if amb is None and chave not in self._calculando:
                self._calculando.add(chave)
                malha = p.malha.copy()

                def tarefa():
                    try:
                        self._ambientes[chave] = su.Ambiente(malha)
                    finally:
                        self._calculando.discard(chave)
                        self.sinais.ambiente_pronto.emit(chave)
                threading.Thread(target=tarefa, daemon=True).start()
            return amb
        amb = su.Ambiente(p.malha)
        self._ambientes[chave] = amb
        if len(self._ambientes) > 12:
            self._ambientes.pop(next(iter(self._ambientes)))
        return amb

    def _desenhar_faltas(self, i, p, novos):
        c = self.cores
        if p.tem_suportes():
            ms = p.suportes.malha()
            self._desenhar_problemas(i, p, novos)
        else:
            ms = None
        if not self.s_falta.isChecked():
            self._faltas = (0.0, 0)
            return
        amb = self._ambiente(p)
        chave = (hash(p.malha), id(ms), self.s_ang.value(), self.s_espaco.value(), self.s_internos.isChecked(),
                 amb is not None)
        res = self._cache_faltas.get(chave)
        if res is None:
            crit, mins = su.sem_suporte(p.malha, p.suportes if p.tem_suportes() else None, self.s_ang.value(),
                                        self.s_espaco.value(), amb, self.s_internos.isChecked())
            tri = p.malha.triangles[crit] + p.malha.face_normals[crit][:, None, :] * 0.03 if len(crit) else None
            res = (tri, mins, float(p.malha.area_faces[crit].sum()) if len(crit) else 0.0)
            self._cache_faltas = {chave: res}
        tri, mins, area = res
        if tri is not None:
            def fazer(tri=tri):
                faces = np.c_[np.full(len(tri), 3), np.arange(len(tri) * 3).reshape(-1, 3)].ravel()
                return pv.PolyData(tri.reshape(-1, 3), faces)
            self._ator(f"falta_{i}", chave, fazer, novos, c["perigo"])
        if len(mins):
            self._ator(f"ilha_{i}", chave, lambda mins=mins: pv.PolyData(mins), novos, c["perigo"],
                       point_size=12, render_points_as_spheres=True)
        self._faltas = (area, len(mins))

    def _problemas_visiveis(self, p):
        return getattr(p, "problemas", None) is not None and p.problemas[0] is p.suportes and \
            (p.problemas[1].any() or p.problemas[2].any())

    def _desenhar_problemas(self, i, p, novos):
        """Suportes que atravessam a peça (vermelho) ou ficam no vazio interno (âmbar)."""
        if not self._problemas_visiveis(p):
            return
        s, atravessa, interno = p.problemas
        for nome, mascara, cor in ((f"atravessa_{i}", atravessa, self.cores["perigo"]),
                                   (f"interno_{i}", interno & ~atravessa, self.cores["destaque"])):
            if not mascara.any():
                continue
            def fazer(m_=mascara):
                pts = np.empty((m_.sum() * 2, 3))
                pts[0::2], pts[1::2] = s.topos[m_], s.fins[m_]
                linhas = np.c_[np.full(m_.sum(), 2), np.arange(m_.sum() * 2).reshape(-1, 2)].ravel()
                return pv.PolyData(pts, lines=linhas)
            self._ator(nome, (id(s), int(mascara.sum())), fazer, novos, cor, line_width=6)

    def _atualizar_info_suportes(self):
        p = self.peca(avisar=False)
        if p is None:
            self.s_info.setText("Selecione uma peça na lista.")
            return
        partes = []
        if p.tem_suportes():
            s = p.suportes
            s.malha()
            partes.append(f"{len(s)} suportes: {int(s.na_mesa.sum())} na mesa e {int((~s.na_mesa).sum())} "
                          f"apoiados na própria peça. Resina dos suportes: {br(s.volume_ml)} ml.")
        else:
            partes.append("Esta peça ainda não tem suportes.")
        if self._problemas_visiveis(p):
            _, at, it = p.problemas
            a, ii = int(at.sum()), int((it & ~at).sum())
            if a:
                partes.append(f"✖ {a} suporte{'s' if a > 1 else ''} atravessa{'m' if a > 1 else ''} a peça (vermelho).")
            if ii:
                partes.append(f"{ii} suporte{'s' if ii > 1 else ''} no vazio interno (âmbar)"
                              + ("." if self.s_internos.isChecked() else ". Remova se não quiser suportes internos."))
        elif getattr(p, "problemas", None) is not None and p.problemas[0] is p.suportes:
            partes.append("✔ Nenhum suporte atravessa a peça.")
        if self.abas.currentIndex() == self.ABA_SUPORTES and self.s_falta.isChecked():
            fc, fm = getattr(self, "_faltas", (0, 0))
            if fc > 0.01 or fm:
                partes.append((f"Faltam suportes em {br(fc)} mm² da superfície" if fc > 0.01 else "Faltam suportes")
                              + (f" e {fm} ponta{'s' if fm != 1 else ''} solta{'s' if fm != 1 else ''}" if fm else "")
                              + " (em vermelho).")
            elif p.tem_suportes():
                partes.append("Nenhuma área sem suporte.")
        self.s_info.setText("\n".join(partes))
        self._faltas = (0, 0)


    # ================================================================ aba ocar
    def _aba_ocar(self):
        conteudo = QWidget()
        l = QVBoxLayout(conteudo)
        l.setContentsMargins(2, 10, 6, 10)
        l.setSpacing(8)
        explica = rotulo("Deixa a peça oca por dentro para gastar menos resina. Toda peça oca precisa de furos "
                         "de drenagem, senão a resina fica presa e o vazio vira ventosa durante a impressão.")
        explica.setWordWrap(True)
        l.addWidget(explica)

        g = QGridLayout()
        self.o_parede = numero(0.8, 10, 2.0, " mm", "Espessura da casca. 2 mm é bom para a maioria das peças;\n"
                               "peças grandes ou que levam pancada: 2,5 a 3 mm", 1)
        self.o_parede.setSingleStep(0.5)
        self.o_qual = QComboBox()
        self.o_qual.addItem("Rápida", "rapida")
        self.o_qual.addItem("Normal", "normal")
        self.o_qual.addItem("Fina (mais lenta)", "fina")
        self.o_qual.setCurrentIndex(1)
        self.o_qual.setToolTip("Quanto mais fina, mais a casca interna acompanha os detalhes da peça")
        self.o_diam = numero(1, 10, 3.0, " mm", "Diâmetro dos furos de drenagem. 3 mm escoa bem a maioria das resinas", 1)
        self.o_diam.setSingleStep(0.5)
        for i, (txt, w) in enumerate((("Parede", self.o_parede), ("Qualidade", self.o_qual), ("Furo", self.o_diam))):
            g.addWidget(rotulo(txt), i, 0)
            g.addWidget(w, i, 1)
        l.addLayout(g)
        self.o_auto = QCheckBox("Criar 2 furos de drenagem automáticos")
        self.o_auto.setChecked(True)
        self.o_auto.setToolTip("Os furos ficam no lado da mesa, que é por onde a resina e o ar escapam")
        l.addWidget(self.o_auto)
        l.addWidget(self._botao("Ocar peça", "Ocar a peça selecionada. Ctrl+Z desfaz.", self.ocar_peca, "ocar", True))

        l.addSpacing(4)
        l.addWidget(rotulo("Furos de drenagem", "titulo"))
        self.o_furo = self._botao("Adicionar furo com clique", "Clique na peça (sem arrastar) para abrir um furo",
                                  lambda: None, "mais")
        self.o_furo.setCheckable(True)
        self.o_furo.clicked.disconnect()
        self.o_furo.toggled.connect(lambda ligado: self._modo_manual("furo", ligado))
        l.addWidget(self.o_furo)
        dica = rotulo("Ponha os furos perto da mesa (embaixo, na tela) e em lados opostos: um deixa a resina "
                      "sair e o outro deixa o ar entrar. Para tirar um furo, use Ctrl+Z.")
        dica.setWordWrap(True)
        l.addWidget(dica)

        l.addSpacing(4)
        l.addWidget(rotulo("Sucção", "titulo"))
        l.addWidget(self._botao("Verificar sucção", "Procura vazios fechados do lado da mesa, que puxam a peça "
                                "como ventosa a cada camada", self.verificar_succao, "lupa"))
        self.o_mostrar = QCheckBox("Mostrar os pontos de risco em vermelho")
        self.o_mostrar.setChecked(True)
        self.o_mostrar.toggled.connect(lambda _: self.atualizar_tudo())
        l.addWidget(self.o_mostrar)
        self.o_info = rotulo("")
        self.o_info.setWordWrap(True)
        l.addWidget(self.o_info)
        l.addStretch(1)
        rol = QScrollArea()
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        return rol

    def _checar_succao(self, p):
        p.riscos = oc.riscos_succao(p.malha)

    def ocar_peca(self):
        i = self.indice()
        if i < 0:
            self.peca()
            return
        p = self.proj.pecas[i]
        if getattr(p, "oca", False):
            r = QMessageBox.question(self, "Peça já oca", "Esta peça já foi ocada. Ocar de novo deixa a parede "
                                     "mais fina. Continuar?")
            if r != QMessageBox.Yes:
                return
        malha = p.malha.copy()
        parede, qual, diam, auto = (self.o_parede.value(), self.o_qual.currentData(), self.o_diam.value(),
                                    self.o_auto.isChecked())

        def tarefa():
            antes = md.medidas(malha)["volume_ml"]
            oco, cav = oc.ocar(malha, parede, qual)
            if oco is None:
                return None, cav
            furos = 0
            if auto:
                for pt, direcao, comp in oc.sugerir_furos(malha, cav, parede):
                    novo = oc.furo(oco, pt, direcao, diam, comp)
                    if novo is not None:
                        oco, furos = novo, furos + 1
            riscos = oc.riscos_succao(oco)
            return (oco, furos, riscos, antes), None

        def depois(r):
            res, motivo = r
            if res is None:
                QMessageBox.information(self, "Não foi possível ocar", motivo)
                return
            oco, furos, riscos, antes = res
            self.proj.registrar()
            p.malha, p.oca, p.riscos = oco, True, riscos
            if p.suportes is not None:
                p.suportes.mudou()
                p.problemas = None
            self.atualizar_tudo(reconstruir=True)
            vol = md.medidas(p.malha)["volume_ml"]
            eco = f" Resina: {br(antes)} ml para {br(vol)} ml." if antes and vol else ""
            aviso = " Se a peça já tinha suportes, gere de novo para tirar os que ficaram no vazio." \
                if p.tem_suportes() else ""
            self.statusBar().showMessage(f"Peça ocada com {furos} furo{'s' if furos != 1 else ''} de drenagem."
                                         f"{eco}{aviso}", 9000)
        self._rodar("Ocando a peça…", tarefa, depois)

    def _furar(self, p, ponto):
        arv_c = p.malha.triangles_center
        k = int(np.argmin(((arv_c - ponto) ** 2).sum(1)))
        dentro = -p.malha.face_normals[k]
        comp = max(self.o_parede.value() * 1.6 + 1.0, 3.0)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            novo = oc.furo(p.malha, ponto, dentro, self.o_diam.value(), comp)
        finally:
            QApplication.restoreOverrideCursor()
        if novo is None:
            self.statusBar().showMessage("Não consegui abrir o furo aqui. A malha pode ter defeitos.", 5000)
            return
        self.proj.registrar()
        p.malha = novo
        if p.suportes is not None:
            p.suportes.mudou()
        self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage("Furo aberto. Ctrl+Z desfaz.", 4000)
        if getattr(p, "riscos", None) is not None:
            self.verificar_succao()

    def verificar_succao(self):
        p = self.peca()
        if p is None:
            return
        malha = p.malha.copy()

        def depois(r):
            p.riscos = r
            self.atualizar_tudo()
        self._rodar("Procurando risco de sucção…", lambda: oc.riscos_succao(malha), depois)

    def _atualizar_info_ocar(self):
        p = self.peca(avisar=False)
        if p is None:
            self.o_info.setText("Selecione uma peça na lista.")
            return
        riscos = getattr(p, "riscos", None)
        partes = []
        if getattr(p, "oca", False):
            partes.append("Esta peça está oca.")
        if riscos is None:
            partes.append("Clique em Verificar sucção para procurar vazios que viram ventosa.")
        elif not riscos:
            partes.append("✔ Nenhum risco de sucção encontrado.")
        else:
            r = riscos[0]
            partes.append(f"✖ {len(riscos)} região{'ões' if len(riscos) > 1 else ''} com risco de sucção. "
                          f"A maior tem {br(r['area'], 0)} mm², entre {br(r['z0'])} e {br(r['z1'])} mm de altura.")
            partes.append("Abra um furo no ponto vermelho mais perto da mesa, ou incline a peça na aba "
                          "Posição para o vazio não ficar virado para o fundo do tanque.")
        self.o_info.setText("\n".join(partes))
        self.o_info.setStyleSheet(f"color: {self.cores['perigo']};" if riscos else "")

    # ================================================================ tema
    def _aplicar_tema(self):
        c = self.cores = tema.ESCURO if self.escuro else tema.CLARO
        app = QApplication.instance()
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(tema.paleta(c))
        app.setStyleSheet(tema.folha_de_estilo(c))
        for w, nome, tam in self._icones:
            cor = c["sobre_destaque"] if getattr(w, "_principal", False) else c["texto"]
            w.setIcon(tema.icone(nome, cor, tam))
        self.b_tema.setIcon(tema.icone("sol" if self.escuro else "lua", c["texto"], 18))
        self.plotter.set_background(c["fundo3d_baixo"], top=c["fundo3d_topo"])
        mx, my, mz = md.MESA_X, md.MESA_Y, md.MESA_Z
        self.plotter.add_mesh(pv.Plane(center=(0, 0, -0.05), direction=(0, 0, 1), i_size=mx, j_size=my),
                              color=c["mesa"], name="mesa", pickable=False, ambient=0.3, render=False)
        self.plotter.add_mesh(pv.Plane(center=(0, 0, 0), direction=(0, 0, 1), i_size=mx, j_size=my,
                                       i_resolution=int(mx / 10), j_resolution=int(my / 10)),
                              style="wireframe", color=c["grade"], name="grade", pickable=False, render=False)
        self.plotter.add_mesh(pv.Box(bounds=(-mx / 2, mx / 2, -my / 2, my / 2, 0, mz)), style="wireframe",
                              color=c["volume"], opacity=0.6, name="volume", pickable=False, render=False)

    def trocar_tema(self):
        self.escuro = not self.escuro
        self.config.setValue("tema_escuro", self.escuro)
        self._aplicar_tema()
        self.atualizar_tudo(reconstruir=True)

    def _vista(self, qual):
        {"topo": self.plotter.view_xy, "frente": self.plotter.view_xz,
         "lado": self.plotter.view_yz}.get(qual, self.plotter.view_isometric)()
        self.plotter.reset_camera()

    # ================================================================ lista e desenho
    def indice(self):
        i = self.lista.currentRow()
        return i if 0 <= i < len(self.proj.pecas) else -1

    def peca(self, avisar=True):
        i = self.indice()
        if i < 0:
            if avisar:
                QMessageBox.information(self, "Nenhuma peça selecionada", "Clique numa peça da lista à esquerda primeiro.")
            return None
        return self.proj.pecas[i]

    def _reconstruir_lista(self, selecionar=None):
        atual = self.indice() if selecionar is None else selecionar
        self.lista.blockSignals(True)
        self.lista.clear()
        for i in range(len(self.proj.pecas)):
            it = QListWidgetItem()
            w = ItemPeca(self, i)
            it.setSizeHint(QSize(100, 54))
            self.lista.addItem(it)
            self.lista.setItemWidget(it, w)
        if self.proj.pecas:
            self.lista.setCurrentRow(min(max(atual, 0), len(self.proj.pecas) - 1))
        self.lista.blockSignals(False)
        tem = bool(self.proj.pecas)
        self.lista.setVisible(tem)
        self.vazio.setVisible(not tem)
        self.contagem.setText(str(len(self.proj.pecas)) if tem else "")

    def _ator(self, nome, chave, fazer, novos, cor, opacidade=1.0, clicavel=False, **extra):
        """Desenha só quando a geometria muda; senão, só ajusta cor, transparência e clique."""
        atual = self._cache_atores.get(nome)
        if atual is None or atual[0] != chave:
            ator = self.plotter.add_mesh(fazer(), name=nome, render=False, color=cor, opacity=opacidade,
                                         pickable=clicavel, **extra)
            self._cache_atores[nome] = (chave, ator)
        else:
            ator = atual[1]
            ator.prop.color = cor
            ator.prop.opacity = opacidade
            ator.SetPickable(clicavel)
        novos.add(nome)

    def atualizar_tudo(self, resetar_camera=False, reconstruir=False, selecionar=None):
        if reconstruir:
            self._reconstruir_lista(selecionar)
        c = self.cores
        sel = self.indice()
        aba = self.abas.currentIndex() if hasattr(self, "ABA_OCAR") else 0
        cortando = aba in (getattr(self, "ABA_CORTAR", -1), getattr(self, "ABA_ENCAIXES", -1))
        suportando = aba == getattr(self, "ABA_SUPORTES", -1)
        ocando = aba == getattr(self, "ABA_OCAR", -1)
        novos = set()
        for i, p in enumerate(self.proj.pecas):
            if not p.visivel:
                continue
            dentro = md.dentro_da_mesa(p.limites())
            destacar = i == sel and not (cortando or suportando or ocando)
            cor = c["peca_fora"] if not dentro else (c["peca_sel"] if destacar else c["peca"])
            riscos = getattr(p, "riscos", None)
            transparente = i == sel and (cortando or (ocando and riscos and self.o_mostrar.isChecked())
                                         or (suportando and self._problemas_visiveis(p)))
            m = p.malha
            self._ator(f"peca_{i}", (id(m), hash(m)), lambda m=m: para_polydata(m), novos, cor,
                       0.45 if transparente else 1.0, self._modo_clique is not None and i == sel,
                       specular=0.35, specular_power=20, smooth_shading=False)
            if p.tem_suportes():
                ms = p.suportes.malha()
                self._ator(f"sup_{i}", (id(ms), len(ms.faces)), lambda ms=ms: para_polydata(ms), novos,
                           c["suporte"], 1.0, self._modo_clique == "remover", specular=0.2)
            if suportando and i == sel:
                self._desenhar_faltas(i, p, novos)
            if ocando and i == sel and riscos and self.o_mostrar.isChecked():
                pts = np.vstack([r["pontos"] for r in riscos])
                self._ator(f"succao_{i}", id(riscos), lambda pts=pts: pv.PolyData(pts), novos, c["perigo"], 0.8,
                           point_size=7, render_points_as_spheres=True)
        for nome in self._nomes - novos:
            self.plotter.remove_actor(nome, render=False)
            self._cache_atores.pop(nome, None)
        self._nomes = novos
        if resetar_camera:
            self.plotter.view_isometric()
            self.plotter.reset_camera()
        self.plotter.render()
        self._atualizar_info()
        if hasattr(self, "s_info"):
            self._atualizar_info_suportes()
        if hasattr(self, "o_info"):
            self._atualizar_info_ocar()
        if hasattr(self, "c_pos"):
            self._ajustar_limites_corte()
            if cortando:
                self._agendar_previa()
            else:
                self._apagar_previa()

    def _atualizar_info(self):
        c = self.cores
        total = sum((md.medidas(q.malha)["volume_ml"] or 0) + (q.suportes.volume_ml if q.tem_suportes() else 0)
                    for q in self.proj.pecas if q.visivel)
        n = len(self.proj.pecas)
        self.resumo.setText(f"{n} peça{'s' if n != 1 else ''} na mesa, {br(total)} ml de resina no total   " if n else "")
        p = self.peca(avisar=False)
        if p is None:
            self.i_nome.setText("Nenhuma peça selecionada")
            for lb in self.i_med.values():
                lb.setText("–")
            self.i_resina.setText("–")
            self.i_mesa.setText("")
            return
        d = md.medidas(p.malha)
        self.i_nome.setText(p.nome)
        for k in "xyz":
            self.i_med[k].setText(br(d[k]))
        if d["volume_ml"] is None:
            self.i_resina.setText("?")
            self.i_resina.setToolTip("A malha tem furos, então não dá para calcular o volume.")
        else:
            if p.tem_suportes():
                p.suportes.malha()
                tot = d["volume_ml"] + p.suportes.volume_ml
                self.i_resina.setText(f"{br(tot)} ml")
                self.i_resina.setToolTip(f"Peça: {br(d['volume_ml'])} ml\nSuportes: {br(p.suportes.volume_ml)} ml")
            else:
                self.i_resina.setText(f"{br(d['volume_ml'])} ml")
                self.i_resina.setToolTip("")
        if md.dentro_da_mesa(p.limites()):
            self.i_mesa.setText("✔  Cabe na mesa")
            self.i_mesa.setStyleSheet(f"color: {c['ok']}; font-weight: 600;")
        else:
            self.i_mesa.setText("✖  Passa dos limites da mesa")
            self.i_mesa.setStyleSheet(f"color: {c['perigo']}; font-weight: 600;")

    def alternar_visivel(self, i):
        self.lista.setCurrentRow(i)
        self.proj.pecas[i].visivel = not self.proj.pecas[i].visivel
        self.atualizar_tudo(reconstruir=True)

    def _menu_lista(self, pos):
        if self.lista.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction("Renomear", self.renomear)
        m.addAction("Duplicar", self.duplicar)
        m.addAction("Centralizar", self.centralizar)
        m.addSeparator()
        m.addAction("Excluir", self.excluir)
        m.exec(self.lista.mapToGlobal(pos))

    def renomear(self):
        p = self.peca()
        if p is None:
            return
        novo, ok = QInputDialog.getText(self, "Renomear peça", "Novo nome:", text=p.nome)
        if ok and novo.strip():
            self.proj.registrar()
            p.nome = novo.strip()
            self.atualizar_tudo(reconstruir=True)

    # ================================================================ operações
    def _operar(self, func, mensagem):
        p = self.peca()
        if p is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.proj.registrar()
            antes = p.malha.vertices.copy()
            func(p.malha)
            dif = p.malha.vertices - antes if len(antes) == len(p.malha.vertices) else None
            if dif is None or not np.allclose(dif, dif[0], atol=1e-6):
                p.riscos = None
            if p.suportes is not None:
                desloc = p.malha.vertices - antes
                if len(desloc) and np.allclose(desloc, desloc[0], atol=1e-6):
                    p.suportes.transladar(desloc[0])
                else:
                    p.suportes = None
                    mensagem += " Os suportes foram removidos porque a peça mudou de posição; gere de novo."
        finally:
            QApplication.restoreOverrideCursor()
        self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage(mensagem, 7000)

    def mover(self):
        self._operar(lambda m: md.mover(m, self.dx.value(), self.dy.value(), self.dz.value()), "Peça movida.")

    def centralizar(self):
        self._operar(md.centralizar, "Peça centralizada.")

    def deitar(self):
        self._operar(md.colocar_na_mesa, "Peça encostada na mesa.")

    def girar(self, eixo, graus):
        self._operar(lambda m: md.girar(m, eixo, graus), f"Peça girada {br(graus, 0)}° no eixo {eixo}.")

    def escalar(self):
        self._operar(lambda m: md.escalar(m, self.escala.value()), f"Tamanho ajustado para {br(self.escala.value(), 0)}%.")

    def orientar(self):
        p = self.peca()
        if p is None:
            return
        malha = p.malha.copy()
        self._rodar("Procurando a melhor posição…", lambda: md.orientacao_sugerida(malha),
                    lambda r: self._operar(lambda m: md.aplicar_orientacao(m, r),
                                           "Posição sugerida aplicada. Ctrl+Z desfaz se não gostar."))

    def duplicar(self):
        p = self.peca()
        if p is None:
            return
        self.proj.registrar()
        nova = p.copia()
        nova.nome = f"{p.nome} (cópia)"
        b = p.limites()
        largura = b[1][0] - b[0][0] + 5
        nova.mover([largura, 0, 0])
        if not md.dentro_da_mesa(nova.limites()):
            nova.mover([-2 * largura, 0, 0])
        self.proj.pecas.append(nova)
        self.atualizar_tudo(reconstruir=True, selecionar=len(self.proj.pecas) - 1)

    def excluir(self):
        i = self.indice()
        if i < 0:
            return
        self.proj.registrar()
        del self.proj.pecas[i]
        self.atualizar_tudo(reconstruir=True, selecionar=max(i - 1, 0))
        self.statusBar().showMessage("Peça excluída. Ctrl+Z traz de volta.", 5000)

    def desfazer(self):
        ok = self.proj.desfazer()
        if ok:
            self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage("Desfeito." if ok else "Não há nada para desfazer.", 3000)

    def refazer(self):
        ok = self.proj.refazer()
        if ok:
            self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage("Refeito." if ok else "Não há nada para refazer.", 3000)

    # ================================================================ arquivos
    def _pasta(self):
        return self.config.value("ultima_pasta", os.path.expanduser("~"))

    def _lembrar_pasta(self, caminho):
        self.config.setValue("ultima_pasta", os.path.dirname(caminho))

    def importar(self):
        arqs, _ = QFileDialog.getOpenFileNames(self, "Importar peça", self._pasta(),
                                               "Modelos 3D (*.stl *.obj *.3mf);;Todos os arquivos (*)")
        if arqs:
            self._lembrar_pasta(arqs[0])
            self.importar_arquivos(arqs)

    def importar_arquivos(self, arqs):
        def tarefa():
            res = []
            for arq in arqs:
                try:
                    m = md.carregar_malha(arq)
                    md.centralizar(m)
                    m.volume, m.is_watertight  # já calcula aqui, fora da tela
                    res.append((arq, m, None))
                except Exception as e:
                    res.append((arq, None, str(e)))
            return res

        def depois(res):
            primeira = not self.proj.pecas
            erros = [f"{os.path.basename(a)}: {e}" for a, m, e in res if m is None]
            boas = [(a, m) for a, m, e in res if m is not None]
            if boas:
                self.proj.registrar()
            arrumar = False
            for arq, m in boas:
                if self.proj.pecas:
                    borda = max(q.limites()[1][0] for q in self.proj.pecas)
                    t = m.copy()
                    md.mover(t, borda + 5 - t.bounds[0][0], 0, 0)
                    if md.dentro_da_mesa(t):
                        m = t
                    else:
                        arrumar = True
                self.proj.pecas.append(md.Peca(os.path.splitext(os.path.basename(arq))[0], m))
            if arrumar:
                self._organizar([q for q in self.proj.pecas if q.visivel])
            self.atualizar_tudo(resetar_camera=primeira, reconstruir=True, selecionar=len(self.proj.pecas) - 1)
            if erros:
                QMessageBox.warning(self, "Alguns arquivos não abriram", "\n".join(erros))
            else:
                self.statusBar().showMessage(f"{len(boas)} peça(s) importada(s).", 5000)
        self._rodar("Abrindo o arquivo…" if len(arqs) == 1 else f"Abrindo {len(arqs)} arquivos…", tarefa, depois)

    def salvar_projeto(self):
        if not self.proj.pecas:
            QMessageBox.information(self, "Projeto vazio", "Importe pelo menos uma peça antes de salvar.")
            return
        sug = self.caminho_projeto or os.path.join(self._pasta(), "meu_projeto.resina")
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", sug, f"Projeto Fatiador (*{EXT_PROJETO})")
        if not caminho:
            return
        if not caminho.lower().endswith(EXT_PROJETO):
            caminho += EXT_PROJETO
        md.salvar_projeto(self.proj, caminho)
        self.caminho_projeto = caminho
        self._lembrar_pasta(caminho)
        self.statusBar().showMessage(f"Projeto salvo em {caminho}", 6000)

    def abrir_projeto(self, caminho=None):
        if not caminho:
            caminho, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", self._pasta(), f"Projeto Fatiador (*{EXT_PROJETO})")
        if not caminho:
            return
        try:
            self.proj = md.abrir_projeto(caminho)
        except Exception as e:
            QMessageBox.warning(self, "Não foi possível abrir", f"O arquivo parece danificado.\n\n{e}")
            return
        self.caminho_projeto = caminho
        self._lembrar_pasta(caminho)
        self.atualizar_tudo(resetar_camera=True, reconstruir=True, selecionar=0)
        self.statusBar().showMessage("Projeto aberto.", 5000)

    def exportar(self):
        visiveis = [p for p in self.proj.pecas if p.visivel]
        if not visiveis:
            QMessageBox.information(self, "Nada para exportar", "Não há peças visíveis na mesa.")
            return
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Exportar STL")
        caixa.setText("O que você quer exportar?")
        b_todas = caixa.addButton("Todas as peças visíveis", QMessageBox.AcceptRole)
        b_sel = caixa.addButton("Só a peça selecionada", QMessageBox.AcceptRole)
        caixa.addButton("Cancelar", QMessageBox.RejectRole)
        caixa.exec()
        if caixa.clickedButton() == b_todas:
            malhas, nome = [m for p in visiveis for m in p.malhas()], "mesa_completa.stl"
        elif caixa.clickedButton() == b_sel:
            p = self.peca()
            if p is None:
                return
            malhas, nome = p.malhas(), f"{p.nome}.stl"
        else:
            return
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar STL", os.path.join(self._pasta(), nome), "Arquivo STL (*.stl)")
        if not caminho:
            return
        if not caminho.lower().endswith(".stl"):
            caminho += ".stl"
        md.exportar_stl(malhas, caminho)
        self._lembrar_pasta(caminho)
        self.statusBar().showMessage(f"STL salvo em {caminho}. Abra no ChituBox para fatiar.", 8000)

    # ================================================================ atualização
    def _montar_aviso(self):
        aviso = QFrame()
        aviso.setObjectName("aviso")
        l = QHBoxLayout(aviso)
        l.setContentsMargins(14, 8, 14, 8)
        self.av_icone = QLabel()
        l.addWidget(self.av_icone)
        self.av_texto = QLabel()
        self.av_texto.setObjectName("aviso_texto")
        l.addWidget(self.av_texto, 1)
        self.av_barra = QProgressBar()
        self.av_barra.setFixedWidth(220)
        self.av_barra.setVisible(False)
        l.addWidget(self.av_barra)
        self.av_novidades = self._botao("Novidades", "Ver o que mudou nesta versão", self._mostrar_novidades)
        self.av_pular = self._botao("Pular esta versão", "Não avisar mais sobre esta versão", self._pular_versao)
        self.av_depois = self._botao("Depois", "Esconder este aviso", lambda: self.aviso.setVisible(False))
        self.av_atualizar = self._botao("Atualizar agora", "Baixar e instalar a versão nova", self._baixar_atualizacao,
                                        "atualizar", True)
        for b in (self.av_novidades, self.av_pular, self.av_depois, self.av_atualizar):
            l.addWidget(b)
        aviso.setVisible(False)
        return aviso

    def procurar_atualizacao(self, silencioso):
        if not atualizador.pode_atualizar():
            if not silencioso:
                QMessageBox.information(self, "Atualizações",
                                        "A busca de atualizações funciona na versão instalada pelo instalador.")
            return
        if not silencioso:
            self.statusBar().showMessage("Procurando atualizações…", 5000)

        def tarefa():
            try:
                info = atualizador.procurar()
            except Exception as e:
                if not silencioso:
                    self.sinais.busca_falhou.emit(atualizador.explicar_erro(e))
                return
            if info:
                info["silencioso"] = silencioso
                self.sinais.nova_versao.emit(info)
            elif not silencioso:
                self.sinais.sem_novidade.emit(True)
        threading.Thread(target=tarefa, daemon=True).start()

    def _sem_atualizacao(self, _):
        QMessageBox.information(self, "Atualizações", f"Você já está com a versão mais nova ({VERSAO}).")

    def _oferecer_atualizacao(self, info):
        if info.get("silencioso") and self.config.value("pular_versao", "") == info["versao"]:
            return
        if self._baixando:
            return
        self._info_atualizacao = info
        self.av_icone.setPixmap(tema.icone("atualizar", self.cores["destaque"], 18).pixmap(18, 18))
        self.av_texto.setText(f"<b>Versão {info['versao']} disponível.</b> Você está com a {VERSAO}.")
        self.av_barra.setVisible(False)
        for b in (self.av_novidades, self.av_pular, self.av_depois, self.av_atualizar):
            b.setVisible(True)
            b.setEnabled(True)
        self.aviso.setVisible(True)

    def _mostrar_novidades(self):
        info = getattr(self, "_info_atualizacao", None)
        notas = (info or {}).get("notas", "").strip() or "Melhorias e correções."
        QMessageBox.information(self, f"Novidades da versão {info['versao'] if info else ''}", notas)

    def _pular_versao(self):
        info = getattr(self, "_info_atualizacao", None)
        if info:
            self.config.setValue("pular_versao", info["versao"])
        self.aviso.setVisible(False)

    def _baixar_atualizacao(self):
        info = getattr(self, "_info_atualizacao", None)
        if not info or self._baixando:
            return
        if self.proj.pecas and self.proj._desfazer:
            r = QMessageBox.question(self, "Salvar antes?", "O programa vai fechar para instalar a versão nova.\n"
                                     "Quer salvar o projeto antes?",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Yes:
                self.salvar_projeto()
        self._baixando = True
        for b in (self.av_novidades, self.av_pular, self.av_depois, self.av_atualizar):
            b.setVisible(False)
        self.av_texto.setText(f"Baixando a versão {info['versao']}…")
        self.av_barra.setValue(0)
        self.av_barra.setVisible(True)

        def tarefa():
            try:
                self.sinais.baixado.emit(atualizador.baixar(info, self.sinais.progresso.emit))
            except Exception as e:
                self.sinais.falhou.emit(atualizador.explicar_erro(e))
        threading.Thread(target=tarefa, daemon=True).start()

    def _download_ok(self, caminho):
        self.av_barra.setValue(100)
        self.av_texto.setText("Instalando… o programa vai fechar e abrir de novo sozinho.")
        QApplication.processEvents()
        try:
            atualizador.instalar(caminho)
        except Exception as e:
            self._download_falhou(atualizador.explicar_erro(e))
            return
        QTimer.singleShot(800, QApplication.quit)

    def _download_falhou(self, motivo):
        self._baixando = False
        self.av_barra.setVisible(False)
        self.av_texto.setText(f"<b>Não deu para baixar a atualização.</b> {motivo}")
        self.av_atualizar.setText("Tentar de novo")
        for b in (self.av_depois, self.av_atualizar):
            b.setVisible(True)

    def _novidades_desta_versao(self):
        vista = self.config.value("versao_vista", "")
        self.config.setValue("versao_vista", VERSAO)
        if vista and vista != VERSAO:
            from .novidades import TEXTO
            QMessageBox.information(self, f"Atualizado para a versão {VERSAO}",
                                    f"O {NOME} foi atualizado.\n\nNovidades:\n{TEXTO}")

    # ================================================================ trabalho em segundo plano
    def _rodar(self, texto, func, depois):
        """Roda `func` fora da tela (sem travar) e depois chama `depois(resultado)` na tela."""
        if self._ocupado:
            self.statusBar().showMessage("Aguarde a tarefa atual terminar.", 3000)
            return
        self._ocupado = True
        dlg = QProgressDialog(texto, None, 0, 0, self)
        dlg.setWindowTitle(NOME)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(350)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        t = Trabalho()
        self._trabalhos.add(t)

        def fim(ok, valor):
            self._ocupado = False
            dlg.reset()
            dlg.close()
            self._trabalhos.discard(t)
            if ok:
                depois(valor)
            else:
                QMessageBox.warning(self, "Algo deu errado", f"{valor}\n\nO detalhe foi salvo em erro.log.")
        t.pronto.connect(lambda v: fim(True, v))
        t.erro.connect(lambda m: fim(False, m))

        def corpo():
            try:
                r = func()
            except Exception as e:
                _gravar_erro(type(e), e, e.__traceback__)
                t.erro.emit(str(e) or type(e).__name__)
                return
            t.pronto.emit(r)
        threading.Thread(target=corpo, daemon=True).start()

    def esperar_tarefas(self, limite=120):
        """Usado nos testes automáticos."""
        import time
        fim = time.time() + limite
        while (self._ocupado or self._calculando) and time.time() < fim:
            QApplication.processEvents()
            time.sleep(0.01)
        QApplication.processEvents()

    def sobre(self):
        QMessageBox.about(self, f"Sobre o {NOME}",
                          f"<h3>{NOME}</h3><p>Versão {VERSAO}</p>"
                          "<p>Preparação de peças para impressão em resina na Elegoo Saturn 2 8K.</p>"
                          "<p>Próxima etapa: calibração por áreas e fatiar no formato da Saturn 2.</p>")

    # ================================================================ arrastar e soltar
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        arqs = [u.toLocalFile() for u in ev.mimeData().urls()]
        projetos = [a for a in arqs if a.lower().endswith(EXT_PROJETO)]
        modelos = [a for a in arqs if a.lower().endswith(EXTENSOES)]
        if projetos:
            self.abrir_projeto(projetos[0])
        elif modelos:
            self.importar_arquivos(modelos)

    def closeEvent(self, ev):
        self.plotter.close()
        super().closeEvent(ev)


def _gravar_erro(tipo, valor, tb):
    texto = "".join(traceback.format_exception(tipo, valor, tb))
    log = os.path.join(pasta_dados(), "erro.log")
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- versão {VERSAO}\n{texto}\n")
    except OSError:
        pass
    return log


def _mostrar_erro(tipo, valor, tb):
    log = _gravar_erro(tipo, valor, tb)
    QMessageBox.critical(None, "Ocorreu um erro",
                         f"Algo deu errado. O detalhe foi salvo em:\n{log}\n\n{valor}")


def iniciar(app, abertura=None):
    QLocale.setDefault(QLocale(QLocale.Portuguese, QLocale.Brazil))
    sys.excepthook = _mostrar_erro
    j = Janela()
    j.showMaximized()
    if abertura:
        abertura.finish(j)
    for arg in sys.argv[1:]:
        if arg.lower().endswith(EXT_PROJETO):
            j.abrir_projeto(arg)
        elif arg.lower().endswith(EXTENSOES):
            j.importar_arquivos([arg])
    sys.exit(app.exec())
