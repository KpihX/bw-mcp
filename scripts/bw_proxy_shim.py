#!/usr/bin/env python3
import subprocess
import sys
import os
import re
import webbrowser

def main():
    container_name = 'bw-proxy'
    try:
        # Check if container is running
        status = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', container_name], capture_output=True, text=True)
        if status.stdout.strip() != 'true':
            print(f"🔄 Starting {container_name} container...")
            subprocess.run(['docker', 'start', container_name], capture_output=True)

        # Execute command and stream output
        cmd = ['docker', 'exec']
        if sys.stdin.isatty():
            cmd.append('-it')
        
        # We assume the app is installed at /app/src or similar, 
        # but the entrypoint in Dockerfile is already set to python -m bw_proxy.main
        # For simplicity, we just call the module directly inside the container.
        cmd.extend([container_name, 'python', '-m', 'bw_proxy.main'] + sys.argv[1:])

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        for line in iter(process.stdout.readline, ''):
            print(line, end='')
            
            # Detect HITL Approval URL
            # Example: URL      : http://0.0.0.0:1138/?token=...
            match = re.search(r'(http://[0-9.]+:(1138)/[^\s]+token=[a-f0-9-]+)', line)
            if match:
                url = match.group(1).replace('0.0.0.0', '127.0.0.1')
                print(f"\n🚀 [Host Agent] Detected Approval URL: {url}")
                webbrowser.open(url)
        
        process.wait()
        sys.exit(process.returncode)

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

if __name__ == '__main__':
    main()
