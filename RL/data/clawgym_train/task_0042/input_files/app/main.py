import os
import json
from fastapi import FastAPI, HTTPException

app = FastAPI()


def load_gigs(file_path: str | None = None):
    path = file_path or os.environ.get("GIGS_FILE", "data/gigs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            gigs = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"GIGS_FILE not found: {path}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in {path}: {e}")

    if not isinstance(gigs, list):
        raise HTTPException(status_code=500, detail="Invalid gigs format; expected a list")

    required = {"date", "venue", "city", "songs_count"}
    for idx, g in enumerate(gigs):
        if not isinstance(g, dict) or not required.issubset(g.keys()):
            raise HTTPException(status_code=500, detail=f"Invalid gig at index {idx}; missing required keys")
        if not isinstance(g["songs_count"], int):
            raise HTTPException(status_code=500, detail=f"Invalid songs_count at index {idx}; expected int")
    return gigs


@app.get("/gigs")
def get_gigs():
    gigs = load_gigs()
    return {"count": len(gigs), "gigs": gigs}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
