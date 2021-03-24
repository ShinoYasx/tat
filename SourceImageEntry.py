from PySide6.QtWidgets import QWidget, QCheckBox, QSizePolicy
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from ImageEntry import ImageEntry


class SourceImageEntry(ImageEntry):
    def __init__(self, parent: QWidget, image: QImage, path: str, name: str):
        super(SourceImageEntry, self).__init__(parent, image, path, name)
        layout = self.layout()

        self.__check_box = QCheckBox(self)
        self.__check_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.__check_box.setChecked(True)

        layout.addWidget(self.__check_box, alignment=Qt.AlignHCenter)

    def isChecked(self) -> bool:
        return self.__check_box.isChecked()

    def setChecked(self, checked):
        self.__check_box.setChecked(checked)