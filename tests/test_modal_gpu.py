import modal

app = modal.App("test-cloud-gpu")

image = modal.Image.debian_slim().pip_install("torch")

@app.function(image=image, gpu="T4")
def check_gpu():
    import torch
    return torch.cuda.get_device_name(0)

@app.local_entrypoint()
def main():
    name = check_gpu.remote()
    print("\n" + "=" * 50)
    print(f" [SUCCESS] CLOUD GPU CONNECTED: {name}")
    print("=" * 50 + "\n")
