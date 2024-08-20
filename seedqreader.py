import sys
import os
import re

from dataclasses import dataclass, field

from pathlib import Path

from yaml import load, dump
from yaml.loader import SafeLoader as Loader

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtGui import QImage, QPixmap, QPalette, QColor, QColorConstants
from PySide6.QtCore import Qt, QFile, QThread, Signal
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QTextOption

from PIL import ImageQt

from pyzbar import pyzbar

import qrcode

import cv2

import qr_type

from foundation.ur_decoder import URDecoder
from foundation.ur_encoder import UREncoder
from foundation.ur import UR

from urtypes.crypto import PSBT as UR_PSBT
from urtypes.crypto import Account, Output
from urtypes.bytes import Bytes

from embit.psbt import PSBT

MAX_LEN = 100
FILL_COLOR = "#434343"

STOP_QR_TXT = 'Remove QR'
STOP_READ_TXT = 'Stop read'
GENERATE_TXT = 'Generate QR'


def to_str(bin_):
    return bin_.decode('utf-8')


@dataclass
class QRCode:
    data: str = ''
    total_sequences: int = 0
    sequences_count: int = 0
    is_completed: bool = False
    qr_type = None

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
    total_sequences = None
    qr_type = None
    data_type = None
    decoder = None
    encoder = None

    def step(self):
        if self.qr_type == qr_type.SPECTER:
            self.total_sequences = len(self.data_stack)

            return f"{self.current + 1}/{self.total_sequences}"

        elif self.qr_type == qr_type.UR:
            return f"{self.current + 1}/{self.total_sequences}"

    def append(self, data: tuple):
        if self.qr_type == qr_type.SPECTER:
            self.append_specter(data)

        elif self.qr_type == qr_type.UR:
            self.append_ur(data)

    def append_specter(self, data: tuple):
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
                print(f"{data} != {self.data_stack[sequence-1]}")
                raise ValueError('Same sequences have different data!')
        self.check_complete_specter()

    def append_ur(self, data: tuple):
        if not self.decoder:
            self.decoder = URDecoder()

        self.decoder.receive_part(data)

        self.check_complete_ur()

    def data_init(self, sequences: int):
        super().data_init(sequences)
        self.data_stack = [None] * sequences

    def check_complete_specter(self):
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

    def check_complete_ur(self):
        if self.decoder.is_complete():
            if self.decoder.is_success():
                self.is_completed = True
                cbor = self.decoder.result_message().cbor
                _type = self.decoder.result_message().type
                #  XPub
                if _type == 'crypto-account':
                    self.data = Account.from_cbor(cbor).output_descriptors[0].descriptor()
                #  PSBT
                elif _type == 'crypto-psbt':
                    self.data = UR_PSBT.from_cbor(cbor).data
                    if type(self.data) is bytes:
                        self.data = PSBT.parse(self.data).to_string()

                #  Descriptor
                elif _type == 'crypto-output':
                    self.data = Output.from_cbor(cbor).descriptor()
                #  bytes
                elif _type == 'bytes':
                    print('bytes')
                    self.data = Bytes.from_cbor(cbor).data.decode('utf-8')

                else:
                    print(f"Type not yet implemented: {type}")
                    return

                print(f"{_type}:{self.data}")

            else:
                print("fail to complete UR parsing: ", end='')
                print(self.decoder.result_error())

    @staticmethod
    def from_string(data, max=MAX_LEN, type=None, format=None):
        if (max and len(data) > max) or format == 'UR':
            out = MultiQRCode()
            out.data = data
            if format == 'UR':
                out.qr_type = qr_type.UR
            elif format == 'Specter':
                out.qr_type = qr_type.SPECTER

            if format == 'Specter':
                while len(data) > max:
                    sequence = data[:max]
                    data = data[max:]
                    out.data_stack.append(sequence)
                if len(data):
                    out.data_stack.append(data)

                out.total_sequences = len(out.data_stack)
                out.sequences_count = out.total_sequences
                out.is_completed = True

            elif format == 'UR':
                _UR = None
                if type == 'PSBT':
                    out.data_type = 'crypto-psbt'
                    data = PSBT.from_string(data).serialize()
                    _UR = UR_PSBT
                elif type == 'Descriptor':
                    out.data_type = 'bytes'
                    _UR = Bytes
                elif type == 'Key':
                    print("key")
                    out.data_type = 'bytes'
                    _UR = Bytes
                elif type == 'Bytes':
                    out.data_type = 'bytes'
                    _UR = Bytes
                else:
                    return
                if not max:
                    max = 100000
                ur = UR(out.data_type, _UR(data).to_cbor())
                out.encoder = UREncoder(ur, max)
                out.total_sequences = out.encoder.fountain_encoder.seq_len()
        else:
            out = QRCode()
            out.data = data
            out.data_init(1)

        return out

    def next(self) -> str:
        if self.qr_type == qr_type.SPECTER:
            self.current += 1
            if self.current >= self.total_sequences:
                self.current = 0

            data = self.data_stack[self.current]

            digit_a = self.current + 1
            digit_b = self.total_sequences

            data = f"p{digit_a}of{digit_b} {data}"
            print(data)

            return data

        elif self.qr_type == qr_type.UR:
            self.current = self.encoder.fountain_encoder.seq_num
            data = self.encoder.next_part().upper()
            print(data)
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
        self.end = False

    def run(self):
        self.qr_data: QRCode | MultiQRCode = None
        # Initialize the camera
        camera_id = self.parent.get_camera_id()

        if camera_id is None:
            return
        self.capture = cv2.VideoCapture(camera_id)

        self.parent.ui.btn_start_read.setText(STOP_READ_TXT)
        while not self.end:
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
                    if self.qr_data.qr_type is None:
                        print(f"QRCode:{self.qr_data.data}")
                    break
        if self.end:
            self.video_stream.emit(None)
        return

    def decode(self, data):
        '''Multipart QR Code case'''

        # specter format
        if re.match(r'^p\d+of\d+\s', data, re.IGNORECASE):

            if not self.qr_data:
                self.qr_data = MultiQRCode()
                self.qr_data.qr_type = qr_type.SPECTER

            header = data.split(' ')[0][1:].split('of')
            data = ' '.join(data.split(' ')[1:])

            digit_a = header[0]
            digit_b = header[1]

            self.qr_data.append((int(digit_a), int(digit_b), data))

            progress = round(self.qr_data.sequences_count / self.qr_data.total_sequences * 100)
            self.parent.ui.read_progress.setValue(progress)
            self.parent.ui.read_progress.setFormat(f"{self.qr_data.sequences_count}/{self.qr_data.total_sequences}")
            self.parent.ui.read_progress.setVisible(True)
        
        # UR format
        elif re.match(r'^UR:', data, re.IGNORECASE):

            if not self.qr_data:
                self.qr_data = MultiQRCode()
                self.qr_data.qr_type = qr_type.UR

            self.qr_data.append(data)

            progress = self.qr_data.decoder.estimated_percent_complete() * 100
            try:
                self.qr_data.total_sequences = self.qr_data.decoder.expected_part_count()
            except:
                self.qr_data.total_sequences = 0
            self.qr_data.sequences_count = self.qr_data.decoder.processed_parts_count()
            self.parent.ui.read_progress.setValue(progress)
            self.parent.ui.read_progress.setFormat(f"{self.qr_data.sequences_count}/{self.qr_data.total_sequences}")
            self.parent.ui.read_progress.setVisible(True)

        # Other format
        else:
            self.qr_data = QRCode()
            self.qr_data.append(data)

    def on_finnish(self):
        if self.capture:
            self.capture.release()
        self.parent.ui.read_progress.setValue(0)
        self.parent.ui.read_progress.setVisible(False)
        self.parent.ui.read_progress.setFormat('')
        self.parent.ui.btn_start_read.setText('Start read')


class DisplayQR(QThread):
    video_stream = Signal(object)

    def __init__(self, parent, delay):
        QThread.__init__(self)
        self.parent = parent
        self.set_delay(delay)
        self.qr_data: QRCode | MultiQRCode = None
        self.stop = True

    def set_delay(self, delay):
        self.delay = delay

    def run(self):
        self.stop = False
        if self.qr_data.total_sequences > 1 or self.qr_data.qr_type == qr_type.UR:
            remove_qr = True
            while not self.stop:
                data = self.qr_data.next()
                self.display_qr(data)
                self.parent.ui.steps.setText(self.qr_data.step())
                if self.qr_data.total_sequences == 1:
                    remove_qr = False
                    break
                self.msleep(self.delay)
            if remove_qr:
                self.video_stream.emit(None)
        elif self.qr_data.total_sequences == 1:
            data = self.qr_data.data
            self.display_qr(data)
            self.parent.ui.steps.setText('')

    def display_qr(self, data):
        qr = qrcode.QRCode()
        qr.add_data(data)
        qr.make(fit=False)
        img = qr.make_image()
        pil_image = img.convert("RGB")
        qimage = ImageQt.ImageQt(pil_image)
        qimage = qimage.convertToFormat(QImage.Format_RGB888)

        # Create a QPixmap from the QImage
        pixmap = QPixmap.fromImage(qimage)

        scaled_pixmap = pixmap.scaled(self.parent.ui.video_out.size(), Qt.KeepAspectRatio)
        self.video_stream.emit(scaled_pixmap)


class MainWindow(QMainWindow):
    def __init__(self, loader):
        super().__init__()

        # Set up the main window
        path = os.fspath(Path(__file__).resolve().parent / "form.ui")
        ui_file = QFile(path)
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file, self)
        ui_file.close()
        self.setWindowTitle("SeedQReader")
        self.setFixedSize(812,670)

        self.setCentralWidget(self.ui)

        self.load_config()

        self.ui.btn_start_read.clicked.connect(self.on_qr_read)
        self.ui.btn_generate.clicked.connect(self.on_btn_generate)
        self.ui.btn_clear.clicked.connect(self.on_btn_clear)
        self.ui.send_slider.valueChanged.connect(self.on_slider_move)
        self.ui.delay_slider.valueChanged.connect(self.on_delay_slider_move)

        self.ui.data_out.setWordWrapMode(QTextOption.WrapAnywhere)

        #  init radio button

        self.ui.desc_1.toggled.connect(self.on_radio_toggled)
        self.ui.desc_2.toggled.connect(self.on_radio_toggled)
        self.ui.desc_3.toggled.connect(self.on_radio_toggled)

        self.ui.psbt_1.toggled.connect(self.on_radio_toggled)
        self.ui.psbt_2.toggled.connect(self.on_radio_toggled)
        self.ui.psbt_3.toggled.connect(self.on_radio_toggled)
        self.ui.psbt_4.toggled.connect(self.on_radio_toggled)
        self.ui.psbt_5.toggled.connect(self.on_radio_toggled)

        self.ui.key_1.toggled.connect(self.on_radio_toggled)
        self.ui.key_2.toggled.connect(self.on_radio_toggled)
        self.ui.key_3.toggled.connect(self.on_radio_toggled)
        self.ui.key_4.toggled.connect(self.on_radio_toggled)
        self.ui.key_5.toggled.connect(self.on_radio_toggled)

        self.ui.desc_1.setChecked(True)
        self.radio_selected = 'desc_1'
        self.on_radio_toggled()

        self.ui.btn_save.clicked.connect(self.on_btn_save)

        self.ui.combo_format.addItems(['Specter', 'UR'])
        self.format = self.ui.combo_format.currentText()
        self.ui.combo_format.currentIndexChanged.connect(self.on_format_change)
        self.ui.combo_type.currentIndexChanged.connect(self.on_data_type_change)

        self.ui.combo_type.addItems(['Descriptor', 'PSBT', 'Key', 'Bytes'])
        self.ui.combo_type.hide()
        self.data_type = None

        self.ui.btn_camera_update.clicked.connect(self.on_camera_update)

        self.on_slider_move()
        self.on_delay_slider_move()
        self.on_camera_update()

        self.init_qr()

    def init_qr(self):
        self.read_qr = ReadQR(self)
        self.read_qr.video_stream.connect(self.upd_camera_stream)
        self.read_qr.data.connect(self.on_qr_data_read)

        self.display_qr = DisplayQR(self, self.ui.delay_slider.value())
        self.display_qr.video_stream.connect(self.on_qr_display)

    def load_config(self):
        if not os.path.exists('config'):
            f = open('config', 'w')
            f.close()

        with open('config', 'r') as f:
            data = load(f, Loader=Loader)

        if not data:
            data = {}

        self.config = data

    def dump_config(self):
        with open('config', 'w') as f:
            dump(self.config, f)

    @staticmethod
    def list_available_cameras():
        index = 0
        available_cameras = []
        while True:
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                available_cameras.append(str(index))
                cap.release()
                index += 1
            else:
                if index > 20 and not available_cameras:
                    break
                elif available_cameras and (index - int(available_cameras[-1])) > 2:
                    break
                else:
                    index += 1
                    continue

        return available_cameras

    def get_camera_id(self) -> int | None:
        try:
            id = self.ui.combo_camera.currentText()
            return int(id)
        except :
            return None

    def on_camera_update(self):
        last = self.get_camera_id()

        cameras = self.list_available_cameras()
        self.ui.combo_camera.clear()
        self.ui.combo_camera.addItems(cameras)
        if last and str(last) in cameras:
            self.ui.combo_type.setCurrentText(str(last))

    def on_format_change(self):
        self.format = self.ui.combo_format.currentText()

        if self.format != 'Specter':
            self.ui.combo_type.show()
            self.on_data_type_change()

        else:
            self.ui.combo_type.hide()
            self.data_type = None

    def on_data_type_change(self):
        if self.format == 'UR':
            self.data_type = self.ui.combo_type.currentText()

    def on_qr_display(self, frame):
        if frame is None:
            frame = QPixmap(self.ui.video_in.size())
            frame.fill(QColor(FILL_COLOR))
        
        self.ui.video_out.setPixmap(frame)

    def on_qr_read(self):
        if not self.read_qr.isRunning():
            self.read_qr.end = False
            self.ui.data_in.setPlainText('')
            self.read_qr.start()
        else:
            self.read_qr.end = True

    def on_qr_data_read(self, data):
        self.ui.data_in.setWordWrapMode(QTextOption.WrapAnywhere)
        self.ui.data_in.setPlainText(data)

    def upd_camera_stream(self, frame):
        if frame is None:
            frame = QPixmap(self.ui.video_in.size())
            frame.fill(QColor(FILL_COLOR))
        
        self.ui.video_in.setPixmap(frame)

    def on_slider_move(self):
        self.ui.split_size.setText(f"QR split size: {self.ui.send_slider.value()}")

    def on_delay_slider_move(self):
        self.ui.delay_size.setText(f"QR delay: {self.ui.delay_slider.value()}")
        try:
            self.display_qr.set_delay(self.ui.delay_slider.value())
        except:
            pass

    def on_btn_generate(self):
        data: str = self.ui.data_out.toPlainText()
        data.replace(' ', '').replace('\n', '')

        if not self.display_qr.isRunning() and self.display_qr.stop and data != '':
            _max = None if self.ui.no_split.isChecked() else self.ui.send_slider.value()

            try:
                qr = MultiQRCode.from_string(data, max=_max, type=self.data_type, format=self.format)
            except:
                print("error creating MultiQRCode", self.format)
                return
            
            if not qr:
                print("error creating MultiQRCode")
                return
            
            self.display_qr.qr_data = qr
            self.display_qr.start()

            self.ui.btn_generate.setText(STOP_QR_TXT)
        else:
            self.display_qr.stop = True
            self.ui.steps.setText('')
            self.display_qr.video_stream.emit(None)

            self.ui.btn_generate.setText(GENERATE_TXT)

    def on_btn_clear(self):
        self.ui.data_out.setPlainText('')

    def select_data_type(self, data_type):
        self.data_type = data_type
        self.ui.combo_type.setCurrentText(data_type)

    def radio_select(self):
        if self.ui.desc_1.isChecked():
            self.radio_selected = 'desc_1'
            self.select_data_type('Descriptor')

        elif self.ui.desc_2.isChecked():
            self.radio_selected = 'desc_2'
            self.select_data_type('Descriptor')

        elif self.ui.desc_3.isChecked():
            self.radio_selected = 'desc_3'
            self.select_data_type('Descriptor')

        elif self.ui.psbt_1.isChecked():
            self.radio_selected = 'psbt_1'
            self.select_data_type('PSBT')

        elif self.ui.psbt_2.isChecked():
            self.radio_selected = 'psbt_2'
            self.select_data_type('PSBT')

        elif self.ui.psbt_3.isChecked():
            self.radio_selected = 'psbt_3'
            self.select_data_type('PSBT')

        elif self.ui.psbt_4.isChecked():
            self.radio_selected = 'psbt_4'
            self.select_data_type('PSBT')

        elif self.ui.psbt_5.isChecked():
            self.radio_selected = 'psbt_5'
            self.select_data_type('PSBT')

        elif self.ui.key_1.isChecked():
            self.radio_selected = 'key_1'
            self.select_data_type('Key')

        elif self.ui.key_2.isChecked():
            self.radio_selected = 'key_2'
            self.select_data_type('Key')

        elif self.ui.key_3.isChecked():
            self.radio_selected = 'key_3'
            self.select_data_type('Key')

        elif self.ui.key_4.isChecked():
            self.radio_selected = 'key_4'
            self.select_data_type('Key')

        elif self.ui.key_5.isChecked():
            self.radio_selected = 'key_5'
            self.select_data_type('Key')

        else:
            return

    def on_radio_toggled(self):
        self.radio_select()
        self.load_config()

        if self.radio_selected in self.config.keys():
            self.ui.data_out.setPlainText(self.config[self.radio_selected])
        else:
            self.ui.data_out.setPlainText('')

    def on_btn_save(self):
        self.load_config()
        self.config[self.radio_selected] = self.ui.data_out.toPlainText()
        self.dump_config()


if __name__ == '__main__':
    # the QUiLoader object needs to be initialized BEFORE the QApplication - https://stackoverflow.com/a/78041695
    loader = QUiLoader()
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
    palette.setColor(QPalette.PlaceholderText, Qt.gray)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.Button, QColorConstants.DarkGray)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ButtonText, QColorConstants.Black)
    app.setPalette(palette)

    main_win = MainWindow(loader)
    main_win.show()
    app.exec()

