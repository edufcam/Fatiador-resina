"""Cores, estilo e ícones. A cor de destaque é o âmbar da tampa da Saturn."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPalette, QColor
from PySide6.QtSvg import QSvgRenderer

ESCURO = {
    "fundo": "#16181C", "painel": "#1E2126", "elevado": "#272B32", "borda": "#323740",
    "texto": "#ECEAE6", "suave": "#9BA1AA", "destaque": "#F2A33A", "sobre_destaque": "#1B1206",
    "perigo": "#E5604D", "ok": "#4CB782",
    "fundo3d_baixo": "#121418", "fundo3d_topo": "#2A2F37",
    "mesa": "#2B3037", "grade": "#4C5562", "volume": "#68717E",
    "peca": "#A9B7C6", "peca_sel": "#F2A33A", "peca_fora": "#E5604D", "suporte": "#7F8FA1",
}
CLARO = {
    "fundo": "#E9EBEE", "painel": "#F5F6F7", "elevado": "#FFFFFF", "borda": "#D3D7DD",
    "texto": "#1D2026", "suave": "#5D6470", "destaque": "#D9861C", "sobre_destaque": "#FFFFFF",
    "perigo": "#C9432F", "ok": "#2E8B5E",
    "fundo3d_baixo": "#CDD3DA", "fundo3d_topo": "#F7F8FA",
    "mesa": "#B9C0C9", "grade": "#9AA3AE", "volume": "#8A94A0",
    "peca": "#6F8499", "peca_sel": "#D9861C", "peca_fora": "#C9432F", "suporte": "#8E9AA8",
}

FONTE = '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif'


def _setas(c):
    import os
    from .recursos import pasta_dados
    pasta = os.path.join(pasta_dados(), "estilo")
    os.makedirs(pasta, exist_ok=True)
    caminhos = {}
    for nome, pontos, cor in (("cima", "6 15 12 9 18 15", c["suave"]), ("baixo", "6 9 12 15 18 9", c["suave"]),
                              ("check", "5 12 10 17 19 7", c["sobre_destaque"])):
        arq = os.path.join(pasta, f"seta_{nome}_{c['texto'].lstrip('#')}.svg")
        with open(arq, "w", encoding="utf-8") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
                    f'stroke="{cor}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
                    f'<polyline points="{pontos}"/></svg>')
        caminhos[nome] = arq.replace("\\", "/")
    return caminhos


def folha_de_estilo(c):
    s = _setas(c)
    return f"""
* {{ font-family: {FONTE}; font-size: 13px; color: {c['texto']}; }}
QMainWindow, QWidget#raiz {{ background: {c['fundo']}; }}
QWidget#lateral, QWidget#painel {{ background: {c['painel']}; }}
QWidget#cabecalho {{ background: {c['painel']}; border-bottom: 1px solid {c['borda']}; }}
QLabel#marca {{ font-size: 15px; font-weight: 600; }}
QLabel#versao {{ color: {c['suave']}; font-size: 12px; }}
QLabel#titulo {{ font-size: 15px; font-weight: 600; padding: 4px 2px; }}
QLabel#rotulo {{ color: {c['suave']}; font-size: 12px; }}
QLabel#numero {{ font-size: 20px; font-weight: 600; }}
QLabel#mesa_ok {{ color: {c['ok']}; font-weight: 600; }}
QLabel#mesa_fora {{ color: {c['perigo']}; font-weight: 600; }}
QLabel#vazio {{ color: {c['suave']}; font-size: 13px; padding: 16px; }}
QFrame#cartao {{ background: {c['elevado']}; border: 1px solid {c['borda']}; border-radius: 10px; }}
QFrame#barra3d {{ background: transparent; }}

QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px 10px; }}
QToolButton:hover {{ background: {c['elevado']}; }}
QToolButton:pressed {{ background: {c['borda']}; }}
QToolButton#segmento {{ background: {c['elevado']}; border: 1px solid {c['borda']}; border-radius: 0; padding: 5px 12px; }}
QToolButton#segmento:checked {{ background: {c['destaque']}; color: {c['sobre_destaque']}; border-color: {c['destaque']}; }}

QPushButton {{ background: {c['elevado']}; border: 1px solid {c['borda']}; border-radius: 6px;
              padding: 7px 12px; min-height: 22px; }}
QPushButton:hover {{ border-color: {c['destaque']}; }}
QPushButton:pressed {{ background: {c['borda']}; }}
QPushButton:checked {{ background: {c['destaque']}; color: {c['sobre_destaque']}; border-color: {c['destaque']}; }}
QPushButton:disabled {{ color: {c['suave']}; }}
QPushButton#principal {{ background: {c['destaque']}; color: {c['sobre_destaque']}; border: none; font-weight: 600; }}
QPushButton#principal:hover {{ background: {c['destaque']}; border: 1px solid {c['texto']}; }}

QDoubleSpinBox, QComboBox, QLineEdit {{ background: {c['fundo']}; border: 1px solid {c['borda']};
              border-radius: 6px; padding: 5px 8px; min-height: 20px; }}
QDoubleSpinBox {{ padding-right: 22px; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 20px; border: none; background: transparent;
              subcontrol-origin: border; }}
QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['elevado']}; }}
QDoubleSpinBox::up-arrow {{ image: url("{s['cima']}"); width: 12px; height: 12px; }}
QDoubleSpinBox::down-arrow {{ image: url("{s['baixo']}"); width: 12px; height: 12px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{s['baixo']}"); width: 12px; height: 12px; }}
QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border-color: {c['destaque']}; }}
QComboBox QAbstractItemView {{ background: {c['elevado']}; selection-background-color: {c['destaque']};
              selection-color: {c['sobre_destaque']}; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 8px; margin: 2px 0; }}
QListWidget::item:selected {{ background: {c['elevado']}; border: 1px solid {c['destaque']}; }}
QListWidget::item:hover:!selected {{ background: {c['elevado']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 10px; margin-right: 2px; color: {c['suave']};
              border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['texto']}; border-bottom: 2px solid {c['destaque']}; font-weight: 600; }}
QTabBar::tab:disabled {{ color: {c['borda']}; }}
QTabBar::tab:hover:!selected:!disabled {{ color: {c['texto']}; }}

QSlider::groove:horizontal {{ height: 6px; background: {c['borda']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c['destaque']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {c['texto']}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
QCheckBox {{ spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['suave']}; border-radius: 4px; background: {c['fundo']}; }}
QCheckBox::indicator:hover {{ border-color: {c['destaque']}; }}
QCheckBox::indicator:checked {{ background: {c['destaque']}; border-color: {c['destaque']}; image: url("{s['check']}"); }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['borda']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QSplitter::handle {{ background: {c['borda']}; }}
QStatusBar {{ background: {c['painel']}; color: {c['suave']}; border-top: 1px solid {c['borda']}; }}
QToolTip {{ background: {c['elevado']}; color: {c['texto']}; border: 1px solid {c['borda']}; padding: 6px; }}
QMenu {{ background: {c['elevado']}; border: 1px solid {c['borda']}; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['destaque']}; color: {c['sobre_destaque']}; }}
QProgressBar {{ background: {c['fundo']}; border: 1px solid {c['borda']}; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {c['destaque']}; border-radius: 5px; }}
"""


def paleta(c):
    p = QPalette()
    for papel, chave in ((QPalette.Window, "fundo"), (QPalette.WindowText, "texto"), (QPalette.Base, "fundo"),
                         (QPalette.AlternateBase, "painel"), (QPalette.Text, "texto"), (QPalette.Button, "elevado"),
                         (QPalette.ButtonText, "texto"), (QPalette.ToolTipBase, "elevado"),
                         (QPalette.ToolTipText, "texto"), (QPalette.Highlight, "destaque"),
                         (QPalette.HighlightedText, "sobre_destaque"), (QPalette.PlaceholderText, "suave")):
        p.setColor(papel, QColor(c[chave]))
    return p


# Ícones de traço (estilo Lucide, licença ISC)
_ICONES = {
    "importar": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "abrir": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    "salvar": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "exportar": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "desfazer": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "refazer": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "sol": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "lua": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "copiar": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "lixo": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "olho": '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "olho_fechado": '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.4 10.4 0 0 1 12 5c7 0 10 7 10 7a13.2 13.2 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.5 13.5 0 0 0 2 12s3 7 10 7a9.7 9.7 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/>',
    "varinha": '<path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5"/>',
    "centro": '<circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/>',
    "deitar": '<path d="M12 17V3M6 11l6 6 6-6M19 21H5"/>',
    "atualizar": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "tesoura": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/>',
    "grade": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "suporte": '<path d="M4 4h16"/><path d="M8 4l-1 16M16 4l1 16M12 4v16"/><path d="M5 20h14"/>',
    "mais": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "menos": '<line x1="5" y1="12" x2="19" y2="12"/>',
    "info": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
}


def icone(nome, cor, tamanho=20):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
           f'stroke="{cor}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICONES[nome]}</svg>')
    render = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(tamanho * 2, tamanho * 2)
    pm.fill(Qt.transparent)
    pin = QPainter(pm)
    render.render(pin)
    pin.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)
