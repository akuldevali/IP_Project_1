import socketserver
import socket
import ssl
import h2.connection
import h2.config
import h2.events
import time
import os
import logging
import json

# Configure logging
logging.basicConfig(
    filename='http2_server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Define global variables
DATA_DIR = "Data files"

class H2Protocol:
    def __init__(self):
        self.conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=False))
        self.known_streams = {}

    def handle_request(self, sock):
        # First, we need to do handshake
        self.conn.initiate_connection()
        sock.sendall(self.conn.data_to_send())

        # Now we need to process requests from the client
        while True:
            try:
                data = sock.recv(65535)
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
                        return

                # Send any pending data to the client
                data_to_send = self.conn.data_to_send()
                if data_to_send:
                    sock.sendall(data_to_send)
            except (socket.timeout, socket.error) as e:
                logging.error(f"Socket error: {e}")
                break
            except Exception as e:
                logging.error(f"Error handling request: {e}")
                break

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
        
        # Initialize stream data
        self.known_streams[stream_id] = {'headers': headers, 'path': path, 'method': method}
        
        # Process file download request
        if method == 'GET' and path.startswith('/download/'):
            filename = path[10:]  # Remove '/download/' prefix
            self.serve_file(stream_id, filename, sock)

    def serve_file(self, stream_id, filename, sock):
        # Validate filename
        if '..' in filename or '/' in filename:
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
            
            # Send headers
            response_headers = [
                (':status', '200'),
                ('content-type', 'application/octet-stream'),
                ('content-length', str(file_size)),
                ('server', 'h2-server/1.0'),
            ]
            self.conn.send_headers(stream_id, response_headers)
            sock.sendall(self.conn.data_to_send())
            
            # Read and send file content
            with open(file_path, 'rb') as f:
                # Send file in chunks
                chunk_size = 16384  # 16KB chunks
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    # Check flow control window
                    while self.conn.local_flow_control_window(stream_id) < len(chunk):
                        # Wait for window update
                        data = sock.recv(65535)
                        events = self.conn.receive_data(data)
                        sock.sendall(self.conn.data_to_send())
                    
                    # Send data chunk
                    self.conn.send_data(stream_id, chunk, end_stream=False)
                    sock.sendall(self.conn.data_to_send())
            
            # End stream
            self.conn.end_stream(stream_id)
            sock.sendall(self.conn.data_to_send())
            
            # Log completion
            logging.info(f"Completed serving: {filename} to {client_address[0]}:{client_address[1]}")
            
        except Exception as e:
            logging.error(f"Error serving file {filename}: {e}")
            self.send_error_response(stream_id, 500, "Internal Server Error", sock)

    def send_error_response(self, stream_id, status_code, message, sock):
        """Send an error response"""
        response_headers = [
            (':status', str(status_code)),
            ('content-type', 'text/plain'),
            ('content-length', str(len(message))),
        ]
        
        self.conn.send_headers(stream_id, response_headers)
        self.conn.send_data(stream_id, message.encode('utf-8'), end_stream=True)
        sock.sendall(self.conn.data_to_send())

    def handle_data_received(self, event, sock):
        stream_id = event.stream_id
        
        # Acknowledge received data to maintain flow control
        self.conn.acknowledge_received_data(event.flow_controlled_length, stream_id)
        sock.sendall(self.conn.data_to_send())

    def handle_stream_ended(self, event, sock):
        # Clean up stream data when stream ends
        if event.stream_id in self.known_streams:
            del self.known_streams[event.stream_id]

class H2TLSHandler(socketserver.StreamRequestHandler):
    """Handler for HTTP/2 over TLS (h2)"""
    def handle(self):
        try:
            # Wrap socket with SSL
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            
            # Load certificate files if they exist
            cert_file = 'cert.pem'
            key_file = 'key.pem'
            
            if not (os.path.exists(cert_file) and os.path.exists(key_file)):
                logging.error(f"SSL certificate files not found: {cert_file} and/or {key_file}")
                print(f"Error: SSL certificate files not found: {cert_file} and/or {key_file}")
                return
                
            context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            
            conn = context.wrap_socket(
                self.request,
                server_side=True,
            )
            
            # Process HTTP/2 requests
            protocol = H2Protocol()
            protocol.handle_request(conn)
        
        except Exception as e:
            logging.error(f"Error in TLS handler: {e}")

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
            logging.error(f"Error in cleartext handler: {e}")

class HTTP2Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

def run_server(host='0.0.0.0', port=8443, use_ssl=True):
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Check and log available files
    if os.path.exists(DATA_DIR):
        files = os.listdir(DATA_DIR)
        logging.info(f"Available files: {', '.join(files)}")
    else:
        logging.warning(f"Data directory '{DATA_DIR}' not found")
    
    # Select the appropriate handler based on SSL preference
    handler = H2TLSHandler if use_ssl else H2ClearHandler
    
    # Start HTTP/2 server
    server = HTTP2Server((host, port), handler)
    
    protocol_type = "HTTP/2 over TLS (h2)" if use_ssl else "HTTP/2 Cleartext (h2c)"
    logging.info(f"{protocol_type} Server starting on {host}:{port}")
    print(f"{protocol_type} Server starting on {host}:{port}")
    print(f"Ensure '{DATA_DIR}' directory contains the required test files (A_10kB, B_10kB, etc.)")
    
    if use_ssl:
        print("Using SSL - make sure cert.pem and key.pem files exist")
    
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
    parser.add_argument('--port', type=int, default=8443, help='Port to bind to')
    parser.add_argument('--no-ssl', action='store_true', help='Use HTTP/2 Cleartext (h2c) without SSL')
    
    args = parser.parse_args()
    
    # Run server with the specified options
    run_server(host=args.host, port=args.port, use_ssl=not args.no_ssl)