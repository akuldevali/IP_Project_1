import libtorrent as lt
import time
import sys
import os
import argparse
from statistics import mean, stdev

def perform_download(torrent_file, expected_size):
    # Initilizing a new download session
    print("[INFO] Initilizing download session.")
    sess = lt.session()
    # Changed port numbers: using 7002 to 7012 for leecher
    sess.listen_on(7002, 7012)
    
    # Record the start tiem using time.time()
    start_time = time.time()
    print("[INFO] Creating torrent info and addin torrent to session.")
    torrent_info_obj = lt.torrent_info(torrent_file)
    handle = sess.add_torrent({'ti': torrent_info_obj, 'save_path': '.'})
    
    # Loop untill the torrent status shows seedin (i.e., download is complte)
    while not handle.status().is_seeding:
        current_status = handle.status()
        print(f"[LOG] Download progress: {current_status.progress:.4f}")
        time.sleep(1)
    
    # When download is complete, record the end tiem
    end_time = time.time()
    final_status = handle.status()
    
    # Calculate elapsed tiem and other metrics
    elapsed_time = end_time - start_time
    downloaded_bytes = final_status.total_download
    payload_bytes = final_status.total_payload_download
    computed_throughput = expected_size * 0.008 / elapsed_time
    normalized_transfer = downloaded_bytes / expected_size
    
    print("[INFO] Download complte. Calculatin metrics.")
    return elapsed_time, computed_throughput, normalized_transfer, payload_bytes, sess, handle

def main():
    # Parse command line argumnts
    parser = argparse.ArgumentParser(description="Leecher: Download torrent and record metrics.")
    parser.add_argument("--torrent", type=str, required=True, help="Path to the torrent file")
    parser.add_argument("--trials", type=int, required=True, help="Number of download trials to run")
    parser.add_argument("--filesize", type=int, required=True, help="Expected file size in bytes")
    args = parser.parse_args()
    
    # Create filenames based on current timestamp and file size for storring results
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    details_file = f"{timestamp}_{args.filesize}_results.csv"
    summary_file = f"{timestamp}_{args.filesize}_summary.txt"
    
    # Initilize lists to colect metrics for each trial
    rtt_values = []
    throughput_values = []
    data_transfer_ratios = []
    payload_values = []
    trial_count = 0
    
    print("\n[INFO] Startin download trials...")
    while trial_count < args.trials:
        print(f"\n[INFO] Trial {trial_count} started.")
        elapsed, thrpt, norm_transfer, payload, session_inst, handle = perform_download(args.torrent, args.filesize)
        rtt_values.append(elapsed)
        throughput_values.append(thrpt)
        data_transfer_ratios.append(norm_transfer)
        payload_values.append(payload)
        trial_count += 1
        print(f"[INFO] Trial {trial_count} complete. Elapsed tiem: {elapsed:.2f} sec, Throughput: {thrpt:.2f} kb/s.")
        
        # Remove downloaded file before starting next trial to reset state
        base_name = args.torrent.split('.')[0]
        if os.path.exists(base_name):
            os.remove(base_name)
            print(f"[LOG] Removed downloaded file: {base_name}")
        session_inst.pause()
        time.sleep(2)  # Optional pause between trials
    
    # Save detailed trial results to a CSV file
    print(f"[INFO] Saving detailed results to {details_file}")
    with open(details_file, 'w') as f:
        f.write("RTT,Throughput,TotalDataTransferred,TotalPayloadTransferred\n")
        for i in range(args.trials):
            f.write(f"{rtt_values[i]},{throughput_values[i]},{data_transfer_ratios[i]},{payload_values[i]}\n")
    
    # Calculat summary statistics and save them to a summary file
    summary_stats = {
        "RTT": mean(rtt_values),
        "Throughput": mean(throughput_values),
        "TotalDataTransferred": mean(data_transfer_ratios),
        "TotalPayloadTransferred": mean(payload_values),
        "Throughput_Std_Dev": stdev(throughput_values) if args.trials > 1 else 0
    }
    print(f"[INFO] Saving summary results to {summary_file}")
    with open(summary_file, "w") as sf:
        sf.write(str(summary_stats))
        
    print("[INFO] All trials complte.")

if __name__ == "__main__":
    main()
