from flask import Flask, send_file, request
import time
import os
import logging
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configure basic logging
logging.basicConfig(
    filename='http1_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    # Secure the filename
    safe_filename = secure_filename(filename)
    file_path = f"Data files/{safe_filename}"
    
    if not os.path.exists(file_path):
        logging.error(f"File not found: {safe_filename}")
        return "File not found", 404

    # Log the download request (basic info)
    file_size = os.path.getsize(file_path)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    logging.info(f"Serving file: {safe_filename} ({file_size} bytes) to {client_ip}")
    
    # Send the file with minimal overhead
    return send_file(file_path, as_attachment=True)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Shutdown the server"""
    logging.info("Shutdown request received")
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        logging.error("Failed to shut down - not running with Werkzeug Server")
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    logging.info("Server shutting down")
    return 'Server shutting down...'

if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs("Data files", exist_ok=True)
    
    print("HTTP/1.1 Server starting...")
    print("Ensure 'Data files' directory contains the required test files (A_10kB, B_10kB, etc.)")
    
    # Disable Flask's default logging
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    
    # Log server start
    logging.info("HTTP/1.1 Server starting on 0.0.0.0:8080")
    
    # Check and log available files
    data_dir = "Data files"
    if os.path.exists(data_dir):
        files = os.listdir(data_dir)
        logging.info(f"Available files: {', '.join(files)}")
    else:
        logging.warning(f"Data directory '{data_dir}' not found")
    
    # Start Flask server with threading for better performance
    app.run(host='0.0.0.0', port=8080, threaded=True)