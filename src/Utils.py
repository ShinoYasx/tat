from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import QSize

import numpy as np
import cv2 as cv
from typing import Optional


def fit_to_frame(image: QPixmap, frame: QSize) -> QPixmap:
    frame_width, frame_height = frame.toTuple()
    dw = abs(image.width() - frame_width)
    dh = abs(image.height() - frame_height)
    return image.scaledToWidth(frame_width) if dw > dh else image.scaledToHeight(frame_height)


def load_image(path: str) -> QImage:
    return QImage(path)


def apply_colormap(image: np.ndarray, colormap=cv.COLORMAP_VIRIDIS) -> np.ndarray:
    image = image - np.min(image)
    return cv.applyColorMap(np.uint8(255 * (image / np.max(image))), colormap)


def array2d_to_pixmap(array: np.ndarray, normalize=False, colormap: int = cv.COLORMAP_VIRIDIS) -> QPixmap:
    assert array.ndim == 2
    if normalize:
        array = apply_colormap(array, colormap)
        height, width, color_bytes = array.shape
        return QPixmap.fromImage(QImage(array.data, width, height, color_bytes * width, QImage.Format_BGR888))
    height, width = array.shape
    return QPixmap.fromImage(QImage(array.data, width, height, width, QImage.Format_Grayscale8))