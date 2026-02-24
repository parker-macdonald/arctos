"""
New application entry point using the factory pattern.
This is the refactored version - once complete, rename to app.py.
"""

import os
from app import create_app
import logging

# Create the app instance
app = create_app()

app.logger.setLevel(logging.INFO)

if __name__ == "__main__":
    # Port from env (e.g. 5006). For Dioxus dev (dx serve on 8080), run Flask on http:
    #   ARCTOS_PORT=5006 python run_app.py
    # Then use ARCTOS_API_BASE=http://127.0.0.1:5006 when building the frontend.
    port = int(os.environ.get("ARCTOS_PORT", "5006"))
    app.run(host="127.0.0.1", port=port, debug=False)
