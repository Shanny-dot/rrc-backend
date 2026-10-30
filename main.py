# Render starts the server with `uvicorn main:app`; the app itself is defined in app/main.py.
from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
