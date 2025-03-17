import requests
import time
import json
import statistics
import os

computer1_url = 'http://172.30.115.112:8080'  

experiments = [
    {"file_size": "10kB", "repetitions": 1000},
    {"file_size": "100kB", "repetitions": 100},
    {"file_size": "1MB", "repetitions": 10},
    {"file_size": "10MB", "repetitions": 1}
]

results_summary = {
    "10kB": {"throughputs_kbps": [], "overhead_ratios": [], "avg_kbps": 0, "std_dev_kbps": 0, "avg_overhead": 0},
    "100kB": {"throughputs_kbps": [], "overhead_ratios": [], "avg_kbps": 0, "std_dev_kbps": 0, "avg_overhead": 0},
    "1MB": {"throughputs_kbps": [], "overhead_ratios": [], "avg_kbps": 0, "std_dev_kbps": 0, "avg_overhead": 0},
    "10MB": {"throughputs_kbps": [], "overhead_ratios": [], "avg_kbps": 0, "std_dev_kbps": 0, "avg_overhead": 0}
}

def download_file(server_url, filename, repetitions):
    throughputs_kbps = []
    overhead_ratios = []
    file_size_category = filename.split("_")[1]  
    
    print(f"Starting {repetitions} transfers of {filename}...")
    
    for i in range(repetitions):
        start_time = time.time()
        try:
            response = requests.get(f'{server_url}/download/{filename}')
            end_time = time.time()
            
            if response.status_code == 200:
                file_size_bytes = len(response.content)
                
                headers_size = 0
                for name, value in response.headers.items():
                    headers_size += len(name) + len(value) + 4
                
                request_headers_size = 0
                for name, value in response.request.headers.items():
                    request_headers_size += len(name) + len(value) + 4
                
                total_data_transferred = headers_size + request_headers_size + file_size_bytes
                
                overhead_ratio = total_data_transferred / file_size_bytes
                
                transfer_time = end_time - start_time
                throughput_bytes_per_second = file_size_bytes / transfer_time
                
                throughput_kbps = (throughput_bytes_per_second * 8) / 1000
                
                throughputs_kbps.append(throughput_kbps)
                overhead_ratios.append(overhead_ratio)
                
                progress_interval = max(1, min(repetitions // 10, 10))
                if (i + 1) % progress_interval == 0:
                    print(f"Progress: {i + 1}/{repetitions} transfers completed ({(i + 1)/repetitions*100:.1f}%)")
                
            else:
                print(f"Failed to download {filename}: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"Error downloading {filename}: {str(e)}")
    
    if file_size_category in results_summary and throughputs_kbps:
        results_summary[file_size_category]["throughputs_kbps"].extend(throughputs_kbps)
        results_summary[file_size_category]["overhead_ratios"].extend(overhead_ratios)
    
    return throughputs_kbps, overhead_ratios

def run_experiments():
    for exp in experiments:
        file_size = exp["file_size"]
        repetitions = exp["repetitions"]
        
        a_filename = f"A_{file_size}"
        print(f"\nRunning experiment: {repetitions} transfers of {a_filename}")
        download_file(computer1_url, a_filename, repetitions)
        
    for size, data in results_summary.items():
        if data["throughputs_kbps"]:
            data["avg_kbps"] = statistics.mean(data["throughputs_kbps"])
            data["std_dev_kbps"] = statistics.stdev(data["throughputs_kbps"]) if len(data["throughputs_kbps"]) > 1 else 0
        if data["overhead_ratios"]:
            data["avg_overhead"] = statistics.mean(data["overhead_ratios"])
    
    with open("http1_1_throughput_results.json", "w") as f:
        clean_summary = {}
        for size, data in results_summary.items():
            clean_summary[size] = {
                "avg_throughput_kbps": data["avg_kbps"],
                "std_dev_kbps": data["std_dev_kbps"],
                "avg_overhead_ratio": data["avg_overhead"],
                "transfer_count": len(data["throughputs_kbps"])
            }
        
        json.dump(clean_summary, f, indent=2)
    
    print("\nAll experiments completed. Results saved to http1_1_throughput_results.json")
    
    print("\nHTTP/1.1 Results Summary:")
    print("-----------------------------------------------------------------")
    print("File Size | Average Throughput | Standard Deviation | Overhead Ratio")
    print("-----------------------------------------------------------------")
    for size, data in results_summary.items():
        if data["throughputs_kbps"]:
            print(f"{size:8} | {data['avg_kbps']:18.2f} | {data['std_dev_kbps']:18.2f} | {data['avg_overhead']:14.8f}")
    print("-----------------------------------------------------------------")

if __name__ == "__main__":
    run_experiments()