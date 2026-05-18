import subprocess
import hashlib
import sys
import os


class HardwareAuthenticator:
    """Lấy thông số phần cứng và tạo mã bản quyền duy nhất — hỗ trợ Windows/Linux/macOS."""

    @staticmethod
    def get_system_uuid() -> str:
        """Lấy UUID của bo mạch chủ theo từng hệ điều hành."""
        try:
            if sys.platform == "win32":
                cmd = 'powershell -Command "(Get-CimInstance -Class Win32_ComputerSystemProduct).UUID"'
                result = subprocess.check_output(cmd, shell=True, timeout=10)
                uuid = result.decode('utf-8', errors='replace').strip()
                if uuid and "ERROR" not in uuid.upper() and len(uuid) > 5:
                    return uuid

            elif sys.platform == "darwin":
                result = subprocess.check_output(
                    ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    timeout=10, stderr=subprocess.DEVNULL
                )
                for line in result.decode('utf-8', errors='replace').splitlines():
                    if "IOPlatformUUID" in line:
                        parts = line.split('"')
                        if len(parts) >= 4:
                            return parts[-2].strip()

            else:
                # Linux — thử /etc/machine-id trước (ổn định nhất)
                for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                    if os.path.exists(path):
                        with open(path, "r") as f:
                            uid = f.read().strip()
                        if uid:
                            return uid
                # Fallback: /proc/sys/kernel/random/boot_id (thay đổi sau reboot)
                boot_id_path = "/proc/sys/kernel/random/boot_id"
                if os.path.exists(boot_id_path):
                    with open(boot_id_path, "r") as f:
                        return f.read().strip()

        except Exception as e:
            pass

        # Last resort: hash of hostname + username
        import socket
        fallback = f"{socket.gethostname()}:{os.getenv('USERNAME') or os.getenv('USER') or 'user'}"
        return fallback

    @staticmethod
    def generate_hwid() -> str:
        """Băm UUID thành chuỗi 20 ký tự HEX (viết hoa) — làm ID máy ổn định."""
        raw_id = HardwareAuthenticator.get_system_uuid()
        if not raw_id:
            return ""
        hwid_hash = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        return hwid_hash[:20].upper()

    @staticmethod
    def get_formatted_hwid() -> str:
        """Trả về HWID định dạng XXXX-XXXX-XXXX-XXXX-XXXX (20 ký tự, 4 nhóm)."""
        hwid = HardwareAuthenticator.generate_hwid()
        if not hwid or len(hwid) < 20:
            return "KHÔNG XÁC ĐỊNH"
        return f"{hwid[0:4]}-{hwid[4:8]}-{hwid[8:12]}-{hwid[12:16]}-{hwid[16:20]}"


if __name__ == "__main__":
    hwid = HardwareAuthenticator.generate_hwid()
    print(f"HWID: {HardwareAuthenticator.get_formatted_hwid()}")
    print(f"Raw:  {hwid}")
