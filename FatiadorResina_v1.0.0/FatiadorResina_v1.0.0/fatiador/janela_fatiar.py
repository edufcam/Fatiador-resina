"""Janela de fatiamento: perfil de resina, prévia camada por camada e arquivo para a impressora."""
import io
import json
import os
import threading

import numpy as np
from PySide6.QtCore import Qt, QTimer, QObject, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QSlider,
    QPushButton, QCheckBox, QFileDialog, QMessageBox, QProgressDialog, QInputDialog, QFrame, QApplication,
)

from . import fatiar as ft
from . import calibracao as cb
from PySide6.QtWidgets import QTabWidget, QWidget, QLineEdit, QScrollArea
from PySide6.QtGui import QPainter, QColor, QPen, QFont

PERFIL_PADRAO = "Resina padrão (ponto de partida)"


def _tempo(seg):
    h, m = int(seg // 3600), int(seg % 3600 // 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _br(v, casas=1):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


class _Sinais(QObject):
    progresso = Signal(int)
    fim = Signal(object)


class JanelaFatiar(QDialog):
    def __init__(self, janela, malhas, nome, preview_png, calibracao=False, peca_selecionada=None):
        super().__init__(janela)
        self.j = janela
        self.cores = janela.cores
        self.nome, self.preview_png, self.malhas = nome, preview_png, malhas
        self.calibracao, self.peca_sel = calibracao, peca_selecionada
        self._cache_mesa = None
        self.setWindowTitle("Teste de calibração da resina" if calibracao else "Fatiar para a Saturn 2 8K")
        self.resize(1250, 780)
        self.fat = None
        self._cancelar = False

        raiz = QHBoxLayout(self)
        raiz.addWidget(self._painel_perfil())
        centro = QVBoxLayout()
        self.tela = QLabel()
        self.tela.setAlignment(Qt.AlignCenter)
        self.tela.setMinimumSize(640, 360)
        self.tela.setStyleSheet(f"background: {self.cores['fundo3d_baixo']}; border-radius: 10px;")
        centro.addWidget(self.tela, 1)
        linha = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setToolTip("Arraste para ver cada camada")
        self.slider.valueChanged.connect(lambda _: self._timer.start(25))
        self.num = QSpinBox()
        self.num.setMinimum(1)
        self.num.valueChanged.connect(lambda v: self.slider.setValue(v - 1))
        linha.addWidget(QLabel("Camada"))
        linha.addWidget(self.slider, 1)
        linha.addWidget(self.num)
        centro.addLayout(linha)
        self.info_camada = QLabel()
        self.info_camada.setObjectName("rotulo")
        centro.addWidget(self.info_camada)
        raiz.addLayout(centro, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._mostrar_camada)
        self._timer_refatiar = QTimer(self)
        self._timer_refatiar.setSingleShot(True)
        self._timer_refatiar.timeout.connect(self._refatiar)
        self._carregar_perfil(self.perfis.currentText())
        self._refatiar()

    # ------------------------------------------------------------ perfil
    def _painel_perfil(self):
        caixa = QFrame()
        caixa.setObjectName("cartao")
        caixa.setFixedWidth(360)
        l = QVBoxLayout(caixa)
        l.setContentsMargins(12, 12, 12, 12)
        t = QLabel("Perfil de resina")
        t.setObjectName("titulo")
        l.addWidget(t)
        linha = QHBoxLayout()
        self.perfis = QComboBox()
        self._todos = self._ler_perfis()
        self.perfis.addItems(list(self._todos))
        ultimo = self.j.config.value("perfil_atual", PERFIL_PADRAO)
        if ultimo in self._todos:
            self.perfis.setCurrentText(ultimo)
        self.perfis.currentTextChanged.connect(self._carregar_perfil)
        linha.addWidget(self.perfis, 1)
        b = QPushButton("Salvar…")
        b.setToolTip("Guardar estes valores com o nome da sua resina")
        b.clicked.connect(self._salvar_perfil)
        linha.addWidget(b)
        l.addLayout(linha)

        self.campos = {}
        abas = QTabWidget()
        if self.calibracao:
            abas.addTab(self._aba_calibracao(), "Teste")

        def aba():
            w = QWidget()
            g = QGridLayout(w)
            g.setContentsMargins(4, 10, 4, 4)
            g.setVerticalSpacing(6)
            rol = QScrollArea()
            rol.setWidgetResizable(True)
            rol.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            rol.setWidget(w)
            return rol, g

        def num(g, chave, txt, mn, mx, casas, suf, dica, passo=None):
            w = QSpinBox() if casas == 0 else QDoubleSpinBox()
            w.setRange(mn, mx)
            if casas:
                w.setDecimals(casas)
            if passo:
                w.setSingleStep(passo)
            w.setSuffix(suf)
            w.setToolTip(dica)
            w.valueChanged.connect(lambda _: self._timer_refatiar.start(300))
            r = g.rowCount()
            lb = QLabel(txt)
            lb.setObjectName("rotulo")
            lb.setToolTip(dica)
            g.addWidget(lb, r, 0)
            g.addWidget(w, r, 1)
            self.campos[chave] = w

        def titulo(g, txt):
            lb = QLabel(txt)
            lb.setObjectName("titulo")
            g.addWidget(lb, g.rowCount(), 0, 1, 2)

        rol, g = aba()
        titulo(g, "Camadas")
        num(g, "altura_camada", "Altura da camada", 0.01, 0.2, 3, " mm", "0,05 mm é o padrão. Menor = mais detalhe e mais tempo", 0.005)
        num(g, "camadas_base", "Camadas de base", 1, 50, 0, "", "Primeiras camadas, com exposição forte para grudar na mesa")
        num(g, "camadas_transicao", "Camadas de transição", 0, 30, 0, "",
            "Camadas depois da base em que o tempo vai diminuindo aos poucos até o normal")
        titulo(g, "Exposição")
        num(g, "exposicao", "Exposição normal", 0.5, 60, 2, " s", "Tempo de luz de cada camada normal", 0.1)
        num(g, "exposicao_base", "Exposição da base", 1, 180, 1, " s", "Tempo de luz das camadas de base", 1)
        titulo(g, "Esperas")
        num(g, "espera_antes", "Antes de expor", 0, 30, 1, " s",
            "Espera com a mesa parada antes de acender a luz (a resina assenta). Também chamado de luz apagada", 0.5)
        num(g, "espera_depois_expor", "Depois de expor", 0, 30, 1, " s", "Espera depois da luz apagar, antes de subir", 0.5)
        num(g, "espera_depois_subir", "Depois de subir", 0, 30, 1, " s", "Espera com a mesa no alto, antes de descer", 0.5)
        titulo(g, "Bordas")
        self.aa = QComboBox()
        for txt, v in (("Sem suavização", 1), ("Suavizar 2×", 2), ("Suavizar 4× (recomendado)", 4), ("Suavizar 8×", 8)):
            self.aa.addItem(txt, v)
        self.aa.setToolTip("Antialiasing: as bordas recebem tons de cinza, o que deixa curvas e degraus mais lisos.\n"
                           "Não muda a prévia, só o arquivo da impressora.")
        self.aa.currentIndexChanged.connect(lambda _: self._timer_refatiar.start(300))
        lb = QLabel("Antialiasing")
        lb.setObjectName("rotulo")
        r = g.rowCount()
        g.addWidget(lb, r, 0)
        g.addWidget(self.aa, r, 1)
        g.setRowStretch(g.rowCount(), 1)
        abas.addTab(rol, "Exposição")

        rol, g = aba()
        titulo(g, "Subida")
        num(g, "subida", "Altura de subida", 1, 20, 1, " mm", "Quanto a mesa sobe a cada camada para descolar do filme", 0.5)
        num(g, "vel_subida", "Velocidade de subida", 10, 600, 0, " mm/min", "Mais devagar = menos força no filme e na peça")
        num(g, "subida_base", "Subida na base", 1, 20, 1, " mm", "Altura de subida nas camadas de base", 0.5)
        num(g, "vel_subida_base", "Velocidade na base", 10, 600, 0, " mm/min", "Velocidade de subida nas camadas de base")
        titulo(g, "Descida")
        num(g, "vel_descida", "Velocidade de descida", 10, 600, 0, " mm/min", "Velocidade de volta da mesa")
        self.duas = QCheckBox("Subir e descer em duas velocidades")
        self.duas.setToolTip("Começa a subida devagar (para descolar com cuidado) e termina rápido.\n"
                             "Na volta, desce rápido e termina devagar. Economiza tempo.")
        self.duas.toggled.connect(lambda _: (self._duas_mudou(), self._timer_refatiar.start(300)))
        g.addWidget(self.duas, g.rowCount(), 0, 1, 2)
        num(g, "dist_lenta", "Trecho lento na subida", 0.5, 15, 1, " mm", "Distância subida devagar antes de acelerar", 0.5)
        num(g, "vel_subida_rapida", "Subida rápida", 10, 600, 0, " mm/min", "Velocidade depois do trecho lento")
        num(g, "dist_descida_lenta", "Trecho lento na descida", 0.5, 15, 1, " mm", "Últimos milímetros da descida feitos devagar", 0.5)
        num(g, "vel_descida_lenta", "Descida lenta", 10, 600, 0, " mm/min", "Velocidade no fim da descida")
        self.espelhar = QCheckBox("Espelhar imagem")
        self.espelhar.setToolTip("Só mude se a peça sair espelhada na impressora")
        self.espelhar.toggled.connect(lambda _: self._timer_refatiar.start(300))
        g.addWidget(self.espelhar, g.rowCount(), 0, 1, 2)
        g.setRowStretch(g.rowCount(), 1)
        abas.addTab(rol, "Mesa")

        rol, g = aba()
        titulo(g, "Resina")
        num(g, "densidade", "Densidade", 0.8, 2.0, 2, " g/ml", "Está na ficha da resina. A maioria fica entre 1,05 e 1,15", 0.01)
        num(g, "preco_litro", "Preço por litro", 0, 5000, 2, "", "Quanto você pagou por 1 litro (para calcular o custo)", 10)
        titulo(g, "Correção de medida")
        for eixo in "xyz":
            num(g, f"escala_{eixo}", f"Eixo {eixo.upper()}", 90, 110, 2, " %",
                "100% = sem correção. Calcule com o cubo de 20 mm em Calibrar resina", 0.1)
        aviso = QLabel("Os valores do perfil padrão são um ponto de partida. Use o teste de calibração para "
                       "achar o tempo certo da sua resina e salve como um perfil.")
        aviso.setObjectName("rotulo")
        aviso.setWordWrap(True)
        g.addWidget(aviso, g.rowCount(), 0, 1, 2)
        g.setRowStretch(g.rowCount(), 1)
        abas.addTab(rol, "Resina")
        l.addWidget(abas, 1)

        t = QLabel("Resumo")
        t.setObjectName("titulo")
        l.addWidget(t)
        self.resumo = QLabel("Fatiando…")
        self.resumo.setWordWrap(True)
        l.addWidget(self.resumo)
        self.b_salvar = QPushButton("Salvar teste para a impressora" if self.calibracao else
                                    "Salvar arquivo para a impressora")
        self.b_salvar.setObjectName("principal")
        self.b_salvar.clicked.connect(self._exportar)
        l.addWidget(self.b_salvar)
        nota = QLabel("Gera o arquivo .ctb da Saturn 2 8K, pronto para o pen drive (ou ZIP do ChituBox, se preferir).")
        nota.setObjectName("rotulo")
        nota.setWordWrap(True)
        l.addWidget(nota)
        return caixa

    def _duas_mudou(self):
        for k in ("dist_lenta", "vel_subida_rapida", "dist_descida_lenta", "vel_descida_lenta"):
            self.campos[k].setEnabled(self.duas.isChecked())

    # ------------------------------------------------------------ calibração
    def _aba_calibracao(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 10, 4, 4)
        self.c_tipo = QComboBox()
        self.c_tipo.addItem("Tempo de exposição", "exposicao")
        self.c_tipo.addItem("Folga dos encaixes", "folga")
        self.c_tipo.addItem("Medida (cubo de 20 mm)", "medida")
        self.c_tipo.setToolTip("O que você quer calibrar neste teste")
        lb = QLabel("O que testar")
        lb.setObjectName("titulo")
        l.addWidget(lb)
        l.addWidget(self.c_tipo)
        self.c_explica = QLabel()
        self.c_explica.setWordWrap(True)
        self.c_explica.setObjectName("rotulo")
        l.addWidget(self.c_explica)

        self.c_grade = QWidget()
        g = QGridLayout(self.c_grade)
        g.setContentsMargins(0, 0, 0, 0)
        self.c_regioes = QComboBox()
        for n in (4, 6, 8):
            self.c_regioes.addItem(f"{n} regiões", n)
        self.c_regioes.setCurrentIndex(1)
        self.c_inicio = QDoubleSpinBox()
        self.c_inicio.setRange(0.01, 30)
        self.c_inicio.setDecimals(2)
        self.c_passo = QDoubleSpinBox()
        self.c_passo.setRange(0.01, 10)
        self.c_passo.setDecimals(2)
        self.c_lista = QLineEdit()
        self.c_lista.setToolTip("Você pode digitar os valores à mão, separados por ponto e vírgula")
        self.c_peca = QComboBox()
        self.c_peca.addItem("Peça de calibração padrão", "padrao")
        if self.peca_sel is not None:
            self.c_peca.addItem("Peça selecionada na mesa", "selecionada")
        self.c_rot = {}
        for i, (txt, wd) in enumerate((("Regiões", self.c_regioes), ("Primeiro valor", self.c_inicio),
                                       ("Aumentar de", self.c_passo), ("Valores", self.c_lista), ("Peça", self.c_peca))):
            lb = QLabel(txt)
            lb.setObjectName("rotulo")
            self.c_rot[txt] = lb
            g.addWidget(lb, i, 0)
            g.addWidget(wd, i, 1)
        l.addWidget(self.c_grade)
        self.c_base = QCheckBox("Variar também a exposição da base")
        self.c_base.setToolTip("Desligado (recomendado): todas as regiões usam a mesma base forte, para nenhuma "
                               "peça soltar da mesa. Ligue só para calibrar a base.")
        l.addWidget(self.c_base)

        # resultado
        lb = QLabel("Depois de imprimir")
        lb.setObjectName("titulo")
        l.addWidget(lb)
        self.c_res_caixa = QWidget()
        lr = QGridLayout(self.c_res_caixa)
        lr.setContentsMargins(0, 0, 0, 0)
        self.c_melhor = QComboBox()
        self.c_melhor.setToolTip("Escolha a região que saiu melhor")
        lbm = QLabel("Melhor região")
        lbm.setObjectName("rotulo")
        lr.addWidget(lbm, 0, 0)
        lr.addWidget(self.c_melhor, 0, 1)
        self.c_usar = QPushButton("Usar no perfil")
        self.c_usar.clicked.connect(self._usar_resultado)
        self.c_refinar = QPushButton("Refinar o teste")
        self.c_refinar.setToolTip("Monta um teste novo com passos menores em volta da região escolhida")
        self.c_refinar.clicked.connect(self._refinar)
        lr.addWidget(self.c_usar, 1, 0)
        lr.addWidget(self.c_refinar, 1, 1)
        l.addWidget(self.c_res_caixa)
        self.c_medir = QPushButton("Digitar as medidas do cubo…")
        self.c_medir.setToolTip("Meça o cubo impresso com um paquímetro e o programa calcula a correção")
        self.c_medir.clicked.connect(self._medidas_cubo)
        l.addWidget(self.c_medir)
        self.c_dica = QLabel()
        self.c_dica.setWordWrap(True)
        self.c_dica.setObjectName("rotulo")
        l.addWidget(self.c_dica)
        l.addStretch(1)

        self.c_tipo.currentIndexChanged.connect(lambda _: self._tipo_mudou())
        for wd in (self.c_regioes, self.c_peca):
            wd.currentIndexChanged.connect(lambda _: self._gerar_lista())
        for wd in (self.c_inicio, self.c_passo):
            wd.valueChanged.connect(lambda _: self._gerar_lista())
        self.c_lista.editingFinished.connect(lambda: (self._atualizar_melhor(), self._timer_refatiar.start(50)))
        self.c_base.toggled.connect(lambda _: self._timer_refatiar.start(50))
        self._tipo_mudou(atualizar=False)
        return w

    TIPOS = {
        "exposicao": {"inicio": 1.6, "passo": 0.3, "suf": " s", "rotulo": "s",
                      "explica": "A mesma peça em várias regiões, cada uma com um tempo de exposição. A cada camada, "
                                 "as regiões que já completaram o tempo são apagadas sem mover a mesa; a mesa só sobe "
                                 "quando a última termina.",
                      "dica": "Escolha a região com pinos e paredes finas inteiros, furos abertos e números nítidos."},
        "folga": {"inicio": 0.05, "passo": 0.05, "suf": " mm", "rotulo": "mm",
                  "explica": "Cada região tem um pino redondo, um quadrado e dois anéis soltos com uma folga diferente "
                             "(gravada na peça). Todas usam a exposição do perfil.",
                  "dica": "Depois de lavar e curar, encaixe os anéis nos pinos. Escolha a menor folga que entra "
                          "sem forçar e sem ficar bamba."},
        "medida": {"explica": "Imprime um cubo de 20 × 20 × 10 mm com furo de 10 mm, usando o perfil atual. "
                              "Um entalhe marca o lado X; dois entalhes, o lado Y.",
                   "dica": "Meça o cubo já curado com um paquímetro e clique em Digitar as medidas do cubo."},
    }

    def _tipo_mudou(self, atualizar=True):
        t = self.c_tipo.currentData()
        cfg = self.TIPOS[t]
        self.c_explica.setText(cfg["explica"])
        self.c_dica.setText(cfg["dica"])
        varia = t != "medida"
        self.c_grade.setVisible(varia)
        self.c_res_caixa.setVisible(varia)
        self.c_medir.setVisible(t == "medida")
        self.c_base.setVisible(t == "exposicao")
        self.c_peca.setVisible(t == "exposicao")
        self.c_rot["Peça"].setVisible(t == "exposicao")
        if varia:
            for wd, chave in ((self.c_inicio, "inicio"), (self.c_passo, "passo")):
                wd.blockSignals(True)
                wd.setSuffix(cfg["suf"])
                wd.setSingleStep(0.05 if t == "folga" else 0.1)
                wd.setValue(cfg[chave])
                wd.blockSignals(False)
            self.c_rot["Valores"].setText("Tempos" if t == "exposicao" else "Folgas")
            self.c_usar.setText("Usar como exposição" if t == "exposicao" else "Usar como folga padrão")
        self._gerar_lista(atualizar)

    def _gerar_lista(self, atualizar=True):
        n = self.c_regioes.currentData()
        ts = [self.c_inicio.value() + i * self.c_passo.value() for i in range(n)]
        self.c_lista.setText("; ".join(_br(t, 2) for t in ts))
        self._cache_mesa = None
        self._atualizar_melhor()
        if atualizar:
            self._timer_refatiar.start(50)

    def _valores(self):
        partes = [x.strip().replace(",", ".") for x in self.c_lista.text().split(";") if x.strip()]
        try:
            ts = [float(x) for x in partes]
        except ValueError:
            ts = []
        return [t for t in ts if t > 0][:12]

    def _atualizar_melhor(self):
        if not hasattr(self, "c_melhor"):
            return
        t = self.c_tipo.currentData()
        suf = " s" if t == "exposicao" else " mm"
        atual = self.c_melhor.currentIndex()
        self.c_melhor.clear()
        for i, v in enumerate(self._valores()):
            self.c_melhor.addItem(f"{i + 1}ª: {_br(v, 2)}{suf}", v)
        if 0 <= atual < self.c_melhor.count():
            self.c_melhor.setCurrentIndex(atual)

    def _usar_resultado(self):
        v = self.c_melhor.currentData()
        if v is None:
            return
        if self.c_tipo.currentData() == "exposicao":
            self.campos["exposicao"].setValue(v)
            r = QMessageBox.question(self, "Exposição atualizada",
                                     f"A exposição normal agora é {_br(v, 2)} s.\nQuer salvar no perfil da resina?")
            if r == QMessageBox.Yes:
                self._salvar_perfil()
        else:
            self.j.config.setValue("folga_padrao", float(v))
            if hasattr(self.j, "e_folga"):
                self.j.e_folga.setValue(v)
            QMessageBox.information(self, "Folga atualizada",
                                    f"Os próximos encaixes vão usar {_br(v, 2)} mm de folga.\n"
                                    "Você pode mudar quando quiser na aba Encaixes.")

    def _refinar(self):
        v = self.c_melhor.currentData()
        if v is None:
            return
        n = self.c_regioes.currentData()
        passo = max(self.c_passo.value() / 2, 0.01)
        inicio = max(0.01 if self.c_tipo.currentData() == "folga" else 0.3, v - passo * (n // 2))
        for wd, val in ((self.c_passo, passo), (self.c_inicio, inicio)):
            wd.blockSignals(True)
            wd.setValue(val)
            wd.blockSignals(False)
        self._gerar_lista()
        QMessageBox.information(self, "Teste refinado", f"Novo teste de {_br(inicio, 2)} em diante, aumentando de "
                                f"{_br(passo, 2)}. Salve e imprima de novo para chegar ao valor exato.")

    def _medidas_cubo(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Medidas do cubo")
        l = QVBoxLayout(dlg)
        ex = QLabel("Meça o cubo já lavado e curado com o paquímetro. Lado X = lado com um entalhe; "
                    "lado Y = lado com dois entalhes; Z = altura.")
        ex.setWordWrap(True)
        l.addWidget(ex)
        g = QGridLayout()
        campos = {}
        for i, (k, txt, nominal) in enumerate((("x", "Largura (X)", 20.0), ("y", "Profundidade (Y)", 20.0),
                                                ("z", "Altura (Z)", 10.0), ("furo", "Furo", 10.0))):
            sp = QDoubleSpinBox()
            sp.setRange(nominal * 0.8, nominal * 1.2)
            sp.setDecimals(2)
            sp.setSingleStep(0.01)
            sp.setSuffix(" mm")
            sp.setValue(nominal)
            g.addWidget(QLabel(f"{txt} (deveria ser {_br(nominal, 0)} mm)"), i, 0)
            g.addWidget(sp, i, 1)
            campos[k] = sp
        l.addLayout(g)
        ok = QPushButton("Calcular e aplicar no perfil")
        ok.setObjectName("principal")
        ok.clicked.connect(dlg.accept)
        l.addWidget(ok)
        if dlg.exec() != QDialog.Accepted:
            return
        atual = {k: self.campos[f"escala_{k}"].value() for k in "xyz"}
        nominal = {"x": 20.0, "y": 20.0, "z": 10.0}
        novo = {k: atual[k] * nominal[k] / campos[k].value() for k in "xyz"}
        for k in "xyz":
            self.campos[f"escala_{k}"].setValue(round(novo[k], 2))
        dif_furo = 10.0 - campos["furo"].value()
        txt = (f"Correção de medida: X {_br(novo['x'], 2)}%, Y {_br(novo['y'], 2)}%, Z {_br(novo['z'], 2)}%.\n\n")
        if abs(dif_furo) >= 0.05:
            txt += (f"O furo saiu {_br(abs(dif_furo), 2)} mm {'menor' if dif_furo > 0 else 'maior'} que o desenho. "
                    f"{'Isso é normal na resina: ' if dif_furo > 0 else ''}para encaixes, use uma folga de pelo menos "
                    f"{_br(max(0.05, dif_furo / 2 + 0.05), 2)} mm.\n\n")
        txt += "Quer salvar no perfil da resina?"
        if QMessageBox.question(self, "Correção calculada", txt) == QMessageBox.Yes:
            self._salvar_perfil()

    def _malhas_calibracao(self, valores):
        tipo = self.c_tipo.currentData()
        regs = cb.layout(1 if tipo == "medida" else len(valores))
        chave = (tipo, tuple(round(t, 3) for t in valores), self.c_peca.currentData())
        if self._cache_mesa and self._cache_mesa[0] == chave:
            return self._cache_mesa[1], regs
        if tipo == "medida":
            malhas = cb.montar_mesa([cb.cubo_medida()], regs)
        elif tipo == "folga":
            malhas = cb.montar_mesa([cb.peca_folga(f) for f in valores], regs)
        elif self.c_peca.currentData() == "selecionada":
            m = self.peca_sel.copy()
            if not cb.cabe(m, regs):
                QMessageBox.information(self, "Peça grande demais", "A peça selecionada não cabe nas regiões. "
                                        "Use menos regiões ou a peça padrão.")
                self.c_peca.setCurrentIndex(0)
                return self._malhas_calibracao(valores)
            malhas = cb.montar_mesa(m, regs)
        else:
            malhas = cb.montar_mesa([cb._rotulo(t) for t in valores], regs)
        self._cache_mesa = (chave, malhas)
        return malhas, regs

    def _ler_perfis(self):
        try:
            d = json.loads(self.j.config.value("perfis_resina", "{}"))
        except Exception:
            d = {}
        todos = {PERFIL_PADRAO: ft.Perfil().para_dict()}
        todos.update(d)
        return todos

    def _carregar_perfil(self, nome):
        dados = ft.Perfil(**self._todos.get(nome, {})).para_dict()
        for k, w in self.campos.items():
            w.blockSignals(True)
            w.setValue(dados[k])
            w.blockSignals(False)
        self.espelhar.setChecked(bool(dados.get("espelhar", False)))
        self.aa.blockSignals(True)
        i = self.aa.findData(int(dados.get("antialias", 1)))
        self.aa.setCurrentIndex(max(i, 0))
        self.aa.blockSignals(False)
        self.duas.blockSignals(True)
        self.duas.setChecked(bool(dados.get("duas_etapas", False)))
        self.duas.blockSignals(False)
        self._duas_mudou()
        self.j.config.setValue("perfil_atual", nome)
        self._timer_refatiar.start(50)

    def _perfil(self):
        return ft.Perfil(**{k: w.value() for k, w in self.campos.items()}, espelhar=self.espelhar.isChecked(),
                         duas_etapas=self.duas.isChecked(), antialias=self.aa.currentData())

    def _novo_fatiador(self):
        p = self._perfil()
        if not self.calibracao:
            return ft.Fatiador(self.malhas, p)
        tipo = self.c_tipo.currentData()
        valores = [p.exposicao] if tipo == "medida" else self._valores()
        if not valores:
            return None
        malhas, regs = self._malhas_calibracao(valores)
        if tipo == "exposicao":
            base = [p.exposicao_base * t / max(p.exposicao, 0.01) for t in valores] if self.c_base.isChecked() else None
            return cb.FatiadorCalibracao(malhas, p, regs, valores, base,
                                         rotulos=[f"{_br(t, 2)} s" for t in valores])
        rot = ["Cubo 20 mm"] if tipo == "medida" else [f"folga {_br(f, 2)} mm" for f in valores]
        return cb.FatiadorCalibracao(malhas, p, regs, [p.exposicao] * len(regs), rotulos=rot)

    def _salvar_perfil(self):
        nome, ok = QInputDialog.getText(self, "Salvar perfil", "Nome da resina (ex.: Elegoo ABS-like cinza):",
                                        text="" if self.perfis.currentText() == PERFIL_PADRAO else self.perfis.currentText())
        if not ok or not nome.strip() or nome.strip() == PERFIL_PADRAO:
            return
        nome = nome.strip()
        self._todos[nome] = self._perfil().para_dict()
        proprios = {k: v for k, v in self._todos.items() if k != PERFIL_PADRAO}
        self.j.config.setValue("perfis_resina", json.dumps(proprios, ensure_ascii=False))
        if self.perfis.findText(nome) < 0:
            self.perfis.addItem(nome)
        self.perfis.setCurrentText(nome)

    # ------------------------------------------------------------ prévia
    def _refatiar(self):
        atual = self.slider.value()
        fat = self._novo_fatiador()
        if fat is None:
            self.resumo.setText("Digite pelo menos um tempo válido.")
            return
        self.fat = fat
        n = max(self.fat.n_camadas, 1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, n - 1)
        self.slider.setValue(min(atual, n - 1) if atual else n // 3)
        self.slider.blockSignals(False)
        self.num.blockSignals(True)
        self.num.setRange(1, n)
        self.num.blockSignals(False)
        vol = self.fat.volume_ml()
        p = self.fat.perfil
        extra = ""
        if self.calibracao:
            tipo = self.c_tipo.currentData()
            if tipo == "exposicao":
                ts = self.fat.tempos
                extra = (f"{len(ts)} regiões de {_br(min(ts), 2)} s a {_br(max(ts), 2)} s<br>"
                         f"{len(list(self.fat.plano()))} imagens no total<br>")
            elif tipo == "folga":
                vs = self._valores()
                extra = f"{len(vs)} regiões, folgas de {_br(min(vs), 2)} a {_br(max(vs), 2)} mm<br>"
            else:
                extra = "Cubo de 20 × 20 × 10 mm<br>"
        self.resumo.setText(
            extra +
            f"<b>{self.fat.n_camadas}</b> camadas de {_br(p.altura_camada, 3)} mm, altura {_br(self.fat.altura)} mm<br>"
            f"Tempo estimado: <b>{_tempo(self.fat.tempo_total())}</b><br>"
            f"Resina: <b>{_br(vol)} ml</b> ({_br(self.fat.peso_g(vol))} g"
            + (f", custo {_br(self.fat.custo(vol), 2)}" if p.preco_litro else "") + ")")
        self._mostrar_camada()

    def _mostrar_camada(self):
        if self.fat is None:
            return
        k = self.slider.value()
        self.num.blockSignals(True)
        self.num.setValue(k + 1)
        self.num.blockSignals(False)
        esc = 4
        img, r0, c0, W, H = self.fat.camada(k, esc)
        tela = np.zeros((H, W), np.uint8)
        borda = 2
        tela[:borda, :] = tela[-borda:, :] = 1
        tela[:, :borda] = tela[:, -borda:] = 1
        area = 0.0
        regs = getattr(self.fat, "regioes", None)
        if img is not None:
            sub = tela[r0:r0 + img.shape[0], c0:c0 + img.shape[1]]
            sub[img] = 2
            if regs:
                for i in range(len(regs)):
                    sub[img & self.fat._mascara([i], r0, c0, img.shape, esc)] = 3 + i
            area = img.sum() * (self.fat.imp["pixel"] * esc) ** 2
        tela = np.ascontiguousarray(np.flipud(tela))
        q = QImage(tela.data, W, H, W, QImage.Format_Indexed8)
        c = self.cores
        tabela = [QColor(c["fundo3d_baixo"]).rgb(), QColor(c["borda"]).rgb(), QColor("#F4F1EA").rgb()]
        if regs:
            n = len(regs)
            for i in range(n):
                f = i / max(n - 1, 1)
                tabela.append(QColor.fromHsvF(0.58 - 0.5 * f, 0.55, 0.98).rgb())
        q.setColorTable(tabela)
        pm = QPixmap.fromImage(q.copy()).scaled(self.tela.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if regs:
            pin = QPainter(pm)
            esc_x = pm.width() / (W * self.fat.imp["pixel"] * esc)
            ox, oy = pm.width() / 2, pm.height() / 2
            pin.setPen(QPen(QColor(c["suave"]), 1, Qt.DashLine))
            fonte = QFont()
            fonte.setPointSize(10)
            fonte.setBold(True)
            pin.setFont(fonte)
            for i, (a, b, cc, d) in enumerate(regs):
                x, y = ox + a * esc_x, oy - d * esc_x
                ww, hh = (cc - a) * esc_x, (d - b) * esc_x
                pin.setPen(QPen(QColor(c["suave"]), 1, Qt.DashLine))
                pin.drawRect(int(x), int(y), int(ww), int(hh))
                pin.setPen(QColor(tabela[3 + i]))
                rot = self.fat.rotulos[i] if getattr(self.fat, "rotulos", None) else \
                    f"{_br(self.fat.tempos_regioes(k)[i], 2)} s"
                if self.c_tipo.currentData() == "exposicao" and k < self.fat.perfil.camadas_base:
                    rot = f"{_br(self.fat.tempos_regioes(k)[i], 1)} s (base)"
                pin.drawText(int(x + 8), int(y + 18), rot)
            pin.end()
        self.tela.setPixmap(pm)
        base = " (camada de base)" if k < self.fat.perfil.camadas_base else ""
        self.info_camada.setText(f"Camada {k + 1} de {self.fat.n_camadas}{base}   Altura "
                                 f"{_br(self.fat.z_da_camada(k) + self.fat.perfil.altura_camada / 2, 2)} mm   "
                                 f"Área iluminada {_br(area)} mm²")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._timer.start(30)

    # ------------------------------------------------------------ exportar
    def _previa_rgb(self, fat):
        """Imagem pequena que a impressora mostra na lista de arquivos."""
        from PIL import Image
        if self.preview_png:
            try:
                return np.asarray(Image.open(io.BytesIO(self.preview_png)).convert("RGB"))
            except Exception:
                pass
        k = max(0, min(fat.n_camadas - 1, max(fat.perfil.camadas_base + 2, fat.n_camadas // 3)))
        img, r0, c0, W, H = fat.camada(k, 8)
        tela = np.zeros((H, W, 3), np.uint8)
        if img is not None:
            tela[r0:r0 + img.shape[0], c0:c0 + img.shape[1]][img] = (242, 163, 58)
        return np.flipud(tela)

    def _exportar(self):
        pasta = self.j.config.value("ultima_pasta", os.path.expanduser("~"))
        nome = "teste_calibracao" if self.calibracao else self.nome
        caminho, filtro = QFileDialog.getSaveFileName(
            self, "Salvar arquivo para a impressora", os.path.join(pasta, f"{nome}.ctb"),
            "Arquivo da Saturn 2 8K (*.ctb);;ZIP do ChituBox (*.zip)")
        if not caminho:
            return
        formato = "zip" if (caminho.lower().endswith(".zip") or "zip" in filtro.lower()) else "ctb"
        if not caminho.lower().endswith("." + formato):
            caminho += "." + formato
        fat = self._novo_fatiador()
        if fat is None:
            return
        dlg = QProgressDialog("Gerando as camadas…", "Cancelar", 0, 100, self)
        dlg.setWindowTitle("Salvando")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        self._cancelar = False
        dlg.canceled.connect(lambda: setattr(self, "_cancelar", True))
        sinais = _Sinais()
        self._sinais = sinais
        sinais.progresso.connect(dlg.setValue)

        def fim(r):
            dlg.reset()
            if isinstance(r, Exception):
                QMessageBox.warning(self, "Não foi possível salvar", str(r))
            elif r:
                self.j.config.setValue("ultima_pasta", os.path.dirname(caminho))
                extra = ("\n\nCopie para o pen drive da impressora e escolha o arquivo na tela dela."
                         if formato == "ctb" else "")
                QMessageBox.information(self, "Arquivo salvo", f"Arquivo salvo em:\n{caminho}\n\n"
                                        f"{fat.n_camadas} camadas, tempo estimado {_tempo(fat.tempo_total())}.{extra}")
        sinais.fim.connect(fim)

        def tarefa():
            try:
                if formato == "ctb":
                    from . import ctb
                    r = ctb.gravar(fat, caminho, self._previa_rgb(fat), sinais.progresso.emit, lambda: self._cancelar)
                else:
                    r = ft.exportar_zip(fat, caminho, self.nome, self.preview_png, sinais.progresso.emit,
                                        lambda: self._cancelar)
            except Exception as e:
                r = e
            sinais.fim.emit(r)
        threading.Thread(target=tarefa, daemon=True).start()
