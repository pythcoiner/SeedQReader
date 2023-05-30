import sys
import os
import re
from typing import List

from dataclasses import dataclass, field

from pathlib import Path

from PySide2.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPlainTextEdit, QProgressBar
from PySide2.QtGui import QImage, QPixmap, QIcon, QPalette, QColor
from PySide2.QtCore import Qt, QFile, QThread, Signal
from PySide2.QtUiTools import QUiLoader
from PySide2.QtGui import QTextOption

from PIL import ImageQt

from pyzbar import pyzbar

import qrcode

import cv2


MAX_LEN = 200
QR_DELAY = 400

def to_str(bin_):
    return bin_.decode('utf-8')


@dataclass
class QRCode:
    data: str = ''
    total_sequences: int = 0
    sequences_count: int = 0
    is_completed: bool = False

    def append(self, data: str):
        self.data_init(1)
        self.data = data
        self.sequences_count += 1
        self.is_completed = True

    def data_init(self, sequences: int):
        self.total_sequences = sequences
        self.sequences_count = 0


@dataclass
class MultiQRCode(QRCode):
    data_stack: list = field(default_factory=list)
    is_init: bool = False
    current: int = 0

    def append(self, data: tuple):
        # print(f'MultiQRCode.append({data})')
        sequence = data[0]
        total_sequences = data[1]

        data = data[2]
        if not self.is_init:
            self.data_init(total_sequences)
            self.is_init = True

        if not self.data_stack[sequence-1]:
            self.data_stack[sequence-1] = data
        else:
            if data != self.data_stack[sequence-1]:
                raise ValueError('Same sequences have different data!')
        self.check_complete()

    def data_init(self, sequences: int):
        # print('data_init()')
        super().data_init(sequences)
        self.data_stack = [None] * sequences

    def check_complete(self):
        fill_sequences = 0
        for i in self.data_stack:
            if i:
                fill_sequences += 1

        self.sequences_count = fill_sequences

        if fill_sequences == self.total_sequences:
            self.is_completed = True
            data = ''

            for i in self.data_stack:
                data += i
            self.data = data

    @staticmethod
    def from_string(data):

        if len(data) > MAX_LEN:
            out = MultiQRCode()
            out.data = data

            while len(data) > MAX_LEN:
                sequence = data[:MAX_LEN]
                data = data[MAX_LEN:]
                out.data_stack.append(sequence)
            if len(data):
                out.data_stack.append(data)

            out.total_sequences = len(out.data_stack)
            out.sequences_count = out.total_sequences
            out.is_completed = True
        else:
            out = QRCode()
            out.data = data
            out.data_init(1)

        return out

    def next(self) -> str:
        self.current += 1
        if self.current >= self.total_sequences:
            self.current = 0

        data = self.data_stack[self.current]

        digit_a = self.current + 1
        digit_b = self.total_sequences

        data = f"p{digit_a}of{digit_b} {data}"

        return data


class ReadQR(QThread):

    data = Signal(object)
    video_stream = Signal(object)

    def __init__(self, parent):
        QThread.__init__(self)
        self.parent = parent
        self.finished.connect(self.on_finnish)
        self.qr_data: QRCode | MultiQRCode = None
        self.capture = None

    def run(self):
        self.qr_data: QRCode | MultiQRCode = None
        # Initialize the camera
        self.capture = cv2.VideoCapture(0)

        end = False

        while not end:
            self.msleep(30)

            ret, frame = self.capture.read()

            if ret:
                # Convert the frame to RGB format
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Create a QImage from the frame data
                height, width, channel = frame.shape
                image = QImage(frame.data, width, height, QImage.Format_RGB888)

                # Create a QPixmap from the QImage
                pixmap = QPixmap.fromImage(image)

                # Scale the QPixmap to fit the label dimensions
                scaled_pixmap = pixmap.scaled(self.parent.ui.video_in.size(), Qt.KeepAspectRatio)

                # Set the pixmap to the label
                self.video_stream.emit(scaled_pixmap)

                data = pyzbar.decode(frame)
                if data:
                    try:
                        self.decode(to_str(data[0].data))
                    except Exception as e:
                        print(e)

            if self.qr_data:
                if self.qr_data.is_completed:
                    self.video_stream.emit(None)
                    self.data.emit(self.qr_data.data)
                    break

        return

    def decode(self, data):

        #  Multipart QR Code case
        if data[0] == 'p':

            if not self.qr_data:
                self.qr_data = MultiQRCode()

            # print('Multipart QR')

            #  sequence is 1 digit
            if data[2:4] == 'of':
                # print('if')
                digit_a = data[1]
                if data[5] == ' ':
                    digit_b = data[4]
                    data = data[6:]
                elif data[6] == ' ':
                    digit_b = data[4:6]
                else:
                    raise Exception('Cannot decode multipart QR Code')

            #  sequence is 2 digit
            elif data[3:5] == 'of':
                # print('elif')
                digit_a = data[1:3]
                if data[7] == ' ':
                    digit_b = data[5:7]
                    data = data[8:]
                else:
                    raise Exception('Cannot decode multipart QR Code')

            else:
                # print('else')
                raise Exception('Cannot decode multipart QR Code')

            self.qr_data.append((int(digit_a), int(digit_b), data))

            progress = round(self.qr_data.sequences_count / self.qr_data.total_sequences*100)
            self.parent.ui.read_progress.setValue(progress)
            self.parent.ui.read_progress.setFormat(f"{self.qr_data.sequences_count}/{self.qr_data.total_sequences}")
            self.parent.ui.read_progress.setVisible(True)

        else:
            self.qr_data = QRCode()
            self.qr_data.append(data)

    def on_finnish(self):
        self.capture.release()
        self.parent.ui.read_progress.setValue(0)
        self.parent.ui.read_progress.setVisible(False)
        self.parent.ui.read_progress.setFormat('')


class DisplayQR(QThread):

    video_stream = Signal(object)

    def __init__(self, parent):
        QThread.__init__(self)
        self.parent = parent
        self.qr_data: QRCode | MultiQRCode = None
        self.stop = False

    def run(self):
        self.stop = False
        if self.qr_data.total_sequences > 1:
            while not self.stop:
                data = self.qr_data.next()
                self.display_qr(data)
                self.msleep(QR_DELAY)

        elif self.qr_data.total_sequences == 1:
            data = self.qr_data.data
            self.display_qr(data)
            while not self.stop:
                self.msleep(QR_DELAY)

    def display_qr(self, data):
        img = qrcode.make(data)
        pil_image = img.convert("RGB")
        qimage = ImageQt.ImageQt(pil_image)
        qimage = qimage.convertToFormat(QImage.Format_RGB888)

        # Create a QPixmap from the QImage
        pixmap = QPixmap.fromImage(qimage)

        scaled_pixmap = pixmap.scaled(self.parent.ui.video_out.size(), Qt.KeepAspectRatio)
        self.video_stream.emit(scaled_pixmap)

    def on_stop(self):
        self.video_stream.emit(None)
        self.stop = True


class MainWindow(QMainWindow):
    stop_display = Signal()

    def __init__(self):
        QMainWindow.__init__(self)

        # Set up the main window
        loader = QUiLoader()
        path = os.fspath(Path(__file__).resolve().parent / "form.ui")
        ui_file = QFile(path)
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file, self)
        ui_file.close()
        self.setWindowTitle("SeedQReader")


        self.ui.show()

        self.ui.btn_start_read.clicked.connect(self.on_qr_read)
        self.ui.btn_generate.clicked.connect(self.on_btn_generate)

        self.ui.data_out.setWordWrapMode(QTextOption.WrapAnywhere)

        self.init_qr()

    def init_qr(self):

        self.read_qr = ReadQR(self)
        self.read_qr.video_stream.connect(self.upd_camera_stream)
        self.read_qr.data.connect(self.on_qr_data_read)

        self.display_qr = DisplayQR(self)
        self.display_qr.video_stream.connect(self.on_qr_display)
        self.stop_display.connect(self.display_qr.on_stop)

    def on_qr_display(self, frame):
        self.ui.video_out.setPixmap(frame)

    def on_qr_read(self):
        if not self.read_qr.isRunning():
            self.ui.data_in.setPlainText('')
            self.read_qr.start()
        else:
            print("read_qr already running!")

    def on_qr_data_read(self, data):
        self.ui.data_in.setWordWrapMode(QTextOption.WrapAnywhere)
        self.ui.data_in.setPlainText(data)

    def upd_camera_stream(self, frame):
        self.ui.video_in.setPixmap(frame)

    def on_btn_generate(self):
        if not self.display_qr.isRunning():
            data = self.ui.data_out.toPlainText()

            qr = MultiQRCode.from_string(data)
            self.display_qr.qr_data = qr
            self.display_qr.start()

            self.ui.btn_generate.setText('Stop')

        else:
            self.stop_display.emit()
            self.ui.btn_generate.setText('Generate')


if __name__ == '__main__':
    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    # Now use a palette to switch to dark colors:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.black)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    main_win = MainWindow()
    sys.exit(app.exec_())

