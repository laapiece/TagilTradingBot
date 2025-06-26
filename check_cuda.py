import torch
import os

print(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
print(f"torch.cuda.device_count(): {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"torch.cuda.current_device(): {torch.cuda.current_device()}")
    print(f"torch.cuda.get_device_name(0): {torch.cuda.get_device_name(0)}")
else:
    print("No CUDA device detected.")

# Check environment variables that might influence CUDA detection
print(f"CUDA_HOME: {os.getenv('CUDA_HOME')}")
print(f"PATH (relevant parts): {os.getenv('PATH')}")
