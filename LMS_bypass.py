import ctypes
import keyboard
import tkinter as tk
from PIL import ImageGrab, Image
import os
import stat
import shutil
import threading
import pyperclip
from google import genai
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# -----------------------------
# Global Configuration & Setup
# -----------------------------
load_dotenv()
API_KEY = os.getenv("API_KEY")
client = genai.Client(api_key=API_KEY)
executor = ThreadPoolExecutor(max_workers=4)

# Directory and global variables
IMAGE_DIR = 'img'
os.makedirs(IMAGE_DIR, exist_ok=True)
screenshot_counter = 1
logged_text = []          # For storing clipboard text
captured_images = []      # For storing captured image file paths

def setup_dpi_awareness():
    """Enable DPI awareness for accurate screen coordinates on Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception as e:
        print("Failed to set DPI awareness:", e)

def remove_readonly(func, path, _):
    """Helper to change file permission if deletion is blocked."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

# -----------------------------
# Response Display
# -----------------------------
def show_response(response_text):
    """
    Display the Gemini response in a borderless, always-on-top Tkinter window
    with a transparent background that auto-closes after 5 seconds.
    """
    def _show():
        window = tk.Tk()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        transparent_color = "magenta"
        window.config(bg=transparent_color)
        window.attributes("-transparentcolor", transparent_color)

        # Position the window in the bottom-right corner.
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        window_width, window_height = 300, 100
        x = screen_width - window_width - 10
        y = screen_height - window_height - 10
        window.geometry(f"{window_width}x{window_height}+{x}+{y}")

        label = tk.Label(window, text=response_text, font=("Helvetica", 10),
                         bg=transparent_color, fg="black", wraplength=280, justify="left")
        label.pack(expand=True, fill="both")
        window.after(5000, window.destroy)
        window.mainloop()

    threading.Thread(target=_show, daemon=True).start()

# -----------------------------
# Input Capture Functions
# -----------------------------
def capture_region():
    """
    Display a translucent full-screen overlay to allow the user to select a region.
    Capture and save the selected region as an image file in IMAGE_DIR.
    """
    global screenshot_counter, captured_images
    root = tk.Tk()
    root.attributes('-fullscreen', True)
    root.attributes('-alpha', 0.3)
    root.config(bg='black')

    canvas = tk.Canvas(root, cursor='cross', bg='grey')
    canvas.pack(fill=tk.BOTH, expand=True)

    start_x = start_y = None
    rect = None

    def on_button_press(event):
        nonlocal start_x, start_y, rect
        start_x, start_y = event.x, event.y
        rect = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

    def on_move(event):
        nonlocal rect
        canvas.coords(rect, start_x, start_y, event.x, event.y)

    def on_release(event):
        nonlocal start_x, start_y, rect
        global screenshot_counter  # Declare as global because screenshot_counter is defined at module level
        end_x, end_y = event.x, event.y
        root.update_idletasks()
        abs_x1 = root.winfo_rootx() + min(start_x, end_x)
        abs_y1 = root.winfo_rooty() + min(start_y, end_y)
        abs_x2 = root.winfo_rootx() + max(start_x, end_x)
        abs_y2 = root.winfo_rooty() + max(start_y, end_y)
        root.destroy()

        # Capture and save the image
        image = ImageGrab.grab(bbox=(abs_x1, abs_y1, abs_x2, abs_y2))
        filename = os.path.join(IMAGE_DIR, f"screenshot_{screenshot_counter}.png")
        image.save(filename)
        captured_images.append(filename)
        print(f"Screenshot saved as {filename}")
        screenshot_counter += 1

    canvas.bind("<ButtonPress-1>", on_button_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.mainloop()


def on_copy():
    """
    Capture clipboard content (triggered by Ctrl+C) and log it if unique.
    """
    content = pyperclip.paste().strip()
    if content and content not in logged_text:
        logged_text.append(content)
        print(f"Logged text: {content}")

# -----------------------------
# Gemini API Query Functions
# -----------------------------
def process_text_only_query():
    """
    Process text-only queries by concatenating logged clipboard content,
    sending it to the Gemini API, and displaying the response.
    """
    if not logged_text:
        print("No text content available!")
        return

    combined_text = " ".join(logged_text)
    logged_text.clear()
    prompt = (
        "Extract only the correct answer choice from the given multiple-choice question. "
        "Output strictly in the format: '[Letter]. [Answer]'. Do not include explanations or extra text. "
        "If unclear, return 'Uncertain'.\n" + combined_text
    )
    future = executor.submit(
        client.models.generate_content,
        model="gemini-2.0-flash-thinking-exp-01-21",
        contents=prompt
    )

    def handle_response(fut):
        try:
            response = fut.result()
            print("Text-only query response:")
            print(response.text)
            show_response(response.text)
        except Exception as e:
            print("Error processing text-only query:", e)

    future.add_done_callback(lambda fut: threading.Thread(target=handle_response, args=(fut,), daemon=True).start())

def process_single_image(img_path):
    """
    Process a single image using the Gemini API and delete the file after processing.
    """
    try:
        image_obj = Image.open(img_path)
    except Exception as e:
        print(f"Error opening image {img_path}: {e}")
        return None

    prompt = (
        "Extract only the correct answer choice from the given multiple-choice question in the image. "
        "Output strictly in the format: '[Letter]. [Answer]'. Do not include explanations. "
        "If unclear, return 'Uncertain'."
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, image_obj]
        )
        # Delete the image file after processing.
        try:
            os.remove(img_path)
            print(f"Deleted processed image {img_path}")
        except Exception as e:
            print(f"Error deleting image {img_path}: {e}")
        return response.text
    except Exception as e:
        print(f"Error processing image {img_path}: {e}")
        return None

def process_image_only_query():
    """
    Process image-only queries by sending all images in IMAGE_DIR to the Gemini API.
    Once processing is complete, delete the entire IMAGE_DIR.
    """
    image_files = [os.path.join(IMAGE_DIR, f) for f in os.listdir(IMAGE_DIR)
                   if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not image_files:
        print("No images available for processing!")
        return

    futures = {executor.submit(process_single_image, img_path): img_path for img_path in image_files}
    for future in as_completed(futures):
        img_path = futures[future]
        try:
            response_text = future.result()
            if response_text:
                print(f"Image-only query response for {img_path}: {response_text}")
                show_response(response_text)
        except Exception as e:
            print(f"Error processing image {img_path}: {e}")

    # Delete the entire image directory after processing.
    try:
        shutil.rmtree(IMAGE_DIR, onerror=remove_readonly)
        os.makedirs(IMAGE_DIR, exist_ok=True)
        print("Image directory cleared after processing!")
    except Exception as e:
        print("Error clearing image directory:", e)

def process_combined_query():
    """
    Process combined queries that include both text (from clipboard) and an image.
    The latest captured image is used, and the image file is deleted after processing.
    """
    if not logged_text:
        print("No text content available for combined query!")
        return
    if not captured_images:
        print("No captured images available for combined query!")
        return

    combined_text = " ".join(logged_text)
    logged_text.clear()
    # Use the most recent captured image.
    image_path = captured_images.pop()
    try:
        image_obj = Image.open(image_path)
    except Exception as e:
        print(f"Error opening image {image_path}: {e}")
        return

    prompt = (
        "Extract only the correct answer choice from the given multiple-choice question provided as both text and image. "
        "Output strictly in the format: '[Letter]. [Answer]'. Do not include extra text. "
        "If unclear, return 'Uncertain'."
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, combined_text, image_obj]
        )
        print("Combined query response:")
        print(response.text)
        show_response(response.text)
        # Delete the processed image file.
        try:
            os.remove(image_path)
            print(f"Deleted processed image {image_path}")
        except Exception as e:
            print(f"Error deleting image {image_path}: {e}")
    except Exception as e:
        print("Error processing combined query:", e)

# -----------------------------
# Hotkey Registration & Main Loop
# -----------------------------
def register_hotkeys():
    """
    Register hotkeys for the three distinct functionalities:
      - Ctrl+Alt+C: Capture screen region.
      - Ctrl+C: Log clipboard text.
      - Ctrl+Alt+V: Process text-only query.
      - Ctrl+Alt+I: Process image-only query.
      - Ctrl+Alt+B: Process combined text and image query.
    """
    keyboard.add_hotkey('ctrl+alt+c', capture_region)
    keyboard.add_hotkey('ctrl+c', on_copy)
    keyboard.add_hotkey('ctrl+alt+v', process_text_only_query)
    keyboard.add_hotkey('ctrl+alt+i', process_image_only_query)
    keyboard.add_hotkey('ctrl+alt+b', process_combined_query)

def main():
    setup_dpi_awareness()
    register_hotkeys()
    print("Hotkeys registered:")
    print("  Ctrl+Alt+C: Capture region")
    print("  Ctrl+C: Log clipboard text")
    print("  Ctrl+Alt+V: Process text-only query")
    print("  Ctrl+Alt+I: Process image-only query")
    print("  Ctrl+Alt+B: Process combined text and image query")
    keyboard.wait()

if __name__ == "__main__":
    main()
