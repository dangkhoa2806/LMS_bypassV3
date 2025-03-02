import ctypes
import os
import stat
import shutil
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Union

import tkinter as tk
from PIL import ImageGrab, Image
import keyboard
import pyperclip
from google import genai
from dotenv import load_dotenv

# -----------------------------
# Logging configuration
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# -----------------------------
# Application Class
# -----------------------------
class App:
    IMAGE_DIR: str = "img"

    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("API_KEY")
        if not api_key:
            logger.error("API_KEY is not set in the environment variables!")
            raise ValueError("Missing API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.executor = ThreadPoolExecutor(max_workers=4)
        os.makedirs(self.IMAGE_DIR, exist_ok=True)
        self.screenshot_counter: int = 1
        self.logged_text: List[str] = []         # To store clipboard text
        self.captured_images: List[str] = []       # To store image file paths

    # -----------------------------
    # DPI Awareness
    # -----------------------------
    @staticmethod
    def setup_dpi_awareness() -> None:
        """Enable DPI awareness for accurate screen coordinates on Windows."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception as e:
            logger.warning("Failed to set DPI awareness: %s", e)

    # -----------------------------
    # File removal helper
    # -----------------------------
    @staticmethod
    def remove_readonly(func, path: str, exc_info) -> None:
        """Helper to change file permissions if deletion is blocked."""
        os.chmod(path, stat.S_IWRITE)
        func(path)

    # -----------------------------
    # Message Display
    # -----------------------------
    @staticmethod
    def show_message(message_text: str) -> None:
        """
        Display a message in a borderless, always-on-top Tkinter window
        with a transparent background that auto-closes after 5 seconds.
        """
        def _show() -> None:
            window = tk.Tk()
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            transparent_color = "magenta"
            window.config(bg=transparent_color)
            window.attributes("-transparentcolor", transparent_color)

            # Position window in the bottom-right corner
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            window_width, window_height = 300, 100
            x = screen_width - window_width - 10
            y = screen_height - window_height - 10
            window.geometry(f"{window_width}x{window_height}+{x}+{y}")

            label = tk.Label(window, text=message_text, font=("Helvetica", 10),
                             bg=transparent_color, fg="black", wraplength=280, justify="left")
            label.pack(expand=True, fill="both")
            window.after(5000, window.destroy)
            window.mainloop()

        threading.Thread(target=_show, daemon=True).start()

    # -----------------------------
    # Input Capture Functions
    # -----------------------------
    def capture_region(self) -> None:
        """
        Display a translucent full-screen overlay for region selection.
        Save the selected region as an image in IMAGE_DIR.
        """
        root = tk.Tk()
        root.attributes('-fullscreen', True)
        root.attributes('-alpha', 0.3)
        root.config(bg='black')

        canvas = tk.Canvas(root, cursor='cross', bg='grey')
        canvas.pack(fill=tk.BOTH, expand=True)

        start_x: Optional[int] = None
        start_y: Optional[int] = None
        rect = None

        def on_button_press(event: tk.Event) -> None:
            nonlocal start_x, start_y, rect
            start_x, start_y = event.x, event.y
            rect = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

        def on_move(event: tk.Event) -> None:
            if rect is not None and start_x is not None and start_y is not None:
                canvas.coords(rect, start_x, start_y, event.x, event.y)

        def on_release(event: tk.Event) -> None:
            nonlocal start_x, start_y, rect
            end_x, end_y = event.x, event.y
            root.update_idletasks()
            abs_x1 = root.winfo_rootx() + min(start_x, end_x)
            abs_y1 = root.winfo_rooty() + min(start_y, end_y)
            abs_x2 = root.winfo_rootx() + max(start_x, end_x)
            abs_y2 = root.winfo_rooty() + max(start_y, end_y)
            root.destroy()

            # Capture and save the image
            try:
                image = ImageGrab.grab(bbox=(abs_x1, abs_y1, abs_x2, abs_y2))
                filename = os.path.join(self.IMAGE_DIR, f"screenshot_{self.screenshot_counter}.png")
                image.save(filename)
                self.captured_images.append(filename)
                logger.info("Screenshot saved as %s", filename)
                self.screenshot_counter += 1
            except Exception as e:
                err_msg = f"Error saving screenshot: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)

        canvas.bind("<ButtonPress-1>", on_button_press)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.mainloop()

    def on_copy(self) -> None:
        """
        Capture clipboard content (triggered by a hotkey) and log it if unique.
        """
        content = pyperclip.paste().strip()
        if content and content not in self.logged_text:
            self.logged_text.append(content)
            logger.info("Logged clipboard text: %s", content)

    # -----------------------------
    # Gemini API Query Functions
    # -----------------------------
    def process_api_query(
        self, 
        text_input: Optional[str] = None, 
        image_input_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Process API query based on available inputs:
         - If both text and image provided: perform a combined query.
         - If only text is provided: perform text-only query.
         - If only image is provided: perform image-only query.
        """
        if not text_input and not image_input_path:
            msg = "Không có nội dung nào được cung cấp!"
            self.show_message(msg)
            logger.warning(msg)
            return None

        # Combined query: both text and image are provided
        if text_input and image_input_path:
            try:
                image_obj = Image.open(image_input_path)
            except Exception as e:
                err_msg = f"Lỗi mở ảnh {image_input_path}: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)
                return None
            prompt = (
                "Extract only the correct answer choice from the given multiple-choice question provided as both text and image. "
                "Output strictly in the format: '[Letter]. [Answer]'. Do not include extra text. "
                "If unclear, return 'Uncertain'."
            )
            contents = [prompt, text_input, image_obj]
            model = "gemini-2.0-flash-thinking-exp-01-21"

        # Text-only query
        elif text_input:
            prompt = (
                "Extract only the correct answer choice from the given multiple-choice question. "
                "Output strictly in the format: '[Letter]. [Answer]'. Do not include explanations or extra text. "
                "If unclear, return 'Uncertain'.\n" + text_input
            )
            contents = [prompt]
            model = "gemini-2.0-flash-thinking-exp-01-21"

        # Image-only query
        elif image_input_path:
            try:
                image_obj = Image.open(image_input_path)
            except Exception as e:
                err_msg = f"Lỗi mở ảnh {image_input_path}: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)
                return None
            prompt = (
                "Extract only the correct answer choice from the given multiple-choice question in the image. "
                "Output strictly in the format: '[Letter]. [Answer]'. Do not include explanations. "
                "If unclear, return 'Uncertain'."
            )
            contents = [prompt, image_obj]
            model = "gemini-2.0-flash"

        try:
            response = self.client.models.generate_content(model=model, contents=contents)
            logger.info("API Response: %s", response.text)
            self.show_message(response.text)
            # Delete the image file after processing (if applicable)
            if image_input_path:
                try:
                    os.remove(image_input_path)
                    logger.info("Deleted image %s", image_input_path)
                except Exception as e:
                    logger.error("Error deleting image %s: %s", image_input_path, e)
            return response.text
        except Exception as e:
            err_msg = f"Lỗi khi xử lý API query: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
            return None

    def process_text_only_query(self) -> None:
        """Process query using logged clipboard text only."""
        if not self.logged_text:
            msg = "No text content available!"
            self.show_message(msg)
            logger.warning(msg)
            return
        combined_text = " ".join(self.logged_text)
        self.logged_text.clear()
        self.process_api_query(text_input=combined_text)

    def process_image_only_query(self) -> None:
        """Process query using all images in the IMAGE_DIR."""
        image_files = [
            os.path.join(self.IMAGE_DIR, f)
            for f in os.listdir(self.IMAGE_DIR)
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ]
        if not image_files:
            msg = "No images available for processing!"
            self.show_message(msg)
            logger.warning(msg)
            return

        futures = {self.executor.submit(self._process_single_image, path): path for path in image_files}
        for future in as_completed(futures):
            img_path = futures[future]
            try:
                response_text = future.result()
                if response_text:
                    logger.info("Image query response for %s: %s", img_path, response_text)
                    self.show_message(response_text)
            except Exception as e:
                err_msg = f"Error processing image {img_path}: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)

    def _process_single_image(self, img_path: str) -> Optional[str]:
        """Helper to process a single image and delete it afterwards."""
        try:
            image_obj = Image.open(img_path)
        except Exception as e:
            err_msg = f"Error opening image {img_path}: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
            return None

        prompt = (
            "Extract only the correct answer choice from the given multiple-choice question in the image. "
            "Output strictly in the format: '[Letter]. [Answer]'. Do not include explanations. "
            "If unclear, return 'Uncertain'."
        )
        try:
            response = self.client.models.generate_content(model="gemini-2.0-flash", contents=[prompt, image_obj])
            response_text = response.text
            try:
                os.remove(img_path)
                logger.info("Deleted processed image %s", img_path)
            except Exception as e:
                logger.error("Error deleting image %s: %s", img_path, e)
            return response_text
        except Exception as e:
            err_msg = f"Error processing image {img_path}: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
            return None

    def process_combined_query(self) -> None:
        """
        Process query using both the logged clipboard text and the most recently captured image.
        """
        if not self.logged_text:
            msg = "No text content available for combined query!"
            self.show_message(msg)
            logger.warning(msg)
            return
        if not self.captured_images:
            msg = "No captured images available for combined query!"
            self.show_message(msg)
            logger.warning(msg)
            return

        combined_text = " ".join(self.logged_text)
        self.logged_text.clear()
        image_path = self.captured_images.pop()
        try:
            image_obj = Image.open(image_path)
        except Exception as e:
            err_msg = f"Error opening image {image_path}: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
            return

        prompt = (
            "Extract only the correct answer choice from the given multiple-choice question provided as both text and image. "
            "Output strictly in the format: '[Letter]. [Answer]'. Do not include extra text. "
            "If unclear, return 'Uncertain'."
        )
        try:
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-thinking-exp-01-21", contents=[prompt, combined_text, image_obj]
            )
            logger.info("Combined query response: %s", response.text)
            self.show_message(response.text)
            try:
                os.remove(image_path)
                logger.info("Deleted processed image %s", image_path)
            except Exception as e:
                logger.error("Error deleting image %s: %s", image_path, e)
        except Exception as e:
            err_msg = f"Error processing combined query: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)

    # -----------------------------
    # Hotkey Registration & Main Loop
    # -----------------------------
    def register_hotkeys(self) -> None:
        """
        Register hotkeys for functionalities:
          - Ctrl+Alt+Shift+C: Capture region
          - Ctrl+Alt+C: Log clipboard text
          - Ctrl+Alt+V: Process API query (text-only or combined)
          - (Optionally) Ctrl+Alt+I: Process image-only query
          - (Optionally) Ctrl+Alt+B: Process combined text and image query
        """
        keyboard.add_hotkey('ctrl+alt+shift+c', self.capture_region)
        keyboard.add_hotkey('ctrl+alt+c', self.on_copy)
        keyboard.add_hotkey('ctrl+alt+v', lambda: self.process_api_query(
            text_input=" ".join(self.logged_text) if self.logged_text else None,
            image_input_path=self.captured_images.pop() if self.captured_images else None
        ))

    def run(self) -> None:
        """Initialize DPI awareness, register hotkeys, and wait for events."""
        self.setup_dpi_awareness()
        self.register_hotkeys()
        logger.info("Hotkeys registered:")
        logger.info("  Ctrl+Alt+Shift+C: Capture region")
        logger.info("  Ctrl+Alt+C: Log clipboard text")
        logger.info("  Ctrl+Alt+V: Process API query")
        keyboard.wait()


# -----------------------------
# Entry Point
# -----------------------------
if __name__ == "__main__":
    try:
        app = App()
        app.run()
    except Exception as e:
        logger.exception("An unexpected error occurred: %s", e)