import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

import numpy as np
import cv2 as cv

from PySide6.QtWidgets import QFileDialog, QLabel, QLayout, QDialog, QProgressBar
from PySide6.QtCore import Slot, Signal, SignalInstance, QThread, QRunnable, QObject, QThreadPool

from .api import Tat
from .checkable_image_entry import CheckableImageEntry
from .preview_window import PreviewWindow
from .cluster_image_entry import ClusterImageEntry
from .cluster_editor import ClusterEditor
from .layer_data import LayerData
from .ui_main_window import Ui_MainWindow
from .ui_progress_bar import Ui_ProgressBar
from .utils import load_image, apply_colormap, create_cluster, array3d_to_pixmap


class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    intermediate = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        self.kwargs['progress_callback'] = self.signals.progress
        self.kwargs['intermediate_callback'] = self.signals.intermediate

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class MainWindow(PreviewWindow):
    def __init__(self):
        super(MainWindow, self).__init__(None)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.thread_pool = QThreadPool()

        self.input_directory = ""
        self.output_directory = ""
        self.merger_directory: Optional[str] = None
        self.editor_window: Optional[ClusterEditor] = None

        self.__generated_images_entries: list[ClusterImageEntry] = []

        self.ui.buttonInputDir.clicked.connect(self.load_input_directory)
        self.ui.buttonOutputDir.clicked.connect(self.load_output_directory)
        self.ui.buttonGenerate.clicked.connect(self.generate_handler)
        self.ui.buttonCheckUncheck.clicked.connect(self.select_deselect)
        self.ui.buttonClearGenerated.clicked.connect(self.clear_generated)

    def source_layout(self) -> QLayout:
        return self.ui.scrollAreaWidgetContentsSrc.layout()

    def image_preview(self) -> QLabel:
        return self.ui.imagePreview

    def clear_image_entries(self):
        super(MainWindow, self).clear_image_entries()
        for ime in self.__generated_images_entries:
            ime.close()
        self.__generated_images_entries.clear()

    def open_preview_window(self, calling_image_entry: ClusterImageEntry):
        if self.editor_window is not None and self.editor_window.isVisible():
            self.editor_window.activateWindow()
            return
        self.editor_window = ClusterEditor(self, calling_image_entry)
        self.editor_window.register_merge_handler(self.merge_layers)
        self.editor_window.show()

    def merge_layers(self, layers_indices: list[int]) -> None:
        """
        Merge all the specified layers
        :param layers_indices: A range of the layers to merge
        :return: None
        """
        if len(layers_indices) == 0:
            return

        merged_cluster_ime: list[ClusterImageEntry] = []

        first = True
        while len(self.__generated_images_entries) > 0:
            ime: ClusterImageEntry = self.__generated_images_entries.pop(0)
            merged: Optional[np.ndarray] = None
            parent_layers: list[int] = []
            for i in layers_indices:
                layer_data: LayerData = ime.get_layer_data(i)
                if layer_data.is_merger:
                    assert layer_data.parent_layers is not None
                    parent_layers.extend(layer_data.parent_layers)
                else:
                    assert layer_data.layer_index is not None
                    parent_layers.append(layer_data.layer_index)

                layer = np.load(layer_data.array_path)
                merged = layer if merged is None else merged | layer

            for i in sorted(layers_indices, reverse=True):
                ime.remove_layer_data(i)

            if merged is None:
                break

            colored = apply_colormap(merged)

            merged_path_no_ext = os.path.join(self.merger_directory,
                                              f"{ime.basename}_layers_{LayerData.indices2str(parent_layers)}")
            merged_image_path = f"{merged_path_no_ext}.png"
            merged_array_path = f"{merged_path_no_ext}.npy"

            cv.imwrite(merged_image_path, colored)
            np.save(merged_array_path, merged)
            ime.add_layer_data(
                LayerData(merged_image_path, merged_array_path, is_merger=True, parent_layers=parent_layers))

            new_cluster_array = create_cluster(
                [np.load(ime.get_layer_data(i).array_path) for i in range(ime.layer_count())])

            new_cluster_colored = apply_colormap(new_cluster_array, cv.COLORMAP_JET)
            new_cluster_colored_image = array3d_to_pixmap(new_cluster_colored).toImage()

            new_cluster_path_no_ext = os.path.join(self.merger_directory, f"{ime.basename}_cluster")
            new_cluster_image_path = f"{new_cluster_path_no_ext}.png"
            new_cluster_array_path = f"{new_cluster_path_no_ext}.npy"

            np.save(new_cluster_array_path, new_cluster_array)
            cv.imwrite(new_cluster_image_path, new_cluster_colored)

            new_ime = ClusterImageEntry(ime.parent(), new_cluster_colored_image, new_cluster_image_path,
                                        new_cluster_array_path, ime.basename, ime.layers_data)
            new_ime.registerMousePressHandler(self.image_entry_click_handler)
            new_ime.register_mouse_double_click_action(self.open_preview_window)
            merged_cluster_ime.append(new_ime)
            ime.close()
            self.ui.scrollAreaWidgetContentsDst.layout().addWidget(new_ime)

            if first:
                self.set_preview_image(new_cluster_colored_image, new_ime)
                first = False

        self.__generated_images_entries = merged_cluster_ime

    def unmerge_layer(self):
        pass

    @Slot()
    def clear_generated(self):
        for ime in self.__generated_images_entries:
            ime.close()
        self.__generated_images_entries.clear()
        self.image_preview().setText("Preview")
        self._selected_image_entry = None

    @Slot()
    def load_input_directory(self):
        self.input_directory = QFileDialog.getExistingDirectory(self)
        if len(self.input_directory) == 0:
            return

        self.clear_image_entries()
        self.clear_preview_image()

        # self.ui.labelInDir.setText(f"Loaded: {self.input_directory}")

        src_layout = self.source_layout()
        first = True
        for entry in os.scandir(self.input_directory):
            if not Tat.is_image(entry.path):
                continue

            qim = load_image(entry.path)

            ime = CheckableImageEntry(src_layout.parent(), qim, entry.name, entry.path)
            ime.registerMousePressHandler(self.image_entry_click_handler)
            self.add_source_image_entry(ime)

            if first:
                self.set_preview_image(qim, ime)
                first = False

        if len(self.output_directory) != 0:
            self.ui.buttonGenerate.setEnabled(True)

    @Slot()
    def load_output_directory(self):
        self.output_directory = QFileDialog.getExistingDirectory(self)
        if len(self.output_directory) == 0:
            return

        self.merger_directory = os.path.join(self.output_directory, "merged")
        Path(self.merger_directory).mkdir(exist_ok=True)

        # self.ui.labelOutDir.setText(f"Loaded: {self.output_directory}")
        if len(self.input_directory) != 0:
            self.ui.buttonGenerate.setEnabled(True)

    @Slot()
    def generate_handler(self):
        self.ui.buttonGenerate.setEnabled(False)

        progress_bar = QDialog(self)
        progress_bar.ui = Ui_ProgressBar()
        progress_bar.ui.setupUi(progress_bar)

        selected_entries: list[CheckableImageEntry] = []
        for ime in self._source_image_entries:
            if ime.isChecked():
                selected_entries.append(ime)

        @Slot()
        def finished_generating():
            progress_bar.close()
            self.ui.buttonGenerate.setEnabled(True)

        worker = Worker(self.generate_cluster, selected_entries)
        worker.signals.progress.connect(
            lambda n: progress_bar.ui.progressBar.setValue(n))
        worker.signals.finished.connect(lambda: progress_bar.close())
        worker.signals.intermediate.connect(self.add_cluster_image)

        progress_bar.ui.progressBar.setMaximum(len(selected_entries))
        progress_bar.show()

        self.thread_pool.start(worker)

    @Slot()
    def add_cluster_image(self, data: tuple[str, str, str, list[LayerData]]):
        image_path, array_path, name, layers_data = data
        container: QLayout = self.ui.scrollAreaWidgetContentsDst.layout()
        ime = ClusterImageEntry(container.parent(), load_image(image_path), image_path, array_path, name, layers_data)
        ime.registerMousePressHandler(self.image_entry_click_handler)
        ime.register_mouse_double_click_action(self.open_preview_window)
        container.addWidget(ime)
        if len(self.__generated_images_entries) == 0:
            self.set_preview_image(load_image(ime.image_path), ime)
        self.__generated_images_entries.append(ime)

    @Slot()
    def generate_cluster(self, entries: list[CheckableImageEntry], intermediate_callback: SignalInstance,
                         progress_callback: SignalInstance):
        progress = 0
        for ime in entries:
            input_basename_no_ext = (lambda basename: basename[0:basename.rfind(".")])(os.path.basename(ime.image_path))
            layers, cluster = Tat.generate_layers(np.asarray(cv.imread(ime.image_path, flags=cv.IMREAD_GRAYSCALE)),
                                                  self.ui.clusterCount.value(), self.ui.runCount.value(),
                                                  self.ui.maxIterCount.value())

            layers_data: list[LayerData] = []
            for i, layer in enumerate(layers):
                output_path_no_ext = os.path.join(self.output_directory, f"{input_basename_no_ext}_layer_{i}")
                output_image_path = f"{output_path_no_ext}.png"
                output_array_path = f"{output_path_no_ext}.npy"
                np.save(output_array_path, layer)
                cv.imwrite(output_image_path, apply_colormap(layer, cv.COLORMAP_VIRIDIS))
                layers_data.append(LayerData(output_image_path, output_array_path, layer_index=i))

            output_path_no_ext = os.path.join(self.output_directory, f"{input_basename_no_ext}_cluster")
            output_image_path = f"{output_path_no_ext}.png"
            output_array_path = f"{output_path_no_ext}.npy"

            np.save(output_array_path, cluster)
            cv.imwrite(output_image_path, apply_colormap(cluster, cv.COLORMAP_JET))
            progress += 1
            progress_callback.emit(progress)
            intermediate_callback.emit((output_image_path, output_array_path, input_basename_no_ext, layers_data))