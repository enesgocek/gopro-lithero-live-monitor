"""Application-level camera errors shared by ports and adapters."""
class CameraError(Exception):
    def __init__(self,message,http_status=None):
        super().__init__(message)
        self.http_status=http_status
