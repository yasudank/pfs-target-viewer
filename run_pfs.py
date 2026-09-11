import json
import os
import sys
import subprocess

def main():
    kernel_path = "/home/yasuda/.local/share/jupyter/kernels/pfs_pipe2d_w.2026.19/kernel.json"
    if not os.path.exists(kernel_path):
        print(f"Error: Kernel file not found at {kernel_path}", file=sys.stderr)
        sys.exit(1)

    with open(kernel_path, "r") as f:
        kernel_data = json.load(f)

    # Build environment dict
    env = os.environ.copy()
    env.update(kernel_data.get("env", {}))

    # Set python executable
    python_exe = kernel_data["argv"][0]

    # Construct command line arguments
    if len(sys.argv) < 2:
        print("Usage: python3 run_pfs.py <script_name.py> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = [python_exe] + sys.argv[1:]

    # Execute subprocess
    res = subprocess.run(cmd, env=env)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
