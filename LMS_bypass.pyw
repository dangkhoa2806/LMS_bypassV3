import ctypes
import os
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Optional, List, Set
import queue

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
# Message Manager using Tkinter (reused for all messages)
# -----------------------------
class MessageManager:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the main window
        self._check_queue()
        self.root.mainloop()

    def _check_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self._show_message(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._check_queue)

    def _show_message(self, message_text: str):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        transparent_color = "magenta"
        win.config(bg=transparent_color)
        win.attributes("-transparentcolor", transparent_color)
        
        # Set the window size
        window_width, window_height = 300, 100
        # Set temporary geometry to update internal parameters
        win.geometry(f"{window_width}x{window_height}+0+0")
        win.update_idletasks()  # Ensure screen parameters are updated,
        
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        x = screen_width - window_width - 10
        y = screen_height - window_height - 10
        # Reposition the window to the bottom-right corner
        win.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        label = tk.Label(
            win,
            text=message_text,
            font=("Helvetica", 10),
            bg=transparent_color,
            fg="black",
            wraplength=280,
            justify="left"
        )
        label.pack(expand=True, fill="both")
        win.after(5000, win.destroy)

    def show_message(self, message_text: str):
        self.msg_queue.put(message_text)


# -----------------------------
# Application Class
# -----------------------------
class App:
    # Sample prompts for the fucking gemini. Were I had more money, I'd use chatgpt instead
    PROMPT_TEXT_IMAGE = (
    "You are an AI assistant specializing in multiple-choice question analysis. "
    "Your task is to extract the correct answer from a multiple-choice question presented in both text and image formats. "
    "You must follow a strict reasoning process by verifying information from multiple reliable sources or performing necessary calculations. "
    "Only respond when you are 100% certain of the answer. "
    "If the input does not include answer choices, use calculations, reasoning, and verification to determine the final answer. "
    "Return only the answer without any explanations or additional text, strictly formatted as '[Letter]. [Answer]' if answer choices exist, or as just the final answer if they do not."
    )

    PROMPT_TEXT_ONLY = (
    "You are an AI assistant trained for precise multiple-choice question analysis. "
    "You must verify all information through logical reasoning, reliable sources, or accurate calculations. "
    "If the question does not provide answer choices, use calculations, reasoning, and verification to determine the final answer. "
    "If the correct answer is ambiguous or cannot be determined with certainty, return 'Uncertain'. "
    "Return only the answer without any explanations or additional content, strictly formatted as '[Letter]. [Answer]' if answer choices exist, or as just the final answer if they do not."
    )

    PROMPT_IMAGE_ONLY = (
    "You are an AI assistant specializing in visual content analysis. "
    "Your task is to extract the correct answer from a multiple-choice question presented in an image format. "
    "Based on careful analysis, logical deduction, and verification from multiple sources or necessary calculations, only respond when you are 100% certain of the answer. "
    "If the image does not provide answer choices, use reasoning and calculations to determine the final answer. "
    "If the correct answer cannot be determined with certainty, return 'Uncertain'. "
    "Return only the answer without any explanations or additional text, strictly formatted as '[Letter]. [Answer]' if answer choices exist, or as just the final answer if they do not."
)



    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("API_KEY")
        if not api_key:
            logger.error("API_KEY is not set in the environment variables!")
            raise ValueError("Missing API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.screenshot_counter: int = 1

        # Use locks to protect concurrent access
        self.text_lock = threading.Lock()
        self.logged_text: List[str] = []
        self.logged_text_set: Set[str] = set()

        self.image_lock = threading.Lock()
        self.captured_images: List[Image.Image] = []

        # Initialize MessageManager for displaying messages
        self.message_manager = MessageManager()

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
    # Message Display
    # -----------------------------
    def show_message(self, message_text: str) -> None:
        self.message_manager.show_message(message_text)

    # -----------------------------
    # Input Capture Functions
    # -----------------------------
    def capture_region(self) -> None:
        """
        Display a full-screen overlay that allows selecting a region.
        After selection, capture the screenshot and save it in memory.
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

            try:
                image = ImageGrab.grab(bbox=(abs_x1, abs_y1, abs_x2, abs_y2))
                with self.image_lock:
                    self.captured_images.append(image)
                logger.info("Screenshot captured in memory (total: %d)", len(self.captured_images))
                self.screenshot_counter += 1
            except Exception as e:
                err_msg = f"Error capturing screenshot: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)

        canvas.bind("<ButtonPress-1>", on_button_press)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.mainloop()

    def on_copy(self) -> None:
        """
        Retrieve clipboard content when the hotkey is triggered and save it if not already stored.
        """
        content = pyperclip.paste().strip()
        if content:
            with self.text_lock:
                if content not in self.logged_text_set:
                    self.logged_text.append(content)
                    self.logged_text_set.add(content)
                    logger.info("Logged clipboard text: %s", content)

    # -----------------------------
    # API Call Helper with Timeout
    # -----------------------------
    def _call_api(self, model: str, contents: List) -> Optional[str]:
        """
        Execute an API call through the executor and wait for the result with a timeout.
        """
        future = self.executor.submit(self.client.models.generate_content, model=model, contents=contents)
        try:
            response = future.result(timeout=40)
            return response.text
        except TimeoutError:
            err_msg = "API call timed out!"
            logger.error(err_msg)
            self.show_message(err_msg)
        except Exception as e:
            err_msg = f"API call error: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
        return None

    # -----------------------------
    # Gemini API Query Functions
    # -----------------------------
    def process_api_query(
        self, 
        text_input: Optional[str] = None, 
        image_input: Optional[Image.Image] = None
    ) -> Optional[str]:
        """
        Process API query based on the inputs:
          - If both text and image are provided: use the combined query.
          - If only text is provided: use the text-only query.
          - If only image is provided: use the image-only query.
        """
        if not text_input and not image_input:
            msg = "No content provided!"
            self.show_message(msg)
            logger.warning(msg)
            return None

        if text_input and image_input:
            contents = [self.PROMPT_TEXT_IMAGE, text_input, image_input]
            model = "gemini-2.0-pro-exp-02-05"
        elif text_input:
            contents = [self.PROMPT_TEXT_ONLY + "\n" + text_input]
            model = "gemini-2.0-pro-exp-02-05"
        elif image_input:
            contents = [self.PROMPT_IMAGE_ONLY, image_input]
            model = "gemini-2.0-pro-exp-02-05"

        response_text = self._call_api(model, contents)
        if response_text:
            logger.info("API Response: %s", response_text)
            self.show_message(response_text)
        return response_text

    def process_text_only_query(self) -> None:
        """Process query using only the saved clipboard content."""
        with self.text_lock:
            if not self.logged_text:
                msg = "No text content available!"
                self.show_message(msg)
                logger.warning(msg)
                return
            combined_text = " ".join(self.logged_text)
            self.logged_text.clear()
            self.logged_text_set.clear()
        self.executor.submit(self.process_api_query, text_input=combined_text)

    def process_image_only_query(self) -> None:
        """Process query using the captured images."""
        with self.image_lock:
            if not self.captured_images:
                msg = "No images available for processing!"
                self.show_message(msg)
                logger.warning(msg)
                return
            images_to_process = self.captured_images.copy()
            self.captured_images.clear()

        futures = {self.executor.submit(self._process_single_image, img): img for img in images_to_process}
        for future in as_completed(futures):
            try:
                response_text = future.result(timeout=5)
                if response_text:
                    logger.info("Image query response: %s", response_text)
                    self.show_message(response_text)
            except Exception as e:
                err_msg = f"Error processing an image: {e}"
                logger.error(err_msg)
                self.show_message(err_msg)

    def _process_single_image(self, image_obj: Image.Image) -> Optional[str]:
        """Process a single image."""
        response_text = self._call_api("gemini-2.0-pro-exp-02-05", [self.PROMPT_IMAGE_ONLY, image_obj])
        return response_text

    def process_combined_query(self) -> None:
        """
        Process query using both the saved clipboard content and the recently captured image.
        """
        with self.text_lock:
            if not self.logged_text:
                msg = "No text content available for combined query!"
                self.show_message(msg)
                logger.warning(msg) # I dunno why it doesn't work...
                return
            combined_text = " ".join(self.logged_text)
            self.logged_text.clear()
            self.logged_text_set.clear()
        with self.image_lock:
            if not self.captured_images:
                msg = "No captured images available for combined query!"
                self.show_message(msg)
                logger.warning(msg)
                return
            image_obj = self.captured_images.pop()

        response_text = self._call_api("gemini-2.0-pro-exp-02-05", [self.PROMPT_TEXT_IMAGE, combined_text, image_obj])
        if response_text:
            logger.info("Combined query response: %s", response_text)
            self.show_message(response_text)

    # -----------------------------
    # Hotkey Registration & Main Loop
    # -----------------------------
    def register_hotkeys(self) -> None:
        """
        Register hotkeys:
         - Ctrl+Alt+Shift+C: Capture screen region
         - Ctrl+Alt+C: Save clipboard content
         - Ctrl+Alt+V: Process API query (text-only or combined)
        """
        keyboard.add_hotkey('ctrl+alt+shift+c', self.capture_region)
        keyboard.add_hotkey('ctrl+alt+c', self.on_copy)

        def process_current_query():
            with self.text_lock:
                text = " ".join(self.logged_text) if self.logged_text else None
                self.logged_text.clear()
                self.logged_text_set.clear()
            with self.image_lock:
                image = self.captured_images.pop() if self.captured_images else None
            self.process_api_query(text_input=text, image_input=image)

        keyboard.add_hotkey('ctrl+alt+v', lambda: self.executor.submit(process_current_query))

    def run(self) -> None:
        """Initialize DPI awareness, register hotkeys and wait for events."""
        self.setup_dpi_awareness()
        self.register_hotkeys()
        logger.info("Hotkeys registered:")
        logger.info("  Ctrl+Alt+Shift+C: Capture region")
        logger.info("  Ctrl+Alt+C: Log clipboard text")
        logger.info("  Ctrl+Alt+V: Process API query")
        try:
            keyboard.wait()
        except KeyboardInterrupt:
            logger.info("Exiting...")
        finally:
            self.executor.shutdown(wait=False)

# -----------------------------
# Entry Point
# -----------------------------
if __name__ == "__main__":
    try:
        App.setup_dpi_awareness()
        app = App()
        app.run()
    except Exception as e:
        logger.exception("An unexpected error occurred: %s", e) 