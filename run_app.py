"""
New application entry point using the factory pattern.
This is the refactored version - once complete, rename to app.py.
"""
from app import create_app, get_socketio
import logging
# Create the app instance
app = create_app()

app.logger.setLevel(logging.INFO)

# Get socketio instance for running
socketio = get_socketio()

if __name__ == '__main__':
    socketio.run(app, debug=False)
