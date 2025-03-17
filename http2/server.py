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

logging.basicConfig(
    filename='http2_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DATA_DIR = "Data files"
BUFFER_SIZE = 1048576

class H2Protocol:
    def __init__(self):
        config = h2.config.H2Configuration(client_side=False)
        self.conn = h2.connection.H2Connection(config=config)
        self.known_streams = {}
        
        self.settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 10000,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: BUFFER_SIZE,
            h2.settings.SettingCodes.HEADER_TABLE_SIZE: 65536,
            h2.settings.SettingCodes.ENABLE_PUSH: 0
        }
        
        self.request_count = 0
        self.bytes_sent = 0
        self.active_connections = 0

    def handle_request(self, sock):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        self.conn.initiate_connection()
        
        self.conn.update_settings(self.settings)
        
        sock.sendall(self.conn.data_to_send())
        
        connection_start = time.time()
        self.active_connections += 1

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
            connection_duration = time.time() - connection_start
            logging.info(f"Connection closed. Duration: {connection_duration:.2f}s, Bytes sent: {self.bytes_sent}")
            
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            logging.info(f"System resources - CPU: {cpu_percent}%, Memory: {memory_percent}%")

    def handle_request_received(self, event, sock):
        stream_id = event.stream_id
        headers = dict(event.headers)
        
        headers = {k.decode('utf-8'): v.decode('utf-8') for k, v in headers.items()}
        
        path = headers.get(':path', '')
        method = headers.get(':method', '')
        
        client_address = sock.getpeername()
        logging.info(f"Request from {client_address[0]}:{client_address[1]} - {method} {path}")
        
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
        
        if method == 'GET' and path.startswith('/download/'):
            filename = path[10:]
            self.serve_file(stream_id, filename, sock)

    def serve_file(self, stream_id, filename, sock):
        if '..' in filename or '/' in filename or '\\' in filename:
            self.send_error_response(stream_id, 400, "Invalid filename", sock)
            return
            
        file_path = os.path.join(DATA_DIR, filename)
        
        if not os.path.exists(file_path):
            self.send_error_response(stream_id, 404, "File not found", sock)
            return
            
        try:
            file_size = os.path.getsize(file_path)
            
            client_address = sock.getpeername()
            logging.info(f"Serving file: {filename} ({file_size} bytes) to {client_address[0]}:{client_address[1]}")
            
            response_headers = [
                (':status', '200'),
                ('content-type', 'application/octet-stream'),
                ('content-length', str(file_size)),
                ('server', 'h2-server/2.0'),
                ('cache-control', 'no-cache'),
                ('x-file-name', filename),
                ('x-transfer-id', str(self.request_count))
            ]
            
            self.conn.send_headers(stream_id, response_headers)
            sock.sendall(self.conn.data_to_send())
            
            self.known_streams[stream_id]['headers_sent_time'] = time.time()
            
            with open(file_path, 'rb') as f:
                chunk_size = min(16384, self.conn.local_flow_control_window(stream_id))
                bytes_sent = 0
                
                start_time = time.time()
                last_progress_log = start_time
                
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    chunk_len = len(chunk)
                    
                    if bytes_sent == 0:
                        self.known_streams[stream_id]['first_byte_time'] = time.time()
                    
                    while self.conn.local_flow_control_window(stream_id) < chunk_len:
                        try:
                            data = sock.recv(65535)
                            if not data:
                                raise ConnectionError("Connection closed during file transfer")
                            events = self.conn.receive_data(data)
                            sock.sendall(self.conn.data_to_send())
                        except socket.timeout:
                            logging.warning(f"Flow control window delay on stream {stream_id}")
                    
                    self.conn.send_data(stream_id, chunk, end_stream=False)
                    sock.sendall(self.conn.data_to_send())
                    
                    bytes_sent += chunk_len
                    self.bytes_sent += chunk_len
                    self.known_streams[stream_id]['bytes_sent'] = bytes_sent
                    
                    current_time = time.time()
                    if file_size > 1024*1024 and current_time - last_progress_log > 1.0:
                        progress = (bytes_sent / file_size) * 100
                        elapsed = current_time - start_time
                        throughput = (bytes_sent * 8) / (elapsed * 1000) if elapsed > 0 else 0
                        logging.info(f"Transfer progress: {filename} - {progress:.1f}% - {throughput:.2f} kbps")
                        last_progress_log = current_time
            
            self.known_streams[stream_id]['last_byte_time'] = time.time()
            
            self.conn.end_stream(stream_id)
            sock.sendall(self.conn.data_to_send())
            
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
        error_message = f"Error {status_code}: {message}"
        response_headers = [
            (':status', str(status_code)),
            ('content-type', 'text/plain'),
            ('content-length', str(len(error_message))),
        ]
        
        self.conn.send_headers(stream_id, response_headers)
        self.conn.send_data(stream_id, error_message.encode('utf-8'), end_stream=True)
        sock.sendall(self.conn.data_to_send())
        
        logging.error(f"Error response sent on stream {stream_id}: {status_code} {message}")

    def handle_data_received(self, event, sock):
        stream_id = event.stream_id
        
        self.conn.acknowledge_received_data(event.flow_controlled_length, stream_id)
        sock.sendall(self.conn.data_to_send())

    def handle_stream_ended(self, event, sock):
        stream_id = event.stream_id
        
        if stream_id in self.known_streams:
            stream_data = self.known_streams[stream_id]
            if all(key in stream_data for key in ['start_time', 'headers_sent_time', 'first_byte_time', 'last_byte_time']):
                if None not in [stream_data['start_time'], stream_data['headers_sent_time'], 
                               stream_data['first_byte_time'], stream_data['last_byte_time']]:
                    setup_time = stream_data['headers_sent_time'] - stream_data['start_time']
                    ttfb = stream_data['first_byte_time'] - stream_data['headers_sent_time']
                    transfer_time = stream_data['last_byte_time'] - stream_data['first_byte_time']
                    total_time = stream_data['last_byte_time'] - stream_data['start_time']
                    
                    logging.info(
                        f"Stream {stream_id} metrics: Setup={setup_time:.4f}s, TTFB={ttfb:.4f}s, "
                        f"Transfer={transfer_time:.4f}s, Total={total_time:.4f}s"
                    )
            
            del self.known_streams[stream_id]

class H2ClearHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            data = self.request.recv(65535)
            
            if b"Upgrade: h2c" in data and b"HTTP2-Settings: " in data:
                upgrade_response = (
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Connection: Upgrade\r\n"
                    b"Upgrade: h2c\r\n"
                    b"\r\n"
                )
                self.request.sendall(upgrade_response)
                
                protocol = H2Protocol()
                protocol.handle_request(self.request)
            else:
                protocol = H2Protocol()
                protocol.handle_request(self.request)
        
        except Exception as e:
            logging.error(f"Error in cleartext handler: {e}", exc_info=True)

class HTTP2Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def run_server(host='0.0.0.0', port=8080):
    os.makedirs(DATA_DIR, exist_ok=True)
    
    create_test_files = False
    if create_test_files:
        create_sample_files()
    
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
    
    parser = argparse.ArgumentParser(description='HTTP/2 Server for file transfer experiments')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to bind to')
    
    args = parser.parse_args()
    
    run_server(host=args.host, port=args.port)