import subprocess
import pwd
import socket
from datetime import datetime


def get_user_usage() -> dict[str, dict[str, float]]:
    """
    Get user cpu, and mem usage of the processes running on the system using ps command.
    Returns:
        dict[str, dict[str, float]]: A dictionary containing user usage information.
            The keys are usernames, and the values are dictionaries with 'cpu' and 'mem' and count of processes. 
    """

    usage_info = {}
    NOLOGIN_SHELLS = {"/sbin/nologin", "/usr/sbin/nologin", "/bin/false"}

    try:

        # Run the ps command to get user, cpu, and mem usage
        processes = subprocess.run(
            ["ps", "-eo", "uid,user,%cpu,%mem"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True, timeout=10
        )
        
        # Process the output of the ps command
        for line in processes.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue

            uid, user, cpu, mem = parts[0], parts[1], parts[2], parts[3]
            
            if user == "root": continue
            # Check if the user has a valid shell
            try:
                uid_int = int(uid)
                user_info = pwd.getpwuid(uid_int)   
                if user_info.pw_shell in NOLOGIN_SHELLS:
                    continue
            except (KeyError, ValueError):
                continue

            
            # Initialize the user's entry if it doesn't exist
            if user not in usage_info:
                usage_info[user] = {"cpu": 0.0, "mem": 0.0, "process_count": 0}

            # Accumulate the cpu and mem usage and process count
            try:
                usage_info[user]["cpu"] += float(cpu)
                usage_info[user]["mem"] += float(mem)
                usage_info[user]["process_count"] += 1
            except ValueError:
                continue
        
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Error executing ps command: {e.stderr}")
        return {}          

    return usage_info


    
def get_load() -> tuple[float, float, float]:
    """
    Get the load average of the login nodes from the file /proc/loadavg

        Returns:    
        tuple[float, float, float]: A tuple of floats representing load over 
        the past 1, 5, 15 minutes respectively.
    """

    try:
        with open("/proc/loadavg") as f:
            content = f.read()
            fields = content.strip().split()

            return (float(fields[0]), float(fields[1]), float(fields[2]))
            

    except OSError as e: 
        print(f"Could not read /proc/loadavg: {e}")
        return (0.0, 0.0, 0.0)
    

def get_memory() -> dict[str, float]:
    """
    Read the machine-wide memory state from /proc/meminfo.

    Returns:
        dict[str, float]: a dict with two keys, both values in gigabytes:
            'total_gb'      - total RAM on this node
            'avail_gb'  - RAM realistically available to new programs
    """
    
    result = {"total_gb": 0.0, "avail_gb": 0.0}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    try:
                        result["total_gb"] = int(line.split()[1]) / (1024 ** 2)
                    except (ValueError, IndexError):
                        pass
                elif line.startswith("MemAvailable:"):
                    try:
                        result["avail_gb"] = int(line.split()[1]) / (1024 ** 2)
                    except (ValueError, IndexError):
                        pass
    
    except OSError as e:
        print(f"Could not read /proc/meminfo: {e}")
    
    return result


def get_user_count() -> int:
    """ Gets the total number of users currently logged in on the current login
    node

        Return:
            int: the number of users
    """

    try:
        users = subprocess.run(
            ["who"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10)
        
        unique_users = {
            line.split()[0]                # take ONLY the first token (username)
            for line in users.stdout.splitlines()
            if line.strip()
        }
        
        return len(unique_users)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Error executing who command: {e.stderr}")
        return 0

def collect_login_data() -> dict:
    """
    Take a complete snapshot of this login node
    
    Returns:
        dict: a snapshot with the following keys:
            'hostname'   (str)   - short hostname, e.g. 'midway3-login4'
            'timestamp'  (str)   - ISO 8601 collection time
            'load'       (tuple) - (1, 5, 15) minute load averages
            'memory'     (dict)  - {'total_gb', 'avail_gb'}
            'user_count' (int)   - number of distinct logged-in users
            'users'      (dict)  - per-user {cpu, mem, process_count}
    """
    
    return {
        "hostname": socket.gethostname().split(".")[0],
        "timestamp": datetime.now().isoformat(),
        "load": get_load(),
        "user_count": get_user_count(),
        "users": get_user_usage(),
        "memory": get_memory(),
    }

if __name__ == "__main__":
    import json
    snapshot = collect_login_data()
    print(json.dumps(snapshot, indent=2, default=str))
