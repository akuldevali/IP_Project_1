from flask import Flask, send_file, request
import time
import os
import logging
from werkzeug.utils import secure_filename

app = Flask(__name__)

logging.basicConfig(
    filename='http1_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    safe_filename = secure_filename(filename)
    file_path = f"Data files/{safe_filename}"
    
    if not os.path.exists(file_path):
        logging.error(f"File not found: {safe_filename}")
        return "File not found", 404

    file_size = os.path.getsize(file_path)
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    logging.info(f"Serving file: {safe_filename} ({file_size} bytes) to {client_ip}")
    
    return send_file(file_path, as_attachment=True)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    logging.info("Shutdown request received")
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        logging.error("Failed to shut down - not running with Werkzeug Server")
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    logging.info("Server shutting down")
    return 'Server shutting down...'

if __name__ == '__main__':
    os.makedirs("Data files", exist_ok=True)
    
    print("HTTP/1.1 Server starting...")
    print("Ensure 'Data files' directory contains the required test files (A_10kB, B_10kB, etc.)")
    
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    
    logging.info("HTTP/1.1 Server starting on 0.0.0.0:8080")
    
    data_dir = "Data files"
    if os.path.exists(data_dir):
        files = os.listdir(data_dir)
        logging.info(f"Available files: {', '.join(files)}")
    else:
        logging.warning(f"Data directory '{data_dir}' not found")
    
    app.run(host='0.0.0.0', port=8080, threaded=True)