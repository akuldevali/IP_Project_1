import socket
import h2.connection
import h2.config
import h2.events
import h2.settings
from statistics import mean, stdev
import time
import os
import json
import argparse

class HTTP2Client:
    """Simplified HTTP/2 Client for file transfer experiments"""

    def __init__(self, server, port):
        self.server = server
        self.port = port
        self.socket = None
        self.connection = None
        self.settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 10000,
            h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 1048576  # 1MB window
        }
        
    def open_connection(self):
        """Open a connection to the server with HTTP/2 protocol (cleartext)"""
        # Set a reasonable timeout
        socket.setdefaulttimeout(15)

        # Create a socket
        sock = socket.create_connection((self.server, self.port))
        
        # TCP optimization
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Set larger buffer sizes for better performance
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)  # 1MB receive buffer
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)  # 1MB send buffer
        
        # For h2c (HTTP/2 without SSL), we start with an HTTP/1.1 request
        self.socket = sock
        
        # Send the initial HTTP/1.1 request with Upgrade header
        upgrade_request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: " + self.server.encode('utf-8') + b"\r\n"
            b"User-Agent: h2c-client/2.0\r\n"
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
            # If server doesn't support upgrade, try direct HTTP/2 connection
            self.socket.close()
            sock = socket.create_connection((self.server, self.port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            self.socket = sock
            self.connection = h2.connection.H2Connection()
        
        # Initialize connection and settings
        self.connection.initiate_connection()
        
        # Update local settings with our optimized parameters
        self.connection.update_settings(self.settings)
        
        # Send connection preface and settings
        self.socket.sendall(self.connection.data_to_send())

    def download_file(self, filename, repetitions=1):
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
        
        print(f"Starting {repetitions} transfers of {filename}...")
        
        for i in range(repetitions):
            # Request start time
            start_time = time.time()
            
            # Send request headers
            headers = [
                (b':method', b'GET'),
                (b':scheme', b'http'),
                (b':authority', self.server.encode()),
                (b':path', f'/download/{filename}'.encode()),
                (b'user-agent', b'http2-client/2.0'),
                (b'accept', b'*/*'),
            ]
            
            # Get a new stream ID
            stream_id = self.connection.get_next_available_stream_id()
            
            # Send headers
            self.connection.send_headers(stream_id, headers)
            self.socket.sendall(self.connection.data_to_send())
            
            # Variables to track response
            response_headers = {}
            response_data = bytearray()  # More efficient for appending data
            stream_ended = False
            header_bytes = 0  # Size of response headers in bytes
            
            # Timing variables
            first_byte_time = None
            last_byte_time = None
            
            # Process response
            while not stream_ended:
                # Receive data from socket
                try:
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
                                name_str = name.decode('utf-8') if isinstance(name, bytes) else name
                                value_str = value.decode('utf-8') if isinstance(value, bytes) else value
                                response_headers[name_str] = value_str
                                # Calculate header size (approximate)
                                header_bytes += len(name) + len(value)
                                
                        elif isinstance(event, h2.events.DataReceived):
                            # Record first byte time
                            if first_byte_time is None and event.data:
                                first_byte_time = time.time()
                            
                            # Collect response body data
                            response_data.extend(event.data)
                            
                            # Update last byte time
                            if event.data:
                                last_byte_time = time.time()
                            
                            # Acknowledge received data to maintain flow control
                            self.connection.acknowledge_received_data(
                                event.flow_controlled_length, 
                                event.stream_id
                            )
                            
                        elif isinstance(event, h2.events.StreamEnded):
                            stream_ended = True
                            # If we never got data, set times
                            if last_byte_time is None:
                                last_byte_time = time.time()
                            if first_byte_time is None:
                                first_byte_time = last_byte_time
                            break
                    
                    # Send any pending data (like WINDOW_UPDATE frames)
                    self.socket.sendall(self.connection.data_to_send())
                    
                except socket.timeout:
                    print(f"Socket timeout on transfer {i} of {filename}")
                    break
                except Exception as e:
                    print(f"Error during transfer {i} of {filename}: {e}")
                    break
            
            # Ensure we have valid timing data
            if first_byte_time is None:
                first_byte_time = time.time()
            if last_byte_time is None:
                last_byte_time = time.time()
            
            # Calculate transfer time
            transfer_time = last_byte_time - first_byte_time
            
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
            
            # Calculate throughput in kilobits per second based on transfer time
            if transfer_time > 0:
                throughput_bps = file_size_bytes / transfer_time
                throughput_kbps = (throughput_bps * 8) / 1000
            else:
                throughput_kbps = 0
                
            # Store metrics
            throughputs_kbps.append(throughput_kbps)
            overhead_ratios.append(overhead_ratio)
            
            # Show progress
            if repetitions > 10 and (i + 1) % (repetitions // 10) == 0:
                print(f"Progress: {i + 1}/{repetitions} transfers ({(i + 1)/repetitions*100:.1f}%)")
            
        # Calculate statistics
        avg_throughput = mean(throughputs_kbps) if throughputs_kbps else 0
        avg_overhead = mean(overhead_ratios) if overhead_ratios else 0
        
        # Calculate standard deviation if we have more than one sample
        std_dev_throughput = stdev(throughputs_kbps) if len(throughputs_kbps) > 1 else 0
            
        return {
            "avg_throughput_kbps": avg_throughput,
            "std_dev_kbps": std_dev_throughput,
            "avg_overhead_ratio": avg_overhead,
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

def run_experiments(computer1_ip, computer1_port, computer2_ip=None, computer2_port=None):
    """Run all the required experiments and collect results"""
    
    # Define basic experiment parameters
    experiments = [
        {"file_size": "10kB", "repetitions": 1000},
        {"file_size": "100kB", "repetitions": 100},
        {"file_size": "1MB", "repetitions": 10},
        {"file_size": "10MB", "repetitions": 1}
    ]
    
    results = {}
    
    # Experiment for Computer 1 (A files)
    print(f"\nConnecting to Computer 1 ({computer1_ip}:{computer1_port})...")
    client1 = HTTP2Client(computer1_ip, computer1_port)
    client1.open_connection()
    
    try:
        # Run basic file transfer experiments
        for exp in experiments:
            file_size = exp["file_size"]
            repetitions = exp["repetitions"]
            filename = f"A_{file_size}"
            
            print(f"\nRunning experiment: {repetitions} transfers of {filename}")
            result = client1.download_file(filename, repetitions)
            
            # Store results
            results[filename] = result
    
    finally:
        client1.close_connection()
    
    # Run experiments for Computer 2 if specified
    if computer2_ip and computer2_port:
        print(f"\nConnecting to Computer 2 ({computer2_ip}:{computer2_port})...")
        client2 = HTTP2Client(computer2_ip, computer2_port)
        client2.open_connection()
        
        try:
            for exp in experiments:
                file_size = exp["file_size"]
                repetitions = exp["repetitions"]
                filename = f"B_{file_size}"
                
                print(f"\nRunning experiment: {repetitions} transfers of {filename}")
                result = client2.download_file(filename, repetitions)
                
                # Store results
                results[filename] = result
        finally:
            client2.close_connection()
    
    # Save results to a JSON file
    with open("http2_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to http2_results.json")
    
    # Print summary to console
    print("\nHTTP/2 Results Summary:")
    print("----------------------------------------------------------------------------")
    print("File Size | Avg Throughput (kbps) | Std Dev (kbps) | Overhead Ratio | Count")
    print("----------------------------------------------------------------------------")
    for filename, data in results.items():
        if isinstance(data, dict) and "avg_throughput_kbps" in data:
            print(f"{filename:8} | {data['avg_throughput_kbps']:20.2f} | {data['std_dev_kbps']:13.2f} | " +
                  f"{data['avg_overhead_ratio']:14.4f} | {data['transfer_count']:5d}")
    print("----------------------------------------------------------------------------")

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='HTTP/2 Client for file transfer experiments')
    parser.add_argument('--server', default='127.0.0.1', help='Server IP address')
    parser.add_argument('--port', type=int, default=8080, help='Server port')
    parser.add_argument('--server2', help='Second server IP address (optional)')
    parser.add_argument('--port2', type=int, help='Second server port (optional)')
    parser.add_argument('--file', help='Single file to download (skips full experiment)')
    parser.add_argument('--repeats', type=int, default=1, help='Number of repeats for single file download')
    
    args = parser.parse_args()
    
    # Check if we're doing a single file download or full experiment
    if args.file:
        client = HTTP2Client(args.server, args.port)
        client.open_connection()
        
        try:
            result = client.download_file(args.file, args.repeats)
            print("\nDownload Results:")
            print(f"File: {args.file}")
            print(f"Average throughput: {result['avg_throughput_kbps']:.2f} kbps")
            print(f"Standard deviation: {result['std_dev_kbps']:.2f} kbps")
            print(f"Average overhead ratio: {result['avg_overhead_ratio']:.8f}")
            print(f"Transfer count: {result['transfer_count']}")
        finally:
            client.close_connection()
    else:
        # Run full experiments
        run_experiments(
            args.server, 
            args.port,
            args.server2,
            args.port2
        )