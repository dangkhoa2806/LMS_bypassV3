import os
import ctypes
import threading
import logging
import queue
import io
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Optional, List, Set

import tkinter as tk
from PIL import ImageGrab, Image
import keyboard
import pyperclip
from google import genai
from google.genai import types
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
        win.update_idletasks()
        
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
    # Sample prompts for the stupid Gemini API
    PROMPT_TEXT_IMAGE = (
        "You are an AI assistant specializing in multiple-choice question analysis. "
        "Extract the correct answer based on both text and image inputs. "
        "Return only the final answer in the format '<letter> <answer>' if answer choices exist, or '<answer>' if not. "
        "Do not provide any additional explanation. If you are not 100% certain, return 'I don't know :)'."
    )

    PROMPT_TEXT_ONLY = (    
        "You are an AI assistant trained for precise multiple-choice question analysis. "
        "Determine the correct answer from the text input. "
        "Return only the final answer in the format '<letter> <answer>' if answer choices exist, or '<answer>' if not. "
        "Do not provide any additional explanation. If you are not 100% certain, return 'I don't know :)'."
    )

    PROMPT_IMAGE_ONLY = (
        "You are an AI assistant specializing in visual content analysis. "
        "Analyze the image of a multiple-choice question and extract the correct answer. "
        "Return only the final answer in the format '<letter> <answer>' if answer choices exist, or '<answer>' if not. "
        "Do not provide any additional explanation. If you are not 100% certain, return 'I don't know :)'."
    )
    
    def __init__(self) -> None:
        load_dotenv()
        # Read the 3 API keys from .env
        self.api_keys = [
            os.getenv("API_KEY1"),
            os.getenv("API_KEY2"),
            os.getenv("API_KEY3")
        ]
        if not all(self.api_keys):
            logger.error("Missing one of API_KEY1, API_KEY2, API_KEY3 in the environment variables!")
            raise ValueError("Missing API keys")
        # Create a client for each API key
        self.clients = [genai.Client(api_key=key) for key in self.api_keys]
        self.api_index = 0
        self.api_lock = threading.Lock()

        self.executor = ThreadPoolExecutor(max_workers=8)
        self.screenshot_counter: int = 1

        # Use locks to protect concurrent access for text and images
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
    # Helper to encode image to base64 string
    # -----------------------------
    def _encode_image(self, image_obj: Image.Image) -> str:
        buffered = io.BytesIO()
        image_obj.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    # -----------------------------
    # API Call Helper (following Google's sample structure)
    # -----------------------------
    def _get_next_client(self):
        with self.api_lock:
            client = self.clients[self.api_index]
            self.api_index = (self.api_index + 1) % len(self.clients)
            return client

    def _call_api_single(self, client, model: str, prompt: str) -> Optional[str]:
        """
        Send a request using a specific API client.
        """
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)]
            )
        ]
        generate_content_config = types.GenerateContentConfig(
            temperature=0.3,
            top_p=0.87,
            top_k=40,
            max_output_tokens=8192,
            response_mime_type="text/plain",
        )
        try:
            response = ""
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text is not None:
                    response += chunk.text
            return response
        except Exception as e:
            err_msg = f"API call error: {e}"
            logger.error(err_msg)
            self.show_message(err_msg)
            return None

    # NEW: Single API call using round-robin
    def _call_api(self, model: str, prompt: str) -> Optional[str]:
        """
        Send the API request using a single client selected in round-robin fashion.
        """
        client = self._get_next_client()
        return self._call_api_single(client, model, prompt)

# -----------------------------
# Gemini API Query Functions
# -----------------------------
    def process_api_query(
        self, 
        text_input: Optional[str] = None, 
        image_input: Optional[Image.Image] = None
    ) -> Optional[str]:
        """
        Process API query based on the provided inputs:
        - If both text and image are provided: use the combined query.
        - If only text is provided: use the text-only prompt.
        - If only image is provided: use the image-only prompt.
        """
        if not text_input and not image_input:
            msg = "No content provided!"
            self.show_message(msg)
            logger.warning(msg)
            return None

        # Build the prompt based on input type
        if text_input and image_input:
            prompt = (
                self.PROMPT_TEXT_IMAGE + "\n" +
                text_input + "\n" +
                "IMAGE_DATA: " + self._encode_image(image_input)
            )
        elif text_input:
            prompt = self.PROMPT_TEXT_ONLY + "\n" + text_input
        elif image_input:       
            prompt = self.PROMPT_IMAGE_ONLY + "\n" + "IMAGE_DATA: " + self._encode_image(image_input)

        model = "gemini-2.0-pro-exp-02-05"
        # Use the new round-robin API call function
        response_text = self._call_api(model, prompt)
        if response_text:
            logger.info("API Response: %s", response_text)
            self.show_message(response_text)
        return response_text

    def process_text_only_query(self) -> None:
        """Process query using only the saved clipboard text."""
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
        response_text = self._call_api("gemini-2.0-pro-exp-02-05", self.PROMPT_IMAGE_ONLY + "\n" + "IMAGE_DATA: " + self._encode_image(image_obj))
        return response_text

    def process_combined_query(self) -> None:
        """
        Process query using both the saved clipboard text and the most recent captured image.
        """
        with self.text_lock:
            if not self.logged_text:
                msg = "No text content available for combined query!"
                self.show_message(msg)
                logger.warning(msg)
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

        prompt = (
            self.PROMPT_TEXT_IMAGE + "\n" +
            combined_text + "\n" +
            "IMAGE_DATA: " + self._encode_image(image_obj)
        )
        response_text = self._call_api("gemini-2.0-pro-exp-02-05", prompt)
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
    # Input Capture Functions
    # -----------------------------
    def capture_region(self) -> None:
        """
        Display a full-screen overlay that allows selecting a region.
        After selection, capture the screenshot and store it in memory.
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
        Retrieve clipboard content when the hotkey is triggered and store it if not already logged.
        """
        content = pyperclip.paste().strip()
        if content:
            with self.text_lock:
                if content not in self.logged_text_set:
                    self.logged_text.append(content)
                    self.logged_text_set.add(content)
                    logger.info("Logged clipboard text: %s", content)

# -----------------------------
# Entry Point
# -----------------------------
if __name__ == "__main__":
    #The gemini is too stupid to slove the scientific questions.
    try:
        App.setup_dpi_awareness()
        app = App()
        app.run()
    except Exception as e:
        logger.exception("An unexpected error occurred: %s", e)