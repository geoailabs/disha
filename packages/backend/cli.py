"""CLI entry point for the backend — used by PyInstaller builds."""

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Cursor Urban Planners Backend")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    from main import app
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
