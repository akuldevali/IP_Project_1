# HTTP Protocol Performance Testing Framework

This framework provides tools for testing and comparing the performance of HTTP/1.1 and HTTP/2 protocols. It includes client and server implementations for both protocols, designed to measure throughput, latency, and protocol overhead across different file sizes.

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Directory Structure](#directory-structure)
4. [Creating Test Files](#creating-test-files)
5. [HTTP/1.1 Implementation](#http11-implementation)
   - [Server Setup](#http11-server-setup)
   - [Client Setup](#http11-client-setup)
6. [HTTP/2 Implementation](#http2-implementation)
   - [Server Setup](#http2-server-setup)
   - [Client Setup](#http2-client-setup)
7. [Running Tests](#running-tests)
8. [Understanding Results](#understanding-results)
9. [Troubleshooting](#troubleshooting)

## Requirements

### For HTTP/1.1:
- Python 3.6+
- Flask (`pip install flask`)
- Requests (`pip install requests`)
- Werkzeug (`pip install werkzeug`)
- Statistics module (part of Python standard library)

### For HTTP/2:
- Python 3.6+
- h2 (`pip install h2`)
- socket (part of Python standard library)
- Statistics module (part of Python standard library)
- psutil (`pip install psutil`)

## Installation

1. Clone or download this repository
2. Install the required dependencies:

```bash
# For HTTP/1.1 implementation
pip install flask requests werkzeug

# For HTTP/2 implementation
pip install h2 psutil
```

## Directory Structure

Create the following directory structure:

```
http-testing/
├── http1/
│   ├── http1_server.py
│   ├── http1_client.py
│   ├── Data files/     # Test files for HTTP/1.1
│   └── http1_server.log # Generated when running
├── http2/
│   ├── server.py
│   ├── client.py
│   ├── Data files/     # Test files for HTTP/2
│   └── http2_server.log # Generated when running
└── README.md
```

## Creating Test Files

Create test files of specific sizes in both the `http1/Data files/` and `http2/Data files/` directories:

```bash
# For Linux/macOS:
mkdir -p "http1/Data files" "http2/Data files"
cd "http1/Data files"
dd if=/dev/zero of=A_10kB bs=1024 count=10
dd if=/dev/zero of=A_100kB bs=1024 count=100
dd if=/dev/zero of=A_1MB bs=1MB count=1
dd if=/dev/zero of=A_10MB bs=1MB count=10

# Copy to HTTP/2 directory
cp A_* "../../http2/Data files/"

# For Windows PowerShell:
New-Item -ItemType Directory -Force -Path "http1\Data files"
New-Item -ItemType Directory -Force -Path "http2\Data files"
cd "http1\Data files"
fsutil file createnew A_10kB 10240
fsutil file createnew A_100kB 102400
fsutil file createnew A_1MB 1048576
fsutil file createnew A_10MB 10485760

# Copy to HTTP/2 directory
copy A_* "..\..\http2\Data files\"
```

Optional: Create additional B_* test files following the same pattern if you want to test transfers from a second server.

## HTTP/1.1 Implementation

### HTTP/1.1 Server Setup

1. Navigate to the HTTP/1.1 directory:
   ```bash
   cd http1
   ```

2. Configure the server:
   - The server is configured to listen on 0.0.0.0:8080 (all interfaces)
   - Files are served from the "Data files" directory

3. Start the server:
   ```bash
   python http1_server.py
   ```

   You should see output confirming the server is running and listing available files.

### HTTP/1.1 Client Setup

1. Edit the `http1_client.py` file to update the server IP address:
   ```python
   # Define server URLs - update with your actual server IPs
   computer1_url = 'http://YOUR_SERVER_IP:8080'  # Replace with your server's IP
   ```

2. Run the client:
   ```bash
   python http1_client.py
   ```

The client will:
- Download files of different sizes (10kB, 100kB, 1MB, 10MB)
- Perform multiple transfer repetitions (1000, 100, 10, 1 respectively)
- Calculate throughput, latency, and overhead metrics
- Save results to `http1_1_throughput_results.json`

## HTTP/2 Implementation

### HTTP/2 Server Setup

1. Navigate to the HTTP/2 directory:
   ```bash
   cd http2
   ```

2. Configure the server (optional):
   - The server is configured to listen on 0.0.0.0:8080 by default
   - You can specify a different host or port using command-line arguments

3. Start the server:
   ```bash
   python server.py
   ```

   To use specific host/port:
   ```bash
   python server.py --host 192.168.1.100 --port 8443
   ```

### HTTP/2 Client Setup

1. Run the client with your server's IP and port:
   ```bash
   python client.py --server YOUR_SERVER_IP --port 8080
   ```

2. For testing a single file:
   ```bash
   python client.py --server YOUR_SERVER_IP --port 8080 --file A_1MB --repeats 5
   ```

3. For testing with two servers:
   ```bash
   python client.py --server SERVER1_IP --port 8080 --server2 SERVER2_IP --port2 8080
   ```

The client will run similar experiments to HTTP/1.1, saving results to `http2_results.json`.

## Running Tests

For a fair comparison between HTTP/1.1 and HTTP/2:

1. Run the tests on the same network setup
2. Test both protocols with the same file sizes
3. Run the tests at similar times to ensure network conditions are comparable
4. Use multiple test runs to reduce the effect of random network fluctuations

### Complete Test Sequence

1. Start the HTTP/1.1 server on one computer
2. Run the HTTP/1.1 client from another computer
3. Shut down the HTTP/1.1 server
4. Start the HTTP/2 server
5. Run the HTTP/2 client
6. Compare the results from both tests

## Understanding Results

Both implementations generate JSON result files that include:

- **Average Throughput**: Data transfer rate in kilobits per second (kbps)
- **Standard Deviation**: Variation in throughput across multiple transfers
- **Overhead Ratio**: The ratio of total transferred data to file size (headers and protocol overhead)
- **Transfer Count**: Number of transfers performed

Compare the results to see the performance differences between HTTP/1.1 and HTTP/2 across different file sizes.

### Expected Performance Differences

- HTTP/2 typically shows better performance for small files due to:
  - Multiplexing capabilities
  - Header compression
  - Binary protocol format instead of text-based
- HTTP/1.1 may perform similarly for large files where protocol overhead is less significant
- HTTP/2 should show better performance when downloading multiple files simultaneously

## Troubleshooting

### Common Issues:

1. **Connection Refused**:
   - Ensure the server is running
   - Check if the IP address and port are correctly configured
   - Verify firewall settings allow traffic on the specified port

2. **Slow Performance**:
   - Check network conditions
   - Verify no other bandwidth-intensive applications are running
   - Try running tests during periods of low network usage

3. **Server Crashes**:
   - Check log files for error messages
   - Ensure all dependencies are installed
   - Verify sufficient system resources (memory, CPU)

4. **File Not Found Errors**:
   - Ensure test files are created in the correct directories
   - Check file permissions
   - Verify filenames match exactly what the client is requesting

### Logging

- Both servers generate log files (`http1_server.log` and `http2_server.log`)
- Examine these logs for detailed information about transfers and errors
- The HTTP/2 implementation provides more detailed metrics in its logs