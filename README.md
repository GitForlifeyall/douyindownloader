# Douyin / TikTok AI Dubbing Studio 🎬🎙️

An industrial-grade, fully automated AI dubbing, inpainting, and localization pipeline built for viral **YouTube Shorts** and **Instagram Reels**.

Transform original Chinese Douyin and TikTok videos into hyper-engaging, native Hindi/Hinglish short-form videos with continuous single-narrator storytelling, multiple state-of-the-art voice models, intelligent RapidOCR subtitle blurring, Foley/SFX audio stem isolation, and dynamic typography subtitles.

---

## ⚡ Key Highlights & Core Capabilities

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       PIPELINE ARCHITECTURE                                            │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                                                          
 ┌────────────────┐       ┌──────────────────────┐       ┌────────────────────────┐                      
 │  Douyin/TikTok │  ───> │ RapidOCR Subtitle    │  ───> │ Faster-Whisper         │                      
 │  Downloader    │       │ Cleaner & Inpainting │       │ Large-v3-Turbo Speech  │                      
 └────────────────┘       └──────────────────────┘       └────────────────────────┘                      
                                                                     │                                    
                                                                     ▼                                    
 ┌────────────────┐       ┌──────────────────────┐       ┌────────────────────────┐                      
 │ Meta HTDemucs  │       │ Multi-Model TTS      │ <───  │ Gemini 3.8 Transcreator│                      
 │ Foley / SFX    │       │ Voice Synthesis      │       │ (Method 1 Infinite Loop)                       
 └────────────────┘       └──────────────────────┘       └────────────────────────┘                      
         │                           │                                                                    
         └─────────────┬─────────────┘                                                                    
                       ▼                                                                                  
 ┌────────────────────────────────────────────────────────┐                                              
 │ Dynamic Tempo Scaling + Silence Compressor (<140ms)   │                                              
 └────────────────────────────────────────────────────────┘                                              
                       │                                                                                  
                       ▼                                                                                  
 ┌────────────────────────────────────────────────────────┐                                              
 │ Whisper Word-Level DP Align + Dynamic MarginV Subtitles│                                              
 └────────────────────────────────────────────────────────┘                                              
                       │                                                                                  
                       ▼                                                                                  
 ┌────────────────────────────────────────────────────────┐                                              
 │ Final 4K/HEVC NVENC Mux + SEO Metadata & Drive Sync    │                                              
 └────────────────────────────────────────────────────────┘                                              
```

---

## 🌟 Comprehensive Feature Set

### 1. 🎙️ Multi-Model TTS Voice Engine Suite
Switch seamlessly between local GPU and cloud voice models tailored for punchy, emotionally resonant Indian voiceovers:
- **Sarvam AI (`bulbul:v3` & `bulbul:v4-flash`)**:
  - Ultra-realistic native Hindi and Hinglish vocal prosody with natural Indian dialects and intonations.
  - Built-in speaker selection: `shubh`, `arvind`, `ratan`, and more.
- **Google Gemini Audio / Flash TTS**:
  - Expressive zero-shot speech synthesis powered by `gemini-3.8-flash` and `gemini-2.5`.
  - Signature **Bunty** persona (Puck voice clone) for high-octane commentary, along with `Charon`, `Kore`, `Fenrir`, and `Aoede`.
- **OmniVoice (Local GPU Zero-Shot TTS)**:
  - High-fidelity offline voice cloning and Hindi synthesis directly on CUDA.
- **Kokoro TTS (Local ONNX Neural Engine)**:
  - Lightweight, ultra-fast 82M parameter neural TTS running locally on CPU/GPU via ONNX runtime.
- **ElevenLabs**:
  - Studio-grade multi-voice expressive dubbing with emotional realism.
- **Alternative Backends**:
  - Edge-TTS, Meta MMS (Massively Multilingual Speech), and Coqui XTTS-v2 for line-by-line experimentation.

---

### 2. 🔍 Anti-Glitch Subtitle Blurring & RapidOCR Inpainting
Completely removes hardcoded Chinese subtitles and overlays without ugly artifacts, ghosting, or rectangular seams:
- **RapidOCR Clause-Sampling**:
  - Automatically detects hardcoded subtitle bounding boxes and text areas frame-by-frame.
- **Luminance-Suppressed Blurring**:
  - Traditional Gaussian blurs create bright white "foggy silhouettes" over white subtitles. Our pipeline pulls bright text stroke luminance down to match ambient background levels *before* filtering.
- **Euclidean Smoothstep Pill Plate**:
  - Masks are rendered with smoothstep pill-shaped curved radii rather than harsh rectangular edges, blending seamlessly into the footage.
- **Split-Second Flash & Margin Immunity**:
  - Uses generous horizontal safety padding (`pad_x=75px`, `pad_y=16px`, `min_width=760px`) to prevent subtitle edges or drop shadows from flashing on screen during rapid transitions.
- **Dynamic MarginV Calculation**:
  - Automatically extracts bounding box coordinates into `<base>_clean_box.json` (e.g. `margin_v: 351/405`), directly informing the caption engine where to position new subtitles.
- **Hardware Acceleration**:
  - FFmpeg NVDEC (`-hwaccel cuda`) video decoding and NVENC HEVC encoding for blazing-fast batch processing.

---

### 3. 🔄 Continuous Single-Narrator Engine (`dub_single_narrator.py`)
Replaces robotic, block-by-block translated SRT speech with human-sounding storytelling:
- **Method 1 Infinite Loop (Cause & Effect Bridge)**:
  - Structures the narration so the ending connects seamlessly into the opening hook, multiplying viewer retention on looping Shorts/Reels.
- **Multi-Persona Transcreation**:
  - **`viral` (Showrunner / Master Storyteller)**: High-energy, suspenseful pacing that keeps audiences hooked on engineering, craftsmanship, and dramatic reveals.
  - **`funny` / `comedy` / `roast`**: Unhinged Desi commentary combining Lord Puneet Superstar energy, raw street slang, and viral Instagram observational roasts.
- **Smart Silence Compressor**:
  - Tightens unnatural pauses (>200ms) down to a crisp ~140ms between sentences, eliminating dead air.
- **Dynamic Master Tempo Scaling**:
  - Mathematically scales speech pacing so narration starts at `0:00` and lands precisely at `vid_dur - margin` (0.00s for infinite loop)—**zero truncated words and zero awkward cuts**.

---

### 4. 📝 High-Retention Animated Subtitles (ASS Engine)
Engineered specifically for short-form mobile engagement:
- **Typography & Styling**:
  - Crisp, bold **Montserrat ExtraBold** (120pt), thick 9.0 outline, and 2.5 drop shadow for instant readability over fast-moving video.
  - Rapid-fire **≤ 3 words per screen** pacing.
- **Whisper Word-Level Real-Audio Alignment**:
  - Runs Faster-Whisper `large-v3-turbo` on the *final* mixed voiceover track.
  - Uses Needleman-Wunsch Dynamic Programming (DP) to map Devanagari script tokens to spoken Roman-script tokens (`normalize_match_token()` & phonetic skeleton alignment).
- **Phonetic Hinglish Transliteration**:
  - Seamlessly transliterates Devanagari text into clean Romanized Hinglish via `dubbing_studio/hinglish.py`.
- **Dynamic Vertical Offset (MarginV)**:
  - Dynamically anchors the captions directly over the blurred subtitle plate using the detected OCR box coordinates.

---

### 5. 🔊 Meta HTDemucs Foley & Audio Stem Separation
- **Foley Sound Isolation**:
  - Uses Meta's HTDemucs model to separate original Chinese speech from physical environmental Foley (footsteps, tool impacts, water splashes, ambient sounds).
- **Sidechain Ducking**:
  - Automatically ducks original background music while boosting Foley impact sounds (`sfx.wav`) under the new Hindi master voiceover.

---

### 6. 📥 Downloader & Social Workflow Tools
- **Channel Downloader**:
  - Scrapes and downloads full Douyin/TikTok creator feeds using `tools/download_channels.py` and `channelsondouin.txt`.
- **Browser UserScript (`douyin_user_video_filter.user.js`)**:
  - Tampermonkey script to filter, sort, and inspect viral videos directly inside the Douyin web interface.
- **SEO & Social Metadata Generation**:
  - Generates high-CTR YouTube titles, keyword-rich descriptions, and tags.
  - Strictly enforces YouTube's character limit (< 5,000 characters).
- **Google Drive Auto-Sync**:
  - Automated cloud backup of final clean videos, dubbed masters, and JSON metadata.

---

### 7. 🛡️ Resilient Runtime Key Pool & Eviction Manager
- Built-in multi-key rotation pool (`dubbing_studio/key_pool.py`).
- Instant runtime eviction of dead or rate-limited keys (Gemini 429/400/403, Sarvam 402/401, ElevenLabs) without modifying your local `.env` file.

---

## 📂 Repository Structure

```plaintext
douyindownloader/
├── dub_single_narrator.py         # Main continuous single-narrator dubbing engine
├── pipeline.py                    # Top-level pipeline entrypoint
├── dub_pipeline.bat               # Windows batch automation runner
├── channelsondouin.txt            # Channel list for automated scraping
├── douyin_user_video_filter.user.js # Tampermonkey user filter script
│
├── dubbing_studio/                # Core modular dubbing framework
│   ├── pipeline.py                # Full automated multi-step orchestrator
│   ├── tts_engine.py              # ASS subtitle generator & Kokoro engine
│   ├── tts.py                     # Sarvam AI Bulbul integration
│   ├── tts_google.py              # Google Gemini / Flash Audio integration
│   ├── tts_elevenlabs.py          # ElevenLabs voice synthesis
│   ├── tts_omnivoice.py           # OmniVoice local GPU synthesis
│   ├── transcriber.py             # Faster-Whisper GPU transcription
│   ├── translator.py              # Gemini prompt & transcreation engine
│   ├── separator.py               # Meta HTDemucs audio stem separation
│   ├── block_aligner.py           # Subtitle alignment & dynamic volume resolver
│   ├── hinglish.py                # Devanagari to Roman Hinglish transliterator
│   ├── key_pool.py                # Multi-key rotation & thread-safe eviction
│   ├── downloader.py              # Downloader API wrapper
│   └── gdrive_uploader.py         # Google Drive auto-sync client
│
├── tools/                         # Specialized utility scripts
│   ├── blur_subtitles_rapidocr.py # RapidOCR luminance-suppressed subtitle blur
│   ├── blur_subtitles.py          # Standard OpenCV subtitle blur
│   ├── download_channels.py       # Batch channel scraper
│   ├── generate_youtube_titles.py # High-CTR metadata generator
│   ├── batch_run_folders.py       # Multi-folder batch processor
│   ├── generate_multi_voice_dubs.py # Multi-voice comparison generator
│   └── make_google_flash_dub.py   # Gemini Flash dub generator
│
├── assets/                        # Background audio, fonts (Montserrat ExtraBold)
├── TikTokDownloader/              # Downloader core & dependencies
└── config/                        # Global pipeline configuration
```

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- **Python**: 3.10 or newer
- **FFmpeg**: Installed and accessible in your system `PATH` (with CUDA/NVENC support recommended)
- **NVIDIA GPU**: Recommended for Faster-Whisper, HTDemucs, and RapidOCR CUDA acceleration

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/GitForlifeyall/douyindownloader.git
cd douyindownloader
pip install -r requirements.txt
```

*(Optional: Install dependencies for dubbing studio tools)*
```bash
pip install -r requirements.dbs.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env` and set your API keys:
```ini
# Gemini API Key(s) (supports single or comma-separated pool)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_API_KEYS=key1,key2,key3

# Sarvam AI API Key
SARVAM_API_KEY=your_sarvam_api_key_here

# (Optional) Kokoro ONNX model paths
KOKORO_MODEL_PATH=path/to/kokoro-v1.0.onnx
KOKORO_VOICES_PATH=path/to/voices-v1.0.bin
```

---

## 💻 CLI Usage Examples

### A. Continuous Single-Narrator Dubbing (`dub_single_narrator.py`)

**1. Default Viral Dub (Sarvam AI `shubh` voice):**
```bash
python dub_single_narrator.py --engine sarvam --speaker shubh
```

**2. Google Flash Audio with "Bunty" Persona:**
```bash
python dub_single_narrator.py --bunty
```

**3. Unhinged Desi Comedy / Roast Style:**
```bash
python dub_single_narrator.py --bunty --funny
# or specify voice:
python dub_single_narrator.py --engine sarvam --speaker arvind --style funny
```

**4. Force Fresh Script Transcreation & Re-dub:**
```bash
python dub_single_narrator.py --bunty --reloop --force
```

---

### B. Subtitle Blurring & OCR Video Inpainting

Clean hardcoded subtitles from a video using RapidOCR with Luminance Suppression:
```bash
python tools/blur_subtitles_rapidocr.py --input path/to/video.mp4
```

---

### C. End-to-End Orchestrated Pipeline

Run the full automated multi-stage pipeline (Download ➔ Blur ➔ Transcribe ➔ Transcreate ➔ Stem Separation ➔ Multi-Model TTS ➔ Sync ➔ Drive Sync):
```bash
python -m dubbing_studio.pipeline
```

---

### D. Batch Channel Scraping

Download channels configured in `channelsondouin.txt`:
```bash
python tools/download_channels.py
```

---

## 🔒 Security & Best Practices

- **Zero Hardcoded Secrets**: All API tokens are loaded dynamically from environment variables.
- **Fail-Safe Quota Handling**: Runtime eviction ensures your batch jobs don't crash when an API key encounters 429 quota exhaustion.
- **Metadata Protection**: Automatic clipping protects descriptions against YouTube's 5,000 character limit.

---

## 📜 Attribution & License

- Downloader core based on [JoeanAmier/TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader). See `TikTokDownloader/license`.
- Original additions: RapidOCR subtitle inpainting, single-narrator continuous storytelling engine, multi-model voice synthesis architecture, and ASS subtitle sync.
