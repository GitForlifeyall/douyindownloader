import sys
sys.stdout.reconfigure(encoding='utf-8')
from gradio_client import Client

client = Client('k2-fsa/OmniVoice')
print("Successfully connected!")
# Inspect API info
with open("output/omnivoice_api.txt", "w", encoding="utf-8") as f:
    f.write(client.view_api(print_info=False, return_format="str"))
print("Saved API info to output/omnivoice_api.txt")
