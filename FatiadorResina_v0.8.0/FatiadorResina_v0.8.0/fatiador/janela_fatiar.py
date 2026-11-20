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
    def __init__(self, janela, malhas, nome, preview_png):
        super().__init__(janela)
        self.j = janela
        self.cores = janela.cores
        self.nome, self.preview_png, self.malhas = nome, preview_png, malhas
        self.setWindowTitle("Fatiar para a Saturn 2 8K")
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
        caixa.setFixedWidth(330)
        l = QVBoxLayout(caixa)
        l.setContentsMargins(14, 12, 14, 12)
        t = QLabel("Perfil de resina")
        t.setObjectName("titulo")
        l.addWidget(t)
        self.perfis = QComboBox()
        self._todos = self._ler_perfis()
        self.perfis.addItems(list(self._todos))
        ultimo = self.j.config.value("perfil_atual", PERFIL_PADRAO)
        if ultimo in self._todos:
            self.perfis.setCurrentText(ultimo)
        self.perfis.currentTextChanged.connect(self._carregar_perfil)
        l.addWidget(self.perfis)

        g = QGridLayout()
        self.campos = {}

        def num(chave, txt, mn, mx, casas, suf, dica, passo=None):
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
            g.addWidget(lb, r, 0)
            g.addWidget(w, r, 1)
            self.campos[chave] = w

        num("altura_camada", "Altura da camada", 0.01, 0.2, 3, " mm", "0,05 mm é o padrão. Menor = mais detalhe e mais tempo", 0.005)
        num("exposicao", "Exposição", 0.5, 60, 2, " s", "Tempo de luz de cada camada normal", 0.1)
        num("exposicao_base", "Exposição da base", 1, 180, 1, " s", "Tempo de luz das primeiras camadas, que grudam na mesa", 1)
        num("camadas_base", "Camadas de base", 1, 50, 0, "", "Quantas camadas usam a exposição da base")
        num("luz_apagada", "Luz apagada", 0, 30, 1, " s", "Espera com a luz apagada antes de expor (resina assentar)", 0.5)
        num("subida", "Subida", 1, 20, 1, " mm", "Quanto a mesa sobe para descolar do filme", 0.5)
        num("vel_subida", "Velocidade de subida", 10, 600, 0, " mm/min", "Mais devagar = menos força no filme")
        num("vel_descida", "Velocidade de descida", 10, 600, 0, " mm/min", "Velocidade de volta da mesa")
        l.addLayout(g)
        self.espelhar = QCheckBox("Espelhar imagem")
        self.espelhar.setToolTip("Só mude se a peça sair espelhada na impressora")
        self.espelhar.toggled.connect(lambda _: self._timer_refatiar.start(300))
        l.addWidget(self.espelhar)
        b = QPushButton("Salvar como perfil…")
        b.setToolTip("Guardar estes valores com o nome da sua resina")
        b.clicked.connect(self._salvar_perfil)
        l.addWidget(b)
        aviso = QLabel("Os valores do perfil padrão são um ponto de partida. Ajuste pela ficha da sua resina "
                       "ou por um teste de calibração.")
        aviso.setObjectName("rotulo")
        aviso.setWordWrap(True)
        l.addWidget(aviso)
        l.addStretch(1)

        t = QLabel("Resumo")
        t.setObjectName("titulo")
        l.addWidget(t)
        self.resumo = QLabel("Fatiando…")
        self.resumo.setWordWrap(True)
        l.addWidget(self.resumo)
        self.b_salvar = QPushButton("Salvar arquivo para a impressora")
        self.b_salvar.setObjectName("principal")
        self.b_salvar.clicked.connect(self._exportar)
        l.addWidget(self.b_salvar)
        nota = QLabel("Gera o arquivo no formato ZIP do ChituBox (imagens de cada camada + comandos).")
        nota.setObjectName("rotulo")
        nota.setWordWrap(True)
        l.addWidget(nota)
        return caixa

    def _ler_perfis(self):
        try:
            d = json.loads(self.j.config.value("perfis_resina", "{}"))
        except Exception:
            d = {}
        todos = {PERFIL_PADRAO: ft.Perfil().para_dict()}
        todos.update(d)
        return todos

    def _carregar_perfil(self, nome):
        dados = self._todos.get(nome, ft.Perfil().para_dict())
        for k, w in self.campos.items():
            w.blockSignals(True)
            w.setValue(dados.get(k, ft.Perfil.CAMPOS[k]))
            w.blockSignals(False)
        self.espelhar.setChecked(bool(dados.get("espelhar", False)))
        self.j.config.setValue("perfil_atual", nome)
        self._timer_refatiar.start(50)

    def _perfil(self):
        return ft.Perfil(**{k: w.value() for k, w in self.campos.items()}, espelhar=self.espelhar.isChecked())

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
        self.fat = ft.Fatiador(self.malhas, self._perfil())
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
        self.resumo.setText(
            f"<b>{self.fat.n_camadas}</b> camadas de {_br(p.altura_camada, 3)} mm<br>"
            f"Altura: {_br(self.fat.altura)} mm<br>"
            f"Tempo estimado: <b>{_tempo(self.fat.tempo_total())}</b><br>"
            f"Resina: <b>{_br(vol)} ml</b>")
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
        if img is not None:
            tela[r0:r0 + img.shape[0], c0:c0 + img.shape[1]][img] = 2
            area = img.sum() * (self.fat.imp["pixel"] * esc) ** 2
        tela = np.ascontiguousarray(np.flipud(tela))
        q = QImage(tela.data, W, H, W, QImage.Format_Indexed8)
        c = self.cores
        from PySide6.QtGui import QColor
        q.setColorTable([QColor(c["fundo3d_baixo"]).rgb(), QColor(c["borda"]).rgb(), QColor("#F4F1EA").rgb()])
        pm = QPixmap.fromImage(q.copy()).scaled(self.tela.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.tela.setPixmap(pm)
        base = " (camada de base)" if k < self.fat.perfil.camadas_base else ""
        self.info_camada.setText(f"Camada {k + 1} de {self.fat.n_camadas}{base}   Altura "
                                 f"{_br(self.fat.z_da_camada(k) + self.fat.perfil.altura_camada / 2, 2)} mm   "
                                 f"Área iluminada {_br(area)} mm²")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._timer.start(30)

    # ------------------------------------------------------------ exportar
    def _exportar(self):
        pasta = self.j.config.value("ultima_pasta", os.path.expanduser("~"))
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar arquivo para a impressora",
                                                 os.path.join(pasta, f"{self.nome}.zip"), "ZIP do ChituBox (*.zip)")
        if not caminho:
            return
        if not caminho.lower().endswith(".zip"):
            caminho += ".zip"
        fat = ft.Fatiador(self.malhas, self._perfil())
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
                QMessageBox.information(self, "Arquivo salvo", f"Arquivo salvo em:\n{caminho}\n\n"
                                        f"{fat.n_camadas} camadas, tempo estimado {_tempo(fat.tempo_total())}.")
        sinais.fim.connect(fim)

        def tarefa():
            try:
                r = ft.exportar_zip(fat, caminho, self.nome, self.preview_png, sinais.progresso.emit,
                                    lambda: self._cancelar)
            except Exception as e:
                r = e
            sinais.fim.emit(r)
        threading.Thread(target=tarefa, daemon=True).start()
