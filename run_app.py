"""
New application entry point using the factory pattern.
This is the refactored version - once complete, rename to app.py.
"""

from app import create_app
import logging

# Create the app instance
app = create_app()

app.logger.setLevel(logging.INFO)

if __name__ == "__main__":
    app.run(debug=False)
