import socket
import h2.connection
import h2.config
import h2.events
import h2.settings
from statistics import mean, stdev
import time
import os
import json
import ssl
import argparse

class HTTP2Client:
    """HTTP/2 Client for file transfer experiments"""

    def __init__(self, server, port, use_ssl=True):
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.socket = None
        self.connection = None

    def open_connection(self):
        """Open a connection to the server with HTTP/2 protocol"""
        # Set a reasonable timeout
        socket.setdefaulttimeout(15)

        # Create a socket
        sock = socket.create_connection((self.server, self.port))
        
        # Set larger buffer sizes for better performance
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)  # 1MB receive buffer
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)  # 1MB send buffer
        
        if self.use_ssl:
            # Configure SSL context
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            context.set_alpn_protocols(['h2'])
            
            # Wrap socket with SSL
            self.socket = context.wrap_socket(sock, server_hostname=self.server)
            
            # Initialize HTTP/2 connection (TLS mode)
            self.connection = h2.connection.H2Connection()
        else:
            # For h2c (HTTP/2 without SSL), we need to start with an HTTP/1.1 request
            # containing the Upgrade header
            self.socket = sock
            
            # Send the initial HTTP/1.1 request with Upgrade header
            upgrade_request = (
                b"GET / HTTP/1.1\r\n"
                b"Host: " + self.server.encode('utf-8') + b"\r\n"
                b"User-Agent: h2c-client/1.0\r\n"
                b"Connection: Upgrade, HTTP2-Settings\r\n"
                b"Upgrade: h2c\r\n"
                b"HTTP2-Settings: AAMAAABkAAQAAP__\r\n"  # Base64 encoded empty settings frame
                b"\r\n"
            )
            self.socket.sendall(upgrade_request)
            
            # Read the HTTP/1.1 response
            response = b""
            while b"\r\n\r\n" not in response:
                data = self.socket.recv(65535)
                if not data:
                    raise ConnectionError("Server closed connection without upgrading to HTTP/2")
                response += data
            
            # Check if the server agreed to upgrade
            if b"101 Switching Protocols" in response and b"Upgrade: h2c" in response:
                # Initialize HTTP/2 connection (cleartext mode)
                self.connection = h2.connection.H2Connection()
            else:
                raise ConnectionError("Server did not agree to upgrade to HTTP/2. Response: " + 
                                     response.decode('utf-8', errors='ignore'))
        
        # Initialize connection and settings
        self.connection.initiate_connection()
        
        # Update local settings to allow more streams
        self.connection.update_settings({
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 10000
        })
        
        # Send connection preface and settings
        self.socket.sendall(self.connection.data_to_send())

    def download_file(self, filename, repetitions):
        """
        Download a file from the server multiple times and collect metrics
        
        Args:
            filename: Name of the file to download
            repetitions: Number of times to repeat the download
            
        Returns:
            Dictionary with throughput and overhead metrics
        """
        throughputs_kbps = []
        overhead_ratios = []
        transfer_times = []
        
        print(f"Starting {repetitions} transfers of {filename}...")
        
        for i in range(repetitions):
            # Request start time
            start_time = time.time()
            
            # Send request headers
            headers = [
                (b':method', b'GET'),
                (b':scheme', b'https' if self.use_ssl else b'http'),
                (b':authority', self.server.encode()),
                (b':path', f'/download/{filename}'.encode()),
                (b'user-agent', b'http2-client/1.0'),
                (b'accept', b'*/*'),
            ]
            
            # Get a new stream ID
            stream_id = self.connection.get_next_available_stream_id()
            
            # Send headers
            self.connection.send_headers(stream_id, headers)
            self.socket.sendall(self.connection.data_to_send())
            
            # Variables to track response
            response_headers = {}
            response_data = b''
            stream_ended = False
            header_bytes = 0  # Size of response headers in bytes
            
            # Process response
            while not stream_ended:
                # Receive data from socket
                data = self.socket.recv(65536)
                if not data:
                    break
                
                # Pass received data to the H2 connection
                events = self.connection.receive_data(data)
                
                for event in events:
                    if isinstance(event, h2.events.ResponseReceived):                        
                        # Extract and record header information
                        for header in event.headers:
                            name, value = header
                            response_headers[name] = value
                            # Calculate header size (approximate)
                            header_bytes += len(name) + len(value)
                            
                    elif isinstance(event, h2.events.DataReceived):
                        # Collect response body data
                        response_data += event.data
                        
                        # Acknowledge received data to maintain flow control
                        self.connection.acknowledge_received_data(
                            event.flow_controlled_length, 
                            event.stream_id
                        )
                        
                    elif isinstance(event, h2.events.StreamEnded):
                        stream_ended = True
                        break
                
                # Send any pending data (like WINDOW_UPDATE frames)
                self.socket.sendall(self.connection.data_to_send())
            
            # Calculate end time and transfer time
            end_time = time.time()
            transfer_time = end_time - start_time
            
            # Calculate file size
            file_size_bytes = len(response_data)
            
            # Add HTTP/2 framing overhead (9 bytes per frame)
            # Assuming ~16KB frames for data
            frame_count = (file_size_bytes // 16384) + 1
            framing_overhead = frame_count * 9
            
            # Calculate total application layer data transferred
            total_data_transferred = header_bytes + file_size_bytes + framing_overhead
            
            # Calculate overhead ratio
            overhead_ratio = total_data_transferred / file_size_bytes if file_size_bytes > 0 else 0
            
            # Calculate throughput in kilobits per second based on total transfer time
            if transfer_time > 0 and file_size_bytes > 0:
                throughput_bps = file_size_bytes / transfer_time
                throughput_kbps = (throughput_bps * 8) / 1000
            else:
                throughput_kbps = 0
                
            # Store metrics
            throughputs_kbps.append(throughput_kbps)
            overhead_ratios.append(overhead_ratio)
            transfer_times.append(transfer_time)
            
            # Show progress
            if repetitions > 10 and (i + 1) % (repetitions // 10) == 0:
                print(f"Progress: {i + 1}/{repetitions} transfers ({(i + 1)/repetitions*100:.1f}%)")
            
        # Calculate statistics
        avg_throughput = mean(throughputs_kbps) if throughputs_kbps else 0
        avg_overhead = mean(overhead_ratios) if overhead_ratios else 0
        avg_transfer_time = mean(transfer_times) if transfer_times else 0
        
        # Calculate standard deviation if we have more than one sample
        if len(throughputs_kbps) > 1:
            std_dev_throughput = stdev(throughputs_kbps)
            std_dev_overhead = stdev(overhead_ratios)
            std_dev_transfer_time = stdev(transfer_times)
        else:
            std_dev_throughput = 0
            std_dev_overhead = 0
            std_dev_transfer_time = 0
            
        return {
            "avg_throughput_kbps": avg_throughput,
            "std_dev_kbps": std_dev_throughput,
            "avg_overhead_ratio": avg_overhead,
            "std_dev_overhead": std_dev_overhead,
            "avg_transfer_time_s": avg_transfer_time,
            "std_dev_transfer_time_s": std_dev_transfer_time,
            "transfer_count": repetitions
        }

    def close_connection(self):
        """Close the HTTP/2 connection properly"""
        if self.connection and self.socket:
            # Send GOAWAY frame to notify server
            self.connection.close_connection()
            self.socket.sendall(self.connection.data_to_send())
            self.socket.close()
            self.socket = None
            self.connection = None

def run_experiments(server_ip, server_port, file_prefix, use_ssl=False):
    """Run all the required experiments and collect results"""
    
    # Define experiment parameters
    experiments = [
        {"file_size": "10kB", "repetitions": 1000},
        {"file_size": "100kB", "repetitions": 100},
        {"file_size": "1MB", "repetitions": 10},
        {"file_size": "10MB", "repetitions": 1}
    ]
    
    results = {}
    
    # Connect to server
    print(f"\nConnecting to server ({server_ip}:{server_port})...")
    client = HTTP2Client(server_ip, server_port, use_ssl)
    client.open_connection()
    
    try:
        # Run experiments for all file sizes
        for exp in experiments:
            file_size = exp["file_size"]
            repetitions = exp["repetitions"]
            filename = f"{file_prefix}_{file_size}"
            
            print(f"\nRunning experiment: {repetitions} transfers of {filename}")
            result = client.download_file(filename, repetitions)
            
            # Store results
            results[filename] = result
    finally:
        # Always close the connection, even if there's an error
        client.close_connection()
    
    # Save results to a JSON file
    results_filename = f"http2_{file_prefix}_results.json"
    with open(results_filename, "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary to console
    print(f"\nHTTP/2 Results Summary (saved to {results_filename}):")
    print("-------------------------------------------------------------------------")
    print("File Size | Avg Throughput (kbps) | Std Dev | Overhead Ratio | Transfer Time")
    print("-------------------------------------------------------------------------")
    for filename, data in results.items():
        print(f"{filename:8} | {data['avg_throughput_kbps']:20.2f} | {data['std_dev_kbps']:7.2f} | " +
              f"{data['avg_overhead_ratio']:14.4f} | {data['avg_transfer_time_s']:12.4f}s")
    print("-------------------------------------------------------------------------")
    
    return results

if __name__ == "__main__":
    # Configure your server details here - CHANGE THESE VALUES AS NEEDED
    SERVER_IP = "127.0.0.1"  # Server IP address
    SERVER_PORT = 8080       # Server port
    FILE_PREFIX = "A"        # A or B depending on which files you're downloading
    USE_SSL = False          # Set to True if using HTTPS
    
    # Parse command line arguments only if you want to override the defaults
    import argparse
    
    parser = argparse.ArgumentParser(description='HTTP/2 Client for file transfer experiments')
    parser.add_argument('--ssl', action='store_true', help='Use SSL/TLS (HTTPS)')
    parser.add_argument('--prefix', choices=['A', 'B'], help='File prefix (A or B)')
    
    args = parser.parse_args()
    
    # Override settings if specified in command line
    if args.ssl:
        USE_SSL = True
    if args.prefix:
        FILE_PREFIX = args.prefix
    
    # Run experiments with the configured settings
    run_experiments(SERVER_IP, SERVER_PORT, FILE_PREFIX, USE_SSL)