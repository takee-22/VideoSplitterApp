import os
import sys
import cv2
import subprocess
import imageio_ffmpeg

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QMessageBox,
    QLineEdit,
    QGroupBox,
    QGridLayout,
)


def format_seconds(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))

    if ms == 1000:
        secs += 1
        ms = 0
    if secs == 60:
        minutes += 1
        secs = 0
    if minutes == 60:
        hours += 1
        minutes = 0

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def safe_basename(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


class VideoSplitterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional Video Splitter v1.1")
        self.resize(1000, 700)

        self.video_path = ""
        self.output_dir = ""
        self.cut_time_sec = 0.0

        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

        self.fps = 25.0
        self.frame_count = 0
        self.duration_sec = 0.0
        self.current_frame_index = 0
        self.is_playing = False
        self.slider_dragging = False

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Video display
        self.video_label = QLabel("Open a video to start")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumHeight(450)
        self.video_label.setStyleSheet("border: 1px solid gray; background: black; color: white;")
        main_layout.addWidget(self.video_label)

        # Slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.slider.valueChanged.connect(self.on_slider_changed)
        main_layout.addWidget(self.slider)

        # Time label
        self.time_label = QLabel("00:00:00.000 / 00:00:00.000")
        main_layout.addWidget(self.time_label)

        # Controls
        control_layout = QHBoxLayout()

        self.open_btn = QPushButton("Open Video")
        self.open_btn.clicked.connect(self.open_video)
        control_layout.addWidget(self.open_btn)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_video)
        control_layout.addWidget(self.pause_btn)

        self.set_cut_btn = QPushButton("Set Cut at Current Position")
        self.set_cut_btn.clicked.connect(self.set_cut_at_current_position)
        control_layout.addWidget(self.set_cut_btn)

        main_layout.addLayout(control_layout)

        # Split settings
        group = QGroupBox("Split Settings")
        grid = QGridLayout()

        grid.addWidget(QLabel("Selected Cut Time:"), 0, 0)
        self.cut_time_edit = QLineEdit("00:00:00.000")
        grid.addWidget(self.cut_time_edit, 0, 1)

        use_box_btn = QPushButton("Use This Time")
        use_box_btn.clicked.connect(self.use_time_from_box)
        grid.addWidget(use_box_btn, 0, 2)

        grid.addWidget(QLabel("Output Folder:"), 1, 0)
        self.output_dir_edit = QLineEdit()
        grid.addWidget(self.output_dir_edit, 1, 1)

        browse_output_btn = QPushButton("Browse")
        browse_output_btn.clicked.connect(self.select_output_dir)
        grid.addWidget(browse_output_btn, 1, 2)

        self.split_btn = QPushButton("Split Video Into 2 Parts")
        self.split_btn.setToolTip("Click to split the video at the selected time into two separate files.")
        self.split_btn.clicked.connect(self.split_video)
        grid.addWidget(self.split_btn, 2, 0, 1, 3)

        group.setLayout(grid)
        main_layout.addWidget(group)

        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        self.setLayout(main_layout)

    def open_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.m4v *.ts);;All Files (*)"
        )
        if not file_path:
            return

        self.close_video()

        self.video_path = file_path
        self.cap = cv2.VideoCapture(self.video_path)

        if not self.cap.isOpened():
            QMessageBox.critical(self, "Error", "Could not open video.")
            self.cap = None
            return

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if not self.fps or self.fps <= 0:
            self.fps = 25.0

        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_sec = self.frame_count / self.fps if self.fps > 0 else 0.0
        self.current_frame_index = 0
        self.cut_time_sec = 0.0

        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, self.frame_count - 1))
        self.slider.setValue(0)

        default_output_dir = os.path.dirname(self.video_path)
        self.output_dir = default_output_dir
        self.output_dir_edit.setText(default_output_dir)

        self.cut_time_edit.setText(format_seconds(0.0))
        self.update_time_label(0.0)
        self.show_frame(0)

        self.status_label.setText(f"Loaded: {self.video_path}")

    def close_video(self):
        self.pause_video()
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def toggle_play(self):
        if self.cap is None:
            return

        if self.is_playing:
            self.pause_video()
        else:
            interval = max(1, int(1000 / self.fps))
            self.timer.start(interval)
            self.is_playing = True
            self.play_btn.setText("Playing...")

    def pause_video(self):
        self.timer.stop()
        self.is_playing = False
        self.play_btn.setText("Play")

    def next_frame(self):
        if self.cap is None:
            return

        next_index = self.current_frame_index + 1
        if next_index >= self.frame_count:
            self.pause_video()
            return

        self.show_frame(next_index)

    def show_frame(self, frame_index: int):
        if self.cap is None:
            return

        frame_index = max(0, min(frame_index, max(0, self.frame_count - 1)))

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = self.cap.read()
        if not ret:
            return

        self.current_frame_index = frame_index
        current_sec = self.current_frame_index / self.fps if self.fps > 0 else 0.0

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)

        scaled = pixmap.scaled(
            self.video_label.width(),
            self.video_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.video_label.setPixmap(scaled)

        if not self.slider_dragging:
            self.slider.blockSignals(True)
            self.slider.setValue(frame_index)
            self.slider.blockSignals(False)

        self.update_time_label(current_sec)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.cap is not None:
            self.show_frame(self.current_frame_index)

    def update_time_label(self, current_sec: float):
        self.time_label.setText(f"{format_seconds(current_sec)} / {format_seconds(self.duration_sec)}")

    def on_slider_pressed(self):
        self.slider_dragging = True

    def on_slider_released(self):
        self.slider_dragging = False
        self.show_frame(self.slider.value())

    def on_slider_changed(self, value):
        if self.cap is None:
            return

        if self.slider_dragging:
            preview_sec = value / self.fps if self.fps > 0 else 0.0
            self.update_time_label(preview_sec)

    def set_cut_at_current_position(self):
        if self.cap is None:
            QMessageBox.warning(self, "Warning", "Open a video first.")
            return

        self.cut_time_sec = self.current_frame_index / self.fps if self.fps > 0 else 0.0
        self.cut_time_edit.setText(format_seconds(self.cut_time_sec))
        self.status_label.setText(f"Cut point set to {format_seconds(self.cut_time_sec)}")

    def use_time_from_box(self):
        if self.cap is None:
            QMessageBox.warning(self, "Warning", "Open a video first.")
            return

        text = self.cut_time_edit.text().strip()
        try:
            self.cut_time_sec = self.parse_time_to_seconds(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid Time", "Use format HH:MM:SS or HH:MM:SS.mmm")
            return

        if self.cut_time_sec <= 0 or self.cut_time_sec >= self.duration_sec:
            QMessageBox.warning(self, "Invalid Time", "Cut time must be inside the video duration.")
            return

        target_frame = int(self.cut_time_sec * self.fps)
        self.show_frame(target_frame)
        self.status_label.setText(f"Cut point set to {format_seconds(self.cut_time_sec)}")

    def parse_time_to_seconds(self, text: str) -> float:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("Invalid time format")

        hours = int(parts[0])
        minutes = int(parts[1])

        if "." in parts[2]:
            sec_part, ms_part = parts[2].split(".", 1)
            seconds = int(sec_part)
            ms = int(ms_part.ljust(3, "0")[:3])
        else:
            seconds = int(parts[2])
            ms = 0

        total = hours * 3600 + minutes * 60 + seconds + ms / 1000.0
        return total

    def select_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_dir = folder
            self.output_dir_edit.setText(folder)

    def split_video(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Open a video first.")
            return

        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Warning", "Select an output folder.")
            return

        if not os.path.isdir(output_dir):
            QMessageBox.warning(self, "Warning", "Output folder does not exist.")
            return

        try:
            cut_time = self.parse_time_to_seconds(self.cut_time_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Time", "Use format HH:MM:SS or HH:MM:SS.mmm")
            return

        if cut_time <= 0 or cut_time >= self.duration_sec:
            QMessageBox.warning(self, "Invalid Time", "Cut time must be inside the video duration.")
            return

        self.pause_video()

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        base = safe_basename(self.video_path)
        ext = os.path.splitext(self.video_path)[1]
        part1_path = os.path.join(output_dir, f"{base}_part1{ext}")
        part2_path = os.path.join(output_dir, f"{base}_part2{ext}")

        cut_time_str = format_seconds(cut_time)

        # Part 1: from start to cut point
        cmd1 = [
            ffmpeg_exe,
            "-y",
            "-i", self.video_path,
            "-to", cut_time_str,
            "-c", "copy",
            part1_path,
        ]

        # Part 2: from cut point to end
        cmd2 = [
            ffmpeg_exe,
            "-y",
            "-ss", cut_time_str,
            "-i", self.video_path,
            "-c", "copy",
            part2_path,
        ]

        self.status_label.setText("Splitting... Please wait.")
        QApplication.processEvents()

        try:
            result1 = subprocess.run(cmd1, capture_output=True, text=True)
            if result1.returncode != 0:
                raise RuntimeError(result1.stderr.strip() or "Failed to create part 1.")

            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0:
                raise RuntimeError(result2.stderr.strip() or "Failed to create part 2.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Split failed:\n\n{str(e)}")
            self.status_label.setText("Split failed.")
            return

        self.status_label.setText("Done.")
        QMessageBox.information(
            self,
            "Success",
            f"Video split completed.\n\nPart 1:\n{part1_path}\n\nPart 2:\n{part2_path}"
        )

    def closeEvent(self, event):
        self.close_video()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoSplitterApp()
    window.show()
    sys.exit(app.exec_())