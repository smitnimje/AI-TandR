import sys
import time
import datetime
import speech_recognition as sr

# Global flag — brain thread checks this before listening
mic_muted = False

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QThread, pyqtSignal

import agent_backend
from robot_face import RobotFaceWidget


# ==========================================
# THREAD 1: BACKGROUND WATCHER
# ==========================================

class WatcherThread(QThread):

    database_updated_signal = pyqtSignal()
    face_state_signal       = pyqtSignal(str)

    def run(self):
        while True:
            try:
                triggered_tasks = agent_backend.check_and_trigger_tasks()
                for task_text in triggered_tasks:
                    global mic_muted
                    mic_muted = True   # mute brain mic while speaking
                    self.face_state_signal.emit("speaking")
                    agent_backend.speak(
                        f"Sir, a reminder has been triggered. "
                        f"The scheduled task is: {task_text}."
                    )
                    time.sleep(0.5)    # small gap after TTS ends
                    mic_muted = False  # re-enable mic
                    self.database_updated_signal.emit()
                    self.face_state_signal.emit("idle")
            except Exception:
                pass
            time.sleep(10)


# ==========================================
# THREAD 2: VOICE BRAIN
# ==========================================

class AgentBrainThread(QThread):

    status_update           = pyqtSignal(str)
    database_updated_signal = pyqtSignal()
    face_state_signal       = pyqtSignal(str)
    shutdown_signal         = pyqtSignal()

    WAKE_WORDS = [
        "hey listen", "listen", "hey assistant",
        "a listen", "hey listin", "listin",
        "are you listening", "hello listen",
        "hey", "okay listen", "ok listen",
    ]

    SHUTDOWN_WORDS = [
        "shutdown", "shut down", "goodbye", "good bye",
        "turn off", "exit", "close", "bye bye", "power off",
    ]

    def run(self):

        recognizer = sr.Recognizer()

        # ── Static threshold — no auto-raise drift ──────────────────
        recognizer.dynamic_energy_threshold = False

        # ── PAUSE SETTINGS ──────────────────────────────────────────
        #
        # pause_threshold for WAKE WORD:   0.6s  (short phrase, fast)
        # pause_threshold for COMMAND:     1.2s  (enough for Indian
        #   English mid-sentence pauses without a 2.5s wait after done)
        #
        # The trick: we use TWO different recognizer configs —
        # one tight for wake word, one relaxed for the command.
        # ────────────────────────────────────────────────────────────
        recognizer.pause_threshold       = 0.6   # wake word mode (fast)
        recognizer.non_speaking_duration = 0.4
        recognizer.phrase_threshold      = 0.2

        mic = sr.Microphone(sample_rate=16000, chunk_size=512)

        self.status_update.emit("⚙ Calibrating microphone (2 sec)…")
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=2)

        recognizer.energy_threshold = max(recognizer.energy_threshold * 1.1, 250)
        print(f"[MIC] Threshold locked: {recognizer.energy_threshold:.0f}")

        self.status_update.emit("🎙 Say 'Hey Listen'…")

        loop_count = 0

        while True:

            try:

                # Gentle recalibration every 60 idle loops
                loop_count += 1
                if loop_count >= 60:
                    loop_count = 0
                    with mic as source:
                        recognizer.adjust_for_ambient_noise(source, duration=1)
                    recognizer.energy_threshold = max(
                        recognizer.energy_threshold * 1.1, 250
                    )

                # Skip if watcher is speaking (avoids picking up TTS audio)
                global mic_muted
                if mic_muted:
                    time.sleep(0.2)
                    continue

                self.face_state_signal.emit("idle")

                # ── WAKE WORD ONLY mode ─────────────────────────────
                # Mic listens for a short burst. If nothing heard in
                # timeout, loop silently. Only send to Google if audio
                # was actually captured — and only act if wake word found.
                # Nothing is printed unless wake word is detected.
                recognizer.pause_threshold       = 0.6
                recognizer.non_speaking_duration = 0.4

                try:
                    with mic as source:
                        audio = recognizer.listen(
                            source,
                            timeout=3,
                            phrase_time_limit=4
                        )
                except sr.WaitTimeoutError:
                    continue  # silence — loop quietly, no print

                # Transcribe — but catch silently if not understood
                try:
                    text = recognizer.recognize_google(
                        audio, language="en-IN"
                    ).lower().strip()
                except sr.UnknownValueError:
                    continue  # not speech — loop silently, no print
                except sr.RequestError:
                    continue

                # Only wake word triggers anything — everything else ignored silently
                if not self._is_wake_word(text):
                    continue  # not wake word — discard, no print

                # ── Check if it is a shutdown command ──────────────
                if self._is_shutdown_word(text):
                    self.face_state_signal.emit("speaking")
                    self.status_update.emit("🔴 Shutting down…")
                    agent_backend.speak("Goodbye sir. Shutting down now.")
                    self.shutdown_signal.emit()
                    return

                # ── Wake word matched ───────────────────────────────
                self.face_state_signal.emit("listening")
                self.status_update.emit("✅ Listening… speak your command")

                # Beep = mic is now open and recording
                agent_backend.play_beep()

                # Do NOT call adjust_for_ambient_noise here —
                # it blocks the mic and causes the 15s stuck delay.
                # Threshold is already locked from startup calibration.
                #
                # pause_threshold=1.8s so Indian English mid-sentence
                # pauses don't cut the command in half.
                recognizer.pause_threshold       = 1.0
                recognizer.non_speaking_duration = 0.5

                with mic as source:
                    audio_cmd = recognizer.listen(
                        source,
                        timeout=6,
                        phrase_time_limit=30
                    )

                command = recognizer.recognize_google(
                    audio_cmd, language="en-IN"
                )

                print(f"[COMMAND] {command}")

                # ── Shutdown check on the actual command ───────────
                if self._is_shutdown_word(command.lower()):
                    self.face_state_signal.emit("speaking")
                    self.status_update.emit("🔴 Shutting down…")
                    agent_backend.speak("Goodbye sir. Shutting down now.")
                    self.shutdown_signal.emit()
                    return

                self.status_update.emit(f"📝 \"{command}\"\n⏳ Thinking…")
                self.face_state_signal.emit("thinking")

                result_type = agent_backend.process_voice_command(command)

                self.face_state_signal.emit("speaking")

                if result_type == "hidden":
                    agent_backend.speak(
                        "Done sir. I have set a background reminder for you. "
                        "It will alert you at the right time."
                    )
                elif result_type == "visible":
                    self.database_updated_signal.emit()
                    agent_backend.speak(
                        "Done sir. I have updated your plan and added it to the screen."
                    )
                elif result_type == "deleted":
                    self.database_updated_signal.emit()
                    agent_backend.speak(
                        "Done sir. The goal has been deleted from your plan."
                    )
                elif result_type == "edited":
                    self.database_updated_signal.emit()
                    agent_backend.speak(
                        "Done sir. The step has been updated."
                    )
                elif result_type == "step_deleted":
                    self.database_updated_signal.emit()
                    agent_backend.speak(
                        "Done sir. The step has been removed."
                    )
                else:
                    agent_backend.speak(
                        "Sorry sir, I ran into an issue processing that. "
                        "Please try again."
                    )

                self.face_state_signal.emit("idle")
                self.status_update.emit("🎙 Say 'Hey Listen'…")
                loop_count = 0

            except sr.WaitTimeoutError:
                continue

            except sr.UnknownValueError:
                continue

            except sr.RequestError as e:
                print(f"[SR API ERROR] {e}")
                self.status_update.emit("⚠ Speech API error. Retrying…")
                time.sleep(2)

            except Exception as e:
                print(f"[AUDIO ERROR] {e}")
                time.sleep(0.5)

    def _is_shutdown_word(self, text: str) -> bool:
        for phrase in self.SHUTDOWN_WORDS:
            if phrase in text:
                return True
        return False

    def _is_wake_word(self, text: str) -> bool:
        for phrase in self.WAKE_WORDS:
            if phrase in text:
                return True
        words = text.split()
        if len(words) <= 3:
            for w in words:
                if w.startswith("lis") or w.startswith("liss"):
                    return True
        return False


# ==========================================
# MAIN UI
# ==========================================

class AgentUI(QtWidgets.QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("AI Task Manager")
        self.resize(1100, 750)
        self.setStyleSheet("background-color: #121212; color: #FFFFFF;")

        self.show_all_goals = False

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        main_h_layout = QtWidgets.QHBoxLayout(central_widget)

        # ── Left panel ───────────────────────────────────────────────
        left_panel  = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        main_h_layout.addWidget(left_panel, stretch=2)

        self.face_widget = RobotFaceWidget()
        left_layout.addWidget(self.face_widget)

        self.status_label = QtWidgets.QLabel("Initializing…")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setFont(QtGui.QFont("Arial", 12, QtGui.QFont.Bold))
        self.status_label.setStyleSheet("color: #00FFCC; padding: 10px;")
        left_layout.addWidget(self.status_label)

        self.view_toggle_btn = QtWidgets.QPushButton("SHOW ALL TASKS")
        self.view_toggle_btn.setFont(QtGui.QFont("Arial", 10, QtGui.QFont.Bold))
        self.view_toggle_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.view_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E1E1E; color: #00FFCC;
                border: 1px solid #00FFCC; border-radius: 5px;
                padding: 8px; margin-bottom: 5px;
            }
            QPushButton:hover { background-color: #00FFCC; color: #121212; }
        """)
        self.view_toggle_btn.clicked.connect(self.toggle_view)
        left_layout.addWidget(self.view_toggle_btn)

        self.task_list = QtWidgets.QListWidget()
        self.task_list.setFont(QtGui.QFont("Arial", 11))
        self.task_list.setStyleSheet("""
            QListWidget {
                background-color: #1E1E1E; border-radius: 10px;
                padding: 10px; outline: 0;
            }
            QListWidget::item { margin-bottom: 5px; }
            QListWidget::item:checked { text-decoration: line-through; color: #555555; }
        """)
        left_layout.addWidget(self.task_list)

        # ── Right panel ──────────────────────────────────────────────
        right_panel  = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setAlignment(QtCore.Qt.AlignTop)
        main_h_layout.addWidget(right_panel, stretch=1)

        guide_label = QtWidgets.QLabel("🤖 COMMAND GUIDE")
        guide_label.setFont(QtGui.QFont("Arial", 16, QtGui.QFont.Bold))
        guide_label.setStyleSheet("color: #00FFCC;")
        right_layout.addWidget(guide_label)

        guide_text = QtWidgets.QTextBrowser()
        guide_text.setStyleSheet("""
            QTextBrowser {
                background-color: #1A1A1A; color: #DDDDDD;
                border-radius: 10px; padding: 15px;
                border: 1px solid #333333;
            }
        """)
        guide_text.setFont(QtGui.QFont("Arial", 12))
        guide_text.setHtml("""
        <p><b style="color:white; font-size:14px;">⚡ Activation:</b><br>
        Say <span style="color:#00FFCC;">"Hey Listen"</span> or <span style="color:#00FFCC;">"Listen"</span>
        → beep sounds → speak your command → pause 1.5s to submit.</p>

        <p><b style="color:white; font-size:14px;">1. 🎯 New Goal (multi-step):</b><br>
        <i>"Plan a workout routine for today."</i><br>
        <i>"I need to study for my science exam."</i><br>
        <i>"Create a morning routine plan."</i></p>

        <p><b style="color:white; font-size:14px;">2. 🔔 Hidden Reminder:</b><br>
        <i>"Remind me in 2 hours to call my boss."</i><br>
        <i>"Set a reminder at 6 PM to check the oven."</i></p>

        <p><b style="color:white; font-size:14px;">3. ✏️ Rename a Step:</b><br>
        <i>"Rename step 1 of goal 2 to drink water."</i><br>
        <i>"Change step 2 of goal 1 to review notes."</i></p>

        <p><b style="color:white; font-size:14px;">4. ⏩ Delay / Push Forward:</b><br>
        <i>"Delay step 1 of goal 1 by 30 minutes."</i><br>
        <i>"Push step 2 of goal 2 forward by 1 hour."</i><br>
        <i>"Move step 3 of goal 1 to 5 PM."</i></p>

        <p><b style="color:white; font-size:14px;">5. ⏪ Move Backward / Earlier:</b><br>
        <i>"Move step 1 of goal 1 back by 20 minutes."</i><br>
        <i>"Shift step 2 of goal 2 earlier by 45 minutes."</i><br>
        <i>"Reschedule step 1 of goal 1 to 2 PM."</i></p>

        <p><b style="color:white; font-size:14px;">6. 🗑️ Delete:</b><br>
        <i>"Delete goal 1."</i><br>
        <i>"Remove goal 2."</i><br>
        <i>"Clear all goals."</i></p>
        """)
        right_layout.addWidget(guide_text)

        # ── Init ─────────────────────────────────────────────────────
        agent_backend.init_db()
        self.refresh_ui_list()

        self.watcher_thread = WatcherThread()
        self.watcher_thread.database_updated_signal.connect(self.refresh_ui_list)
        self.watcher_thread.face_state_signal.connect(self.face_widget.set_state)
        self.watcher_thread.start()

        self.brain_thread = AgentBrainThread()
        self.brain_thread.status_update.connect(self.status_label.setText)
        self.brain_thread.database_updated_signal.connect(self.refresh_ui_list)
        self.brain_thread.face_state_signal.connect(self.face_widget.set_state)
        self.brain_thread.shutdown_signal.connect(self.close)
        self.brain_thread.start()

    def toggle_view(self):
        self.show_all_goals = not self.show_all_goals
        self.view_toggle_btn.setText(
            "SHOW LATEST GOAL" if self.show_all_goals else "SHOW ALL TASKS"
        )
        self.refresh_ui_list()

    def refresh_ui_list(self):
        self.task_list.clear()
        db = agent_backend.load_tasks(agent_backend.DB_FILE)

        if not db:
            self.task_list.addItem("No visible tasks currently scheduled.")
            return

        display_list = db if self.show_all_goals else db[-1:]

        for goal in display_list:

            header = QtWidgets.QListWidgetItem(
                f"🎯 GOAL {goal['goal_id']}: {goal['goal_name'].upper()}"
            )
            header.setFont(QtGui.QFont("Arial", 12, QtGui.QFont.Bold))
            header.setForeground(QtGui.QBrush(QtGui.QColor("#00FFCC")))
            header.setFlags(QtCore.Qt.NoItemFlags)
            self.task_list.addItem(header)

            for i, step in enumerate(goal.get("steps", []), 1):
                try:
                    time_obj = datetime.datetime.fromisoformat(step["trigger_time"])
                    time_str = time_obj.strftime("%I:%M %p")
                except Exception as te:
                    print(f"[TIME PARSE ERROR] {step.get('trigger_time')} -> {te}")
                    time_str = "?:??"

                item = QtWidgets.QListWidgetItem(
                    f" Step {i}: [{time_str}] {step['task']}"
                )
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(
                    QtCore.Qt.Checked if step.get("completed", False)
                    else QtCore.Qt.Unchecked
                )
                self.task_list.addItem(item)

            self.task_list.addItem(QtWidgets.QListWidgetItem(""))


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AgentUI()
    window.show()
    sys.exit(app.exec_())