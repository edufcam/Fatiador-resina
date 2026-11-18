"""Fatiador Resina - ponto de partida do programa."""
import os
import sys

os.environ.setdefault("QT_API", "pyside6")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplashScreen  # noqa: E402

from fatiador import VERSAO, NOME  # noqa: E402
from fatiador.recursos import recurso  # noqa: E402


def tela_abertura():
    pm = QPixmap(520, 300)
    pm.fill(QColor("#16181C"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    logo = QPixmap(recurso("logo.png"))
    p.drawPixmap(40, 80, 120, 120, logo)
    p.setPen(QColor("#ECEAE6"))
    f = QFont("Segoe UI", 24)
    f.setWeight(QFont.DemiBold)
    p.setFont(f)
    p.drawText(190, 135, NOME)
    p.setPen(QColor("#9BA1AA"))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(192, 165, f"Versão {VERSAO} para Elegoo Saturn 2 8K")
    p.setPen(QColor("#F2A33A"))
    p.drawText(192, 240, "Carregando…")
    p.end()
    return QSplashScreen(pm)


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(NOME)
    app.setOrganizationName("FatiadorResina")
    app.setWindowIcon(QIcon(recurso("icone.ico")))
    abertura = tela_abertura()
    abertura.show()
    app.processEvents()

    from fatiador.janela import iniciar  # carregamento pesado (3D) acontece aqui
    iniciar(app, abertura)


if __name__ == "__main__":
    main()
