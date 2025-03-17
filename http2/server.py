import socketserver
import socket
import h2.connection
import h2.config
import h2.events
import h2.settings
import time
import os
import logging
import json
import psutil

# Configure logging
logging.basicConfig(
    filename='http2_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Define global variables
DATA_DIR = "Data files"
BUFFER_SIZE = 1048576  # 1MB buffer size for file chunks

class H2Protocol:
    def __init__(self):
        config = h2.config.H2Configuration(client_side=False)
        self.conn = h2.connection.H2Connection(config=config)
        self.known_streams = {}
        
        # Optimized settings
        self.settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 10000,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: BUFFER_SIZE,
            h2.settings.SettingCodes.HEADER_TABLE_SIZE: 65536,  # Larger HPACK table
            h2.settings.SettingCodes.ENABLE_PUSH: 0  # Disable server push
        }
        
        # Stats tracking
        self.request_count = 0
        self.bytes_sent = 0
        self.active_connections = 0

    def handle_request(self, sock):
        # TCP optimization
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # First, do handshake
        self.conn.initiate_connection()
        
        # Update settings
        self.conn.update_settings(self.settings)
        
        sock.sendall(self.conn.data_to_send())
        
        # Track connection start time
        connection_start = time.time()
        self.active_connections += 1

        # Process requests
        try:
            while True:
                try:
                    data = sock.recv(BUFFER_SIZE)
                    if not data:
                        break

                    events = self.conn.receive_data(data)
                    for event in events:
                        if isinstance(event, h2.events.RequestReceived):
                            self.handle_request_received(event, sock)
                        elif isinstance(event, h2.events.DataReceived):
                            self.handle_data_received(event, sock)
                        elif isinstance(event, h2.events.StreamEnded):
                            self.handle_stream_ended(event, sock)
                        elif isinstance(event, h2.events.ConnectionTerminated):
                            logging.info(f"Connection terminated by client after {time.time() - connection_start:.2f} seconds")
                            return

                    # Send any pending data
                    data_to_send = self.conn.data_to_send()
                    if data_to_send:
                        sock.sendall(data_to_send)
                        
                except (socket.timeout, socket.error) as e:
                    logging.error(f"Socket error: {e}")
                    break
                except Exception as e:
                    logging.error(f"Error handling request: {e}", exc_info=True)
                    break
        finally:
            self.active_connections -= 1
            # Log connection statistics
            connection_duration = time.time() - connection_start
            logging.info(f"Connection closed. Duration: {connection_duration:.2f}s, Bytes sent: {self.bytes_sent}")
            
            # Log system resource usage
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            logging.info(f"System resources - CPU: {cpu_percent}%, Memory: {memory_percent}%")

    def handle_request_received(self, event, sock):
        stream_id = event.stream_id
        headers = dict(event.headers)
        
        # Convert headers to Python strings
        headers = {k.decode('utf-8'): v.decode('utf-8') for k, v in headers.items()}
        
        path = headers.get(':path', '')
        method = headers.get(':method', '')
        
        # Log request
        client_address = sock.getpeername()
        logging.info(f"Request from {client_address[0]}:{client_address[1]} - {method} {path}")
        
        # Initialize stream data with timing information
        self.known_streams[stream_id] = {
            'headers': headers, 
            'path': path, 
            'method': method,
            'start_time': time.time(),
            'headers_sent_time': None,
            'first_byte_time': None,
            'last_byte_time': None,
            'bytes_sent': 0
        }
        
        self.request_count += 1
        
        # Process file download request
        if method == 'GET' and path.startswith('/download/'):
            filename = path[10:]  # Remove '/download/' prefix
            self.serve_file(stream_id, filename, sock)

    def serve_file(self, stream_id, filename, sock):
        # Validate filename to prevent path traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            self.send_error_response(stream_id, 400, "Invalid filename", sock)
            return
            
        # Construct file path
        file_path = os.path.join(DATA_DIR, filename)
        
        if not os.path.exists(file_path):
            self.send_error_response(stream_id, 404, "File not found", sock)
            return
            
        try:
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Log file access
            client_address = sock.getpeername()
            logging.info(f"Serving file: {filename} ({file_size} bytes) to {client_address[0]}:{client_address[1]}")
            
            # Prepare response headers
            response_headers = [
                (':status', '200'),
                ('content-type', 'application/octet-stream'),
                ('content-length', str(file_size)),
                ('server', 'h2-server/2.0'),
                ('cache-control', 'no-cache'),
                ('x-file-name', filename),
                ('x-transfer-id', str(self.request_count))
            ]
            
            # Send headers
            self.conn.send_headers(stream_id, response_headers)
            sock.sendall(self.conn.data_to_send())
            
            # Update timing data
            self.known_streams[stream_id]['headers_sent_time'] = time.time()
            
            # Read and send file content
            with open(file_path, 'rb') as f:
                # Send file in optimized chunks
                chunk_size = min(16384, self.conn.local_flow_control_window(stream_id))
                bytes_sent = 0
                
                start_time = time.time()
                last_progress_log = start_time
                
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    chunk_len = len(chunk)
                    
                    # If this is the first byte, record time
                    if bytes_sent == 0:
                        self.known_streams[stream_id]['first_byte_time'] = time.time()
                    
                    # Check flow control window
                    while self.conn.local_flow_control_window(stream_id) < chunk_len:
                        # Wait for window update
                        try:
                            data = sock.recv(65535)
                            if not data:
                                raise ConnectionError("Connection closed during file transfer")
                            events = self.conn.receive_data(data)
                            sock.sendall(self.conn.data_to_send())
                        except socket.timeout:
                            # Log if waiting too long for flow control
                            logging.warning(f"Flow control window delay on stream {stream_id}")
                    
                    # Send data chunk
                    self.conn.send_data(stream_id, chunk, end_stream=False)
                    sock.sendall(self.conn.data_to_send())
                    
                    # Update counters
                    bytes_sent += chunk_len
                    self.bytes_sent += chunk_len
                    self.known_streams[stream_id]['bytes_sent'] = bytes_sent
                    
                    # Log progress for large files
                    current_time = time.time()
                    if file_size > 1024*1024 and current_time - last_progress_log > 1.0:
                        progress = (bytes_sent / file_size) * 100
                        elapsed = current_time - start_time
                        throughput = (bytes_sent * 8) / (elapsed * 1000) if elapsed > 0 else 0
                        logging.info(f"Transfer progress: {filename} - {progress:.1f}% - {throughput:.2f} kbps")
                        last_progress_log = current_time
            
            # Update timing data
            self.known_streams[stream_id]['last_byte_time'] = time.time()
            
            # End stream
            self.conn.end_stream(stream_id)
            sock.sendall(self.conn.data_to_send())
            
            # Calculate and log metrics
            transfer_duration = self.known_streams[stream_id]['last_byte_time'] - self.known_streams[stream_id]['first_byte_time']
            throughput_kbps = (file_size * 8) / (transfer_duration * 1000) if transfer_duration > 0 else 0
            
            logging.info(
                f"Completed serving: {filename} ({file_size} bytes) to {client_address[0]}:{client_address[1]} "
                f"in {transfer_duration:.4f}s ({throughput_kbps:.2f} kbps)"
            )
            
        except Exception as e:
            logging.error(f"Error serving file {filename}: {e}", exc_info=True)
            self.send_error_response(stream_id, 500, "Internal Server Error", sock)

    def send_error_response(self, stream_id, status_code, message, sock):
        """Send an error response"""
        error_message = f"Error {status_code}: {message}"
        response_headers = [
            (':status', str(status_code)),
            ('content-type', 'text/plain'),
            ('content-length', str(len(error_message))),
        ]
        
        self.conn.send_headers(stream_id, response_headers)
        self.conn.send_data(stream_id, error_message.encode('utf-8'), end_stream=True)
        sock.sendall(self.conn.data_to_send())
        
        # Log error
        logging.error(f"Error response sent on stream {stream_id}: {status_code} {message}")

    def handle_data_received(self, event, sock):
        stream_id = event.stream_id
        
        # Acknowledge received data to maintain flow control
        self.conn.acknowledge_received_data(event.flow_controlled_length, stream_id)
        sock.sendall(self.conn.data_to_send())

    def handle_stream_ended(self, event, sock):
        stream_id = event.stream_id
        
        # Calculate metrics if available
        if stream_id in self.known_streams:
            stream_data = self.known_streams[stream_id]
            if all(key in stream_data for key in ['start_time', 'headers_sent_time', 'first_byte_time', 'last_byte_time']):
                if None not in [stream_data['start_time'], stream_data['headers_sent_time'], 
                               stream_data['first_byte_time'], stream_data['last_byte_time']]:
                    # Calculate timing metrics
                    setup_time = stream_data['headers_sent_time'] - stream_data['start_time']
                    ttfb = stream_data['first_byte_time'] - stream_data['headers_sent_time']
                    transfer_time = stream_data['last_byte_time'] - stream_data['first_byte_time']
                    total_time = stream_data['last_byte_time'] - stream_data['start_time']
                    
                    logging.info(
                        f"Stream {stream_id} metrics: Setup={setup_time:.4f}s, TTFB={ttfb:.4f}s, "
                        f"Transfer={transfer_time:.4f}s, Total={total_time:.4f}s"
                    )
            
            # Clean up stream data
            del self.known_streams[stream_id]

class H2ClearHandler(socketserver.StreamRequestHandler):
    """Handler for HTTP/2 Cleartext (h2c)"""
    def handle(self):
        try:
            # Check for HTTP/1.1 Upgrade request
            data = self.request.recv(65535)
            
            if b"Upgrade: h2c" in data and b"HTTP2-Settings: " in data:
                # Send 101 Switching Protocols
                upgrade_response = (
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Connection: Upgrade\r\n"
                    b"Upgrade: h2c\r\n"
                    b"\r\n"
                )
                self.request.sendall(upgrade_response)
                
                # Now handle as HTTP/2
                protocol = H2Protocol()
                protocol.handle_request(self.request)
            else:
                # Process directly as HTTP/2 (preface expected)
                protocol = H2Protocol()
                protocol.handle_request(self.request)
        
        except Exception as e:
            logging.error(f"Error in cleartext handler: {e}", exc_info=True)

class HTTP2Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True  # Ensures graceful shutdown

def run_server(host='0.0.0.0', port=8080):
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Check and create test files if they don't exist
    create_test_files = False
    if create_test_files:
        create_sample_files()
    
    # Check and log available files
    if os.path.exists(DATA_DIR):
        files = os.listdir(DATA_DIR)
        file_sizes = {}
        for f in files:
            file_path = os.path.join(DATA_DIR, f)
            if os.path.isfile(file_path):
                file_sizes[f] = os.path.getsize(file_path)
        
        logging.info(f"Available files: {len(files)}")
        for f, size in file_sizes.items():
            logging.info(f"  - {f}: {size} bytes")
    else:
        logging.warning(f"Data directory '{DATA_DIR}' not found")
    
    # Start HTTP/2 server
    server = HTTP2Server((host, port), H2ClearHandler)
    
    protocol_type = "HTTP/2 Cleartext (h2c)"
    logging.info(f"{protocol_type} Server starting on {host}:{port}")
    logging.info(f"System resources at startup - CPU: {psutil.cpu_percent()}%, Memory: {psutil.virtual_memory().percent}%")
    
    print(f"{protocol_type} Server starting on {host}:{port}")
    print(f"Ensure '{DATA_DIR}' directory contains the required test files (A_10kB, B_10kB, etc.)")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logging.info("Server shut down")
        print("Server shut down")


if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='HTTP/2 Server for file transfer experiments')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to bind to')
    
    args = parser.parse_args()
    
    # Run server with the specified options
    run_server(host=args.host, port=args.port)