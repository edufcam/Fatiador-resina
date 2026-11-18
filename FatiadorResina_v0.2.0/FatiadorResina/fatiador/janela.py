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
    QButtonGroup, QMenu, QInputDialog, QProgressDialog, QSizePolicy,
)
from pyvistaqt import QtInteractor

from . import modelo as md
from . import tema, atualizador, VERSAO, NOME
from .recursos import recurso, pasta_dados

EXTENSOES = (".stl", ".obj", ".3mf")
EXT_PROJETO = ".resina"


def br(v, casas=1):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
    progresso = Signal(int)
    baixado = Signal(str)
    falhou = Signal(str)


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
        if not md.dentro_da_mesa(p.malha):
            dims.setText(dims.text() + "   fora da mesa")
            dims.setStyleSheet(f"color: {c['perigo']};")
        textos.addWidget(nome)
        textos.addWidget(dims)
        lay.addLayout(textos, 1)


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
        self._icones = []
        self.sinais = Sinais()
        self.sinais.nova_versao.connect(self._oferecer_atualizacao)
        self.sinais.sem_novidade.connect(self._sem_atualizacao)

        self._montar()
        self._aplicar_tema()
        self.atualizar_tudo(resetar_camera=True, reconstruir=True)
        self.statusBar().showMessage("Arraste um arquivo STL, OBJ ou 3MF para a janela, ou clique em Importar.")
        if atualizador.pode_atualizar():
            QTimer.singleShot(4000, lambda: self.procurar_atualizacao(silencioso=True))

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
        self.plotter.enable_anti_aliasing("ssaa")
        self.plotter.add_axes(line_width=2, labels_off=False)
        l.addWidget(self.plotter.interactor, 1)
        dica = rotulo("Botão esquerdo: girar a vista     Rodinha: zoom     Shift + botão esquerdo: arrastar")
        dica.setContentsMargins(12, 6, 12, 6)
        l.addWidget(dica)
        return caixa

    def _montar_painel(self):
        painel = QWidget()
        painel.setObjectName("painel")
        painel.setMinimumWidth(320)
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
        self.abas.addTab(self._aba_posicionar(), "Posicionar")
        for nome in ("Cortar", "Encaixes", "Suportes", "Ocar"):
            i = self.abas.addTab(QWidget(), nome)
            self.abas.setTabEnabled(i, False)
            self.abas.setTabToolTip(i, "Chega numa próxima atualização")
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
        rol.setWidgetResizable(True)
        rol.setWidget(conteudo)
        return rol

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

    def atualizar_tudo(self, resetar_camera=False, reconstruir=False, selecionar=None):
        if reconstruir:
            self._reconstruir_lista(selecionar)
        c = self.cores
        sel = self.indice()
        novos = set()
        for i, p in enumerate(self.proj.pecas):
            if not p.visivel:
                continue
            nome = f"peca_{i}"
            dentro = md.dentro_da_mesa(p.malha)
            cor = c["peca_fora"] if not dentro else (c["peca_sel"] if i == sel else c["peca"])
            extra = {"silhouette": {"color": c["peca_sel"], "line_width": 2}} if i == sel else {}
            self.plotter.add_mesh(para_polydata(p.malha), color=cor, name=nome, specular=0.35,
                                  specular_power=20, smooth_shading=False, render=False, **extra)
            novos.add(nome)
        for nome in self._nomes - novos:
            self.plotter.remove_actor(nome, render=False)
        self._nomes = novos
        if resetar_camera:
            self.plotter.view_isometric()
            self.plotter.reset_camera()
        self.plotter.render()
        self._atualizar_info()

    def _atualizar_info(self):
        c = self.cores
        total = sum((md.medidas(q.malha)["volume_ml"] or 0) for q in self.proj.pecas if q.visivel)
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
            self.i_resina.setText(f"{br(d['volume_ml'])} ml")
            self.i_resina.setToolTip("")
        if md.dentro_da_mesa(p.malha):
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
            func(p.malha)
        finally:
            QApplication.restoreOverrideCursor()
        self.atualizar_tudo(reconstruir=True)
        self.statusBar().showMessage(mensagem, 5000)

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
        self._operar(lambda m: md.aplicar_orientacao(m, md.orientacao_sugerida(m)),
                     "Posição sugerida aplicada. Ctrl+Z desfaz se não gostar.")

    def duplicar(self):
        p = self.peca()
        if p is None:
            return
        self.proj.registrar()
        nova = p.copia()
        nova.nome = f"{p.nome} (cópia)"
        largura = p.malha.extents[0] + 5
        md.mover(nova.malha, largura, 0, 0)
        if not md.dentro_da_mesa(nova.malha):
            md.mover(nova.malha, -2 * largura, 0, 0)
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
        erros = []
        primeira = not self.proj.pecas
        self.proj.registrar()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for arq in arqs:
                self.statusBar().showMessage(f"Abrindo {os.path.basename(arq)}…")
                QApplication.processEvents()
                try:
                    m = md.carregar_malha(arq)
                except Exception as e:
                    erros.append(f"{os.path.basename(arq)}: {e}")
                    continue
                md.centralizar(m)
                if self.proj.pecas:
                    borda = max(q.malha.bounds[1][0] for q in self.proj.pecas)
                    t = m.copy()
                    md.mover(t, borda + 5 - t.bounds[0][0], 0, 0)
                    if md.dentro_da_mesa(t):
                        m = t
                self.proj.pecas.append(md.Peca(os.path.splitext(os.path.basename(arq))[0], m))
        finally:
            QApplication.restoreOverrideCursor()
        self.atualizar_tudo(resetar_camera=primeira, reconstruir=True, selecionar=len(self.proj.pecas) - 1)
        if erros:
            QMessageBox.warning(self, "Alguns arquivos não abriram", "\n".join(erros))
        else:
            self.statusBar().showMessage(f"{len(arqs)} peça(s) importada(s).", 5000)

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
            malhas, nome = [p.malha for p in visiveis], "mesa_completa.stl"
        elif caixa.clickedButton() == b_sel:
            p = self.peca()
            if p is None:
                return
            malhas, nome = [p.malha], f"{p.nome}.stl"
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
    def procurar_atualizacao(self, silencioso):
        if not atualizador.pode_atualizar():
            if not silencioso:
                QMessageBox.information(self, "Atualizações",
                                        "A busca de atualizações funciona na versão instalada pelo instalador.")
            return

        def tarefa():
            try:
                info = atualizador.procurar()
            except Exception:
                info = None
                if not silencioso:
                    self.sinais.falhou.emit("sem_internet")
            if info:
                self.sinais.nova_versao.emit(info)
            elif not silencioso:
                self.sinais.sem_novidade.emit(True)
        if not silencioso:
            self.statusBar().showMessage("Procurando atualizações…", 4000)
        threading.Thread(target=tarefa, daemon=True).start()

    def _sem_atualizacao(self, _):
        QMessageBox.information(self, "Atualizações", f"Você já está com a versão mais nova ({VERSAO}).")

    def _oferecer_atualizacao(self, info):
        notas = info["notas"].strip()
        r = QMessageBox.question(
            self, "Nova versão disponível",
            f"A versão {info['versao']} do {NOME} está disponível (você tem a {VERSAO}).\n\n"
            + (f"Novidades:\n{notas[:800]}\n\n" if notas else "")
            + "Quer atualizar agora? Salve seu projeto antes, porque o programa vai fechar e abrir de novo.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            return
        dlg = QProgressDialog("Baixando a atualização…", None, 0, 100, self)
        dlg.setWindowTitle("Atualizando")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        s = self.sinais
        s.progresso.connect(dlg.setValue)

        def terminou(caminho):
            dlg.close()
            atualizador.instalar(caminho)
            QApplication.quit()

        def deu_erro(_):
            dlg.close()
            QMessageBox.warning(self, "Atualização", "Não foi possível baixar a atualização. Verifique a internet e tente de novo.")

        s.baixado.connect(terminou)
        s.falhou.connect(deu_erro)

        def tarefa():
            try:
                s.baixado.emit(atualizador.baixar(info, s.progresso.emit))
            except Exception as e:
                s.falhou.emit(str(e))
        threading.Thread(target=tarefa, daemon=True).start()

    def sobre(self):
        QMessageBox.about(self, f"Sobre o {NOME}",
                          f"<h3>{NOME}</h3><p>Versão {VERSAO}</p>"
                          "<p>Preparação de peças para impressão em resina na Elegoo Saturn 2 8K.</p>"
                          "<p>Próximas atualizações: corte inteligente, encaixes, suportes e ocar peças.</p>")

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


def _mostrar_erro(tipo, valor, tb):
    texto = "".join(traceback.format_exception(tipo, valor, tb))
    log = os.path.join(pasta_dados(), "erro.log")
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- versão {VERSAO}\n{texto}\n")
    except OSError:
        pass
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
