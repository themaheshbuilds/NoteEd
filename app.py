import os
import sys

# Add current directory to path to ensure modules load cleanly when running locally
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.index import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000, use_reloader=False, threaded=True)

