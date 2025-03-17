import libtorrent as lt
import sys
import time
import argparse

def start_seeding(torrent_filepath, output_dir, base_port):
    # Exract torrent name from the filepth for loggin purpuses
    torrent_name = torrent_filepath.split('.')[0]
    print(f"[INFO] Startin seeder for: {torrent_name}")

    # Crete a new session and listn on new port range
    session_instance = lt.session()
    # Changed port numbers: using base_port range (e.g., 7001 to 7011)
    session_instance.listen_on(base_port, base_port + 10)
    trial_number = 0

    while True:
        print(f"[INFO] Trial {trial_number}: Addin torrent to session.")
        # Create a torrent info obj and add it to the session
        torrent_info_obj = lt.torrent_info(torrent_filepath)
        torrent_handle = session_instance.add_torrent({'ti': torrent_info_obj, 'save_path': output_dir})
        
        # Wait untill the torrent is fully donlodad and seedin starts
        while not torrent_handle.status().is_seeding:
            current_status = torrent_handle.status()
            progress_percent = current_status.progress * 100
            down_rate = current_status.download_rate / 1000
            up_rate = current_status.upload_rate / 1000
            peers = current_status.num_peers
            state_list = ['queued', 'checking', 'downloading metadata', 'downloading', 
                          'finished', 'seeding', 'allocating', 'checking fastresume']
            print(f'\r[LOG] {progress_percent:.2f}% complete (down: {down_rate:.1f} kb/s, '
                  f'up: {up_rate:.1f} kB/s, peers: {peers}) - state: {state_list[current_status.state]}', end="")
            # Flush output to update log on same line
            sys.stdout.flush()
            time.sleep(1)
        
        print(f"\n[INFO] Seedin trial {trial_number} for '{torrent_name}' complete.")
        status = torrent_handle.status()
        print(f"[INFO] Total uploded for trial {trial_number}: {status.total_upload} bytes.")
        print(f"[INFO] Total payload uploded for trial {trial_number}: {status.total_payload_upload} bytes.")
        
        # Remove torrent from session for next trial
        session_instance.remove_torrent(torrent_handle)
        trial_number += 1
        print(f"[INFO] Prepairing for the next trial...\n")
        time.sleep(2)  # Optional pause between trials

def parse_args():
    parser = argparse.ArgumentParser(description="Seeder: Start seeding a torrent with logging.")
    parser.add_argument("--torrent", type=str, required=True, help="Path to the torrent file")
    parser.add_argument("--dir", type=str, default=".", help="Directory to save the torrent")
    parser.add_argument("--port", type=int, default=7001, help="Base port to use for seeding")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    start_seeding(args.torrent, args.dir, args.port)
