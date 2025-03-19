import subprocess
import keyboard
import time
import os

class Watchdog:
    def __init__(self, script_name="main.py"):
        """
        Initialize the watchdog with the script to run.
        """
        self.script_name = script_name
        self.process = None
        self.running = True  # Flag to control the watchdog loop
        self.start_process()

    def start_process(self):
        """
        Start the monitored process in the background.
        On Windows, the process is started with no console window.
        """
        print(f"Starting process {self.script_name}...")
        if os.name == "nt":
            # Hide the console window in Windows
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(
                ["python", self.script_name],
                creationflags=creation_flags
            )
        else:
            self.process = subprocess.Popen(["python3", self.script_name])
        print(f"Process {self.script_name} started with PID: {self.process.pid}")

    def restart_process(self):
        """
        Terminate the current process (if running) and start a new one.
        """
        if self.process and self.process.poll() is None:
            print("Terminating current process...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("Process did not terminate in time. Killing it...")
                self.process.kill()
        print("Restarting process...")
        self.start_process()

    def stop_watchdog(self):
        """
        Completely terminate the monitored process and exit the watchdog.
        """
        print("Hotkey Ctrl+Shift+Q pressed. Terminating watchdog and process...")
        self.running = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        keyboard.unhook_all_hotkeys()  # Remove all hotkeys before exiting
        print("Watchdog stopped.")

    def hotkey_restart(self):
        """
        Callback function triggered by Ctrl+Shift+Backspace to restart the process.
        """
        print("Hotkey Ctrl+Shift+Backspace pressed. Restarting process...")
        self.restart_process()

    def run(self):
        """
        Register the hotkeys and start monitoring the process.
        """
        keyboard.add_hotkey("ctrl+shift+backspace", self.hotkey_restart)
        keyboard.add_hotkey("ctrl+shift+k", self.stop_watchdog)  # New hotkey to stop everything
        print("Watchdog is running. Press Ctrl+Shift+Backspace to restart the process.")
        print("Press Ctrl+Shift+Q to stop the watchdog completely.")

        try:
            while self.running:
                # If the process has terminated unexpectedly, restart it.
                if self.process.poll() is not None and self.running:
                    print("Process exited unexpectedly. Restarting...")
                    self.start_process()
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_watchdog()

if __name__ == "__main__":
    watchdog = Watchdog("LMS_bypass.pyw")
    watchdog.run()
