import os
import requests

API_KEY = "bbabed1c090b0ca53f29195ac28d31ccae8fce0d".strip()

# API v3 strictly requires field tags like gen: and sp:
query = 'gen:"Gryllotalpa" sp:"orientalis"'
download_dir = "Gryllotalpa_orientalis_dataset"
os.makedirs(download_dir, exist_ok=True)

# URL format with API v3 tagged query
url = f"https://xeno-canto.org/api/3/recordings?query={query}&key={API_KEY}"
headers = {"User-Agent": "Mozilla/5.0"}

print(f"Connecting to Xeno-Canto API v3 with query: {query}...")

try:
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        recordings = data.get("recordings", [])
        print(f"Found {len(recordings)} recordings.\n")
        
        # Fallback to general genus tag if exact species returns 0 results
        if len(recordings) == 0:
            print("No exact species matches. Searching general genus tag 'gen:Gryllotalpa'...")
            fallback_url = f"https://xeno-canto.org/api/3/recordings?query=gen:Gryllotalpa&key={API_KEY}"
            response = requests.get(fallback_url, headers=headers)
            recordings = response.json().get("recordings", [])
            print(f"Found {len(recordings)} recordings in genus Gryllotalpa.\n")

        for rec in recordings:
            rec_id = rec.get("id")
            file_url = rec.get("file")
            
            if file_url and file_url.startswith("//"):
                file_url = "https:" + file_url
                
            file_path = os.path.join(download_dir, f"XC{rec_id}.mp3")
            print(f"Downloading XC{rec_id}.mp3 ...")
            
            audio_bytes = requests.get(file_url, headers=headers).content
            with open(file_path, "wb") as f:
                f.write(audio_bytes)
                
        print(f"\nSuccess! All files saved to: {os.path.abspath(download_dir)}")
    else:
        print(f"Server returned HTTP Status Code: {response.status_code}")
        print(f"Details: {response.text}")

except Exception as e:
    print(f"Execution Error: {e}")