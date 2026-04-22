import subprocess
import hashlib

class HardwareAuthenticator:
    """Lấy thông số phần cứng và tạo mã bản quyền duy nhất"""
    
    @staticmethod
    def get_system_uuid():
        """Lấy UUID của bo mạch chủ (Dùng PowerShell thay cho wmic để tương thích Win 11)"""
        try:
            # Lệnh PowerShell lấy UUID an toàn
            cmd = 'powershell -Command "(Get-CimInstance -Class Win32_ComputerSystemProduct).UUID"'
            result = subprocess.check_output(cmd, shell=True)
            uuid = result.decode('utf-8').strip()
            return uuid
        except Exception as e:
            return f"ERROR_GETTING_UUID: {e}"

    @staticmethod
    def generate_hwid():
        """Băm (Hash) UUID thành một chuỗi an toàn, không thể dịch ngược"""
        raw_id = HardwareAuthenticator.get_system_uuid()
        
        # Nếu bị lỗi, trả về None để hệ thống khóa app
        if "ERROR" in raw_id or not raw_id:
            return None
            
        # Dùng SHA-256 mã hóa thông tin phần cứng
        hwid_hash = hashlib.sha256(raw_id.encode('utf-8')).hexdigest()
        
        # Lấy 20 ký tự đầu làm License Key
        return hwid_hash[:20].upper()

if __name__ == "__main__":
    my_hwid = HardwareAuthenticator.generate_hwid()
    print(f"Mã định danh máy tính của bạn là: {my_hwid}")