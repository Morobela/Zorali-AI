import sys
mods = ["fastapi", "uvicorn", "pydantic_settings", "httpx", "jose", "passlib", "multipart"]
missing = []
for m in mods:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
if missing:
    print("MISSING: " + ", ".join(missing))
else:
    print("ALL OK")
