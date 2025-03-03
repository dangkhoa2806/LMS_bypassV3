import time
import pyperclip
import keyboard
import tkinter as tk
from google import genai
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("API_KEY")

print("Copy content using Ctrl + C. Press Ctrl + Alt + V to stop and concatenate.")
logged_content = []

executor = ThreadPoolExecutor(max_workers=2)
 
def show_response(response_text):
    def _show():
        response_window = tk.Tk()
        response_window.overrideredirect(True)
        response_window.attributes("-topmost", True)
        
        transparent_color = "magenta"
        response_window.config(bg=transparent_color)
        response_window.attributes("-transparentcolor", transparent_color)
        
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

def on_copy():
    content = pyperclip.paste().strip()
    if content and content not in logged_content:
        logged_content.append(content)
        print(f"Saved: {content}")

def process_prompt(prompt):
    return client.models.generate_content(
        model="gemini-2.0-flash-thinking-exp-01-21",
        contents=prompt
    )

def on_concatenate():
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

client = genai.Client(api_key = API_KEY)

keyboard.add_hotkey('ctrl+c', on_copy)
keyboard.add_hotkey('ctrl+alt+v', on_concatenate)
keyboard.wait()