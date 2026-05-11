"""PyInstaller entry point."""
import multiprocessing
import webbrowser
import threading
import uvicorn

def _open_browser():
    import time
    time.sleep(2)
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
