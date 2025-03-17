# Network Protocols Performance Testing Framework

This framework provides tools for testing and comparing the performance of different network protocols: HTTP/1.1, HTTP/2, and BitTorrent. It includes client and server implementations for all three protocols, designed to measure throughput, latency, and protocol overhead across different file sizes.

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Directory Structure](#directory-structure)
4. [HTTP/1.1 Implementation](#http11-implementation)
5. [HTTP/2 Implementation](#http2-implementation)
6. [BitTorrent Implementation](#bittorrent-implementation)
7. [Running Comprehensive Tests](#running-comprehensive-tests)
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

### For BitTorrent:
- Python 3.6+
- libtorrent (`pip install python-libtorrent` or platform-specific installation)
- Statistics module (part of Python standard library)
- argparse (part of Python standard library)

## Installation

### Basic Setup

1. Clone or download this repository
2. Install the required dependencies:

```bash
# Common requirements
pip install statistics

# For HTTP/1.1 implementation
pip install flask requests werkzeug

# For HTTP/2 implementation
pip install h2 psutil

# For BitTorrent implementation
# Note: libtorrent installation can be platform-specific
# On Ubuntu/Debian:
sudo apt-get install python3-libtorrent

# On macOS (with Homebrew):
brew install libtorrent-rasterbar
pip install python-libtorrent

# On Windows:
# Download appropriate binaries or use Anaconda:
conda install -c conda-forge libtorrent
```

## Directory Structure

The repository has the following directory structure:

```
network-testing/
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
├── bitTorrent/
│   ├── seeder.py
│   ├── leecher.py
│   └── torrents/       # Directory for .torrent files
└── README.md
```

## HTTP/1.1 Implementation

### HTTP/1.1 Server Setup

1. Navigate to the HTTP/1.1 directory:
   ```bash
   cd http1
   ```

2. Start the server:
   ```bash
   python http1_server.py
   ```

   The server will:
   - Listen on 0.0.0.0:8080 (all interfaces)
   - Serve files from the "Data files" directory
   - Log activity to http1_server.log

### HTTP/1.1 Client Setup

1. **IMPORTANT**: You must manually edit the `http1_client.py` file to set the correct server IP address:
   ```python
   # Define server URLs - update with your actual server IPs
   computer1_url = 'http://YOUR_SERVER_IP:8080'  # Replace with Computer A's IP
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

2. Start the server:
   ```bash
   python server.py --host 192.168.1.100 --port 8443
   ```

   The server will:
   - Listen on the specified interface (default: 0.0.0.0:8080)
   - Serve files from the "Data files" directory
   - Log activity to http2_server.log

### HTTP/2 Client Setup

1. **IMPORTANT**: Run the client specifying the server's IP address and port:
   ```bash
   python client.py --server YOUR_SERVER_IP --port 8080
   ```

2. For testing a single file:
   ```bash
   python client.py --server YOUR_SERVER_IP --port 8080 --file A_1MB --repeats 5
   ```

## BitTorrent Implementation

BitTorrent testing requires two components: a seeder (server) and a leecher (client).

### BitTorrent Seeder Setup

1. Navigate to the BitTorrent directory:
   ```bash
   cd bitTorrent
   ```

2. Start the seeder with the path to the torrent file, save directory, and port:
   ```bash
   python seeder.py --torrent myfile.torrent --dir . --port 7001
   ```

   Parameters:
   - `--torrent`: Path to the .torrent file
   - `--dir`: Directory where the original file is located
   - `--port`: Base port for BitTorrent communication (default: 7001)

   The seeder will:
   - Load the torrent file
   - Start serving the file to peers
   - Continue running until manually terminated (Ctrl+C)

### BitTorrent Leecher Setup

1. Run the leecher with the path to the torrent file and test parameters:
   ```bash
   python leecher.py --torrent myfile.torrent --trials 5 --filesize 1048576
   ```

   Parameters:
   - `--torrent`: Path to the .torrent file
   - `--trials`: Number of download trials to run
   - `--filesize`: Expected file size in bytes (required for accurate metrics)

   The leecher will:
   - Download the file multiple times (based on trials)
   - Measure download time, throughput, and overhead
   - Save detailed metrics to a timestamped CSV file
   - Generate a summary file with average metrics

## Running Comprehensive Tests

For a complete comparison of all three protocols:

1. Set up the required environments for all protocols
2. Run tests for each protocol separately
3. Compare results across protocols

### Example Test Sequence

First, test HTTP/1.1:
```bash
cd http1
python http1_server.py  # Run on server machine
python http1_client.py  # Run on client machine
```

Next, test HTTP/2:
```bash
cd http2
python server.py  # Run on server machine
python client.py --server SERVER_IP  # Run on client machine
```

Finally, test BitTorrent:
```bash
cd bitTorrent
python seeder.py --torrent file_1MB.torrent --dir test_files  # Run on server machine
python leecher.py --torrent file_1MB.torrent --trials 5 --filesize 1048576  # Run on client machine
```

## Understanding Results

### HTTP/1.1 and HTTP/2 Results
Both HTTP implementations generate JSON result files that include:
- **Average Throughput**: Data transfer rate in kilobits per second (kbps)
- **Standard Deviation**: Variation in throughput across multiple transfers
- **Overhead Ratio**: The ratio of total transferred data to file size (headers and protocol overhead)

### BitTorrent Results
BitTorrent generates two files per test:
- **Detailed CSV file**: Contains metrics for each trial
- **Summary file**: Contains average metrics across all trials

Metrics include:
- **Round-Trip Time (RTT)**: Total download time
- **Throughput**: Data transfer rate in kilobits per second
- **Total Data Transferred**: Ratio of total data to file size
- **Total Payload Transferred**: Actual file data received

### Protocol Comparison
When comparing protocols, look for:
1. **Throughput differences** across file sizes
2. **Overhead ratios** - typically BitTorrent has higher overhead for small files
3. **Consistency** (standard deviation) - lower variation means more predictable performance
4. **Scaling efficiency** - how performance changes as file size increases

## Troubleshooting

### Common Issues for All Protocols

1. **Connection Refused**:
   - Ensure the server/seeder is running
   - Check if the IP address and port are correctly configured
   - Verify firewall settings allow traffic on the specified port

2. **Slow Performance**:
   - Check network conditions
   - Verify no other bandwidth-intensive applications are running
   - Try running tests during periods of low network usage

### HTTP-Specific Issues

1. **File Not Found Errors**:
   - Check file permissions
   - Verify filenames match exactly what the client is requesting

### BitTorrent-Specific Issues

1. **Tracker Connection Issues**:
   - If using an external tracker, ensure it's accessible
   - Consider using DHT or local trackers for testing

2. **Seeding Issues**:
   - Ensure the seeder has the complete file
   - Verify the seeder is properly configured for incoming connections
   - Check that both seeder and leecher are using the same .torrent file

3. **libtorrent Installation Problems**:
   - libtorrent can be difficult to install on some platforms
   - Consider using Docker for a consistent environment
   - For Windows, the Anaconda distribution often simplifies installation