import os

from app import create_app

app = create_app(os.environ.get("MDFEDIT_CONFIG"))

if __name__ == "__main__":
    server = app.config["APP_CFG"].get("server", {})
    app.run(
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8000)),
        debug=False,
    )
