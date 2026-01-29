from waitress import serve
from SBProduction.wsgi import application
import os

# English: Starting the production server on port 8000
if __name__ == '__main__':
    print("Starting Waitress server on http://0.0.0.0:8000")
    serve(application, host='0.0.0.0', port=8000, threads=6)