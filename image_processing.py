import ctypes
import keyboard
import tkinter as tk
from PIL import ImageGrab, Image
import os
import time
import pyperclip
from google import genai
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# ---------------------------
# INITIAL CONFIGURATION
# ---------------------------

def setup_dpi_awareness():
    """
    Set DPI awareness on Windows to ensure accurate screen coordinates.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception as e:
        print("Failed to set DPI awareness:", e)

os.makedirs('img', exist_ok=True)

# Global variables for screenshot capture and clipboard logging
captured_images = []
screenshot_counter = 1
logged_content = []

# Load environment variables and initialize Gemini client
load_dotenv()
API_KEY = os.getenv("API_KEY")
client = genai.Client(api_key=API_KEY)

# Executor for asynchronous Gemini API calls
executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------
# DISPLAY RESPONSE FUNCTION
# ---------------------------

def show_response(response_text):
    """
    Create a borderless, always-on-top Tkinter window to display the Gemini response.
    The window uses a transparent background and auto-destroys after 5 seconds.
    """
    def _show():
        response_window = tk.Tk()
        response_window.overrideredirect(True)
        response_window.attributes("-topmost", True)
        
        transparent_color = "magenta"
        response_window.config(bg=transparent_color)
        response_window.attributes("-transparentcolor", transparent_color)
        
        # Calculate window position (bottom-right corner)
        screen_width = response_window.winfo_screenwidth()
        screen_height = response_window.winfo_screenheight()
        window_width = 300
        window_height = 100
        x = screen_width - window_width - 10
        y = screen_height - window_height - 10
        response_window.geometry(f"{window_width}x{window_height}+{x}+{y}")

        label = tk.Label(
            response_window,
            text=response_text,
            font=("Helvetica", 10),
            bg=transparent_color,
            fg="black",
            wraplength=280,
            justify="left"
        )
        label.pack(expand=True, fill="both")
        response_window.after(5000, response_window.destroy)
        response_window.mainloop()

    threading.Thread(target=_show, daemon=True).start()

# ---------------------------
# SCREEN CAPTURE FUNCTION
# ---------------------------

def capture_region():
    """
    Create a UI for selecting a region on the screen and capture the selected area.
    Save the image with a unique filename and add it to captured_images.
    """
    global captured_images

    root = tk.Tk()
    root.attributes('-fullscreen', True)
    root.attributes('-alpha', 0.3)
    root.config(bg='black')

    canvas = tk.Canvas(root, cursor='cross', bg='grey')
    canvas.pack(fill=tk.BOTH, expand=True)

    start_x, start_y = None, None
    rect = None

    def on_button_press(event):
        nonlocal start_x, start_y, rect
        start_x, start_y = event.x, event.y
        rect = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

    def on_move_press(event):
        nonlocal rect
        canvas.coords(rect, start_x, start_y, event.x, event.y)

    def on_button_release(event):
        nonlocal start_x, start_y, rect
        global screenshot_counter  # Khai báo biến toàn cục ở đây
        end_x, end_y = event.x, event.y

        root.update_idletasks()
        abs_x1 = root.winfo_rootx() + min(start_x, end_x)
        abs_y1 = root.winfo_rooty() + min(start_y, end_y)
        abs_x2 = root.winfo_rootx() + max(start_x, end_x)
        abs_y2 = root.winfo_rooty() + max(start_y, end_y)
        root.destroy()

        # Capture the selected region and save the image to the 'img' folder
        image = ImageGrab.grab(bbox=(abs_x1, abs_y1, abs_x2, abs_y2))
        filename = os.path.join('img', f"screenshot_{screenshot_counter}.png")
        image.save(filename)
        captured_images.append(filename)
        print(f"Screenshot saved as {filename}")

        screenshot_counter += 1

    canvas.bind("<ButtonPress-1>", on_button_press)
    canvas.bind("<B1-Motion>", on_move_press)
    canvas.bind("<ButtonRelease-1>", on_button_release)
    root.mainloop()

# ---------------------------
# CLIPBOARD AND GEMINI PROCESSING
# ---------------------------

def on_copy():
    """
    Listen for clipboard changes (Ctrl + C) and save unique content to logged_content.
    """
    content = pyperclip.paste().strip()
    if content and content not in logged_content:
        logged_content.append(content)
        print(f"Saved: {content}")

def process_prompt(prompt):
    """
    Call the Gemini API with the given prompt.
    """
    return client.models.generate_content(
        model="gemini-2.0-flash-thinking-exp-01-21",
        contents=prompt
    )

def on_concatenate():
    """
    Concatenate the logged clipboard content, clear the clipboard,
    and process the prompt through the Gemini API.
    """
    if logged_content:
        combined_text = " ".join(logged_content)
        pyperclip.copy("")
        logged_content.clear()
        print("Clipboard cleared!")

        prompt = (
            "Extract only the correct answer choice from the given multiple-choice question. "
            "Output strictly in the format: '[Letter]. [Answer]'. "
            "Do not include explanations, additional text, or any formatting other than what is specified. "
            "If the question is unclear or lacks a definitive answer, return 'Uncertain' instead of guessing. "
            "Maintain accuracy and precision at all times.\n"
            f"{combined_text}"
        )
        
        future = executor.submit(process_prompt, prompt)

        def handle_response(fut):
            try:
                response = fut.result()
                print("Response from Gemini:")
                print(response.text)
                show_response(response.text)
            except Exception as e:
                print(f"Error calling Gemini API: {e}")

        future.add_done_callback(lambda fut: threading.Thread(target=handle_response, args=(fut,), daemon=True).start())

# ---------------------------
# HOTKEY REGISTRATION AND MAIN LOOP
# ---------------------------

def register_hotkeys():
    """
    Register hotkeys:
    - Ctrl+Alt+C: Capture a screen region
    - Ctrl+C: Copy content to clipboard
    - Ctrl+Alt+V: Process concatenated clipboard content through Gemini API
    """
    keyboard.add_hotkey('ctrl+alt+c', capture_region)
    keyboard.add_hotkey('ctrl+c', on_copy)
    keyboard.add_hotkey('ctrl+alt+v', on_concatenate)

def main():
    setup_dpi_awareness()
    register_hotkeys()
    print("Press CTRL+ALT+C to capture a screen region.")
    print("Copy content using Ctrl + C. Press Ctrl + Alt + V to process and concatenate clipboard content.")
    keyboard.wait()

if __name__ == "__main__":
    main()
