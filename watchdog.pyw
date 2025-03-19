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
        self.start_process()

    def start_process(self):
        """
        Start the monitored process in the background.
        On Windows, the process is started with no console window.
        """
        print(f"Starting process {self.script_name}...")
        if os.name == "nt":
            # Combine flags to create a new process group and hide the console window.
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

    def hotkey_callback(self):
        """
        Callback function triggered by the hotkey (Ctrl+Shift+Backspace).
        """
        print("Hotkey Ctrl+Shift+Backspace pressed. Restarting process...")
        self.restart_process()

    def run(self):
        """
        Register the hotkey and start monitoring the process.
        """
        # Register the hotkey to trigger process restart
        keyboard.add_hotkey("ctrl+shift+backspace", self.hotkey_callback)
        print("Watchdog is running. Press Ctrl+Shift+Backspace to restart the process.")
        try:
            while True:
                # If the process has terminated unexpectedly, restart it.
                if self.process.poll() is not None:
                    print("Process exited unexpectedly. Restarting...")
                    self.start_process()
                time.sleep(1)
        except KeyboardInterrupt:
            print("Watchdog interrupted. Exiting...")
            if self.process and self.process.poll() is None:
                self.process.terminate()
            keyboard.unhook_all_hotkeys()

if __name__ == "__main__":
    watchdog = Watchdog("LMS_bypass.pyw")
    watchdog.run()
