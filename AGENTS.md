# Workspace Guidelines & Rules

## YouTube Metadata Rules
1. **Description Character Limit**:
   - The maximum length of any YouTube description generated or modified MUST strictly be **less than 5,000 characters** (YouTube's hard cap is 5,000 characters).
   - If user-supplied or AI-generated description content exceeds 5,000 characters, strip out lower-relevance keywords, redundant tags, or clutter until the length is safely under 5,000 characters (target range: 4,000–4,950 characters).
   - Never allow a description to meet or exceed 5,000 characters.

2. **Master Metadata Structure**:
   - Master metadata files stored in Google Drive or channel folders (`metadata.json`) follow the standard schema:
     - `number_of_videos`: Integer count
     - `videos`: List of objects with:
       - `title`: High-CTR title with emojis and hashtags (e.g. `#shorts`). For movie mode/recaps, NEVER include `(3D Animation In English)` or `(3D Animation)`.
       - `description`: Starts with `Comment "MOVIE" for the movie name! 🍿🎬`, followed by a comma-separated movie keyword block + fair-use disclaimer (< 5,000 characters).
       - `tags`: 4–5 broad, high-volume SEO search tags (e.g. `["movie", "movie explanation", "movie recap", "movies", "ending explained"]`). Avoid hyper-niche tags that decrease search discovery.

## Script Writing Rules
- Whenever writing or updating video scripts or script-writing prompts, load and follow the `creative-writing-skills` workspace skill at `.agents/skills/creative-writing-skills/SKILL.md` (applying `writing-principles`, `creative-writing-craft`, and `llm-writing` alongside `config/movie_pillar_script_guide.md`).

## Metricool Movie Niche Export Rules
- **Draft**: Strictly `"false"`.
- **Youtube AI generated content**: Strictly `"false"`.
- **TikTok Ai generated content**: Strictly `"false"`.
- **Facebook Title**: Remove `#shorts` and always append 2 generic movie hashtags: `#MovieExplained #MovieRecap` (e.g., `{clean_title} #MovieExplained #MovieRecap`).
- **YouTube Video Title**: Retain `#shorts` (without `(3D Animation)`).
- **Text (Caption)**: Start with `Comment "MOVIE" for the movie name! 🍿🎬 {clean_title} #MovieRecap #MovieExplained #Shorts`.

## Video Filename Length Rules (Facebook & Drive Hard Cap)
1. **Total Filename Length Under 50 Characters**:
   - The total length of any final video filename (including the `.mp4` extension) MUST strictly be **less than 50 characters** (maximum **49 characters**, i.e. `<= 49`).
   - Reason: Facebook rejects or errors out on video/reel uploads if filenames or word counts exceed 50 characters.
2. **Clutter Stripping**:
   - Always strip bracketed/parenthetical tags before saving or renaming:
     - `[Viral Mirrored]`, `[Viral Movie]`, `[Viral Paragraph]`, `[Funny Paragraph]`, `[Funny]`
     - `(3D Animation In Hindi)`, `(3D Animation In English)`, `(3D Animation)`, `3D Animation`
     - `#shorts`, `#short`, `#fyp`, `#birds`, `#nature`, `#zombie`, `#animation`
     - Pipeline suffixes like `_hindi_dubbed`, `_hindi_funny_elevenlabs_dubbed`, `_hindi_sarvam_dubbed_captioned`, etc.
3. **Clean Truncation & Stopwords**:
   - Truncate clean title stems to at most 45 characters (+ 4 characters for `.mp4` = max 49 chars).
   - Strip dangling conjunctions and prepositions (`and`, `the`, `a`, `an`, `in`, `of`, `to`, `for`, `with`, `as`, `from`) and trailing punctuation (`&`, `,`, `-`, `_`, `:`) before appending `.mp4`.
4. **Collision Resolution**:
   - If two files yield identical shortened names, append `_{counter}.mp4` while keeping the total length `<= 49` characters.

## Test Artifacts & Workspace Organization Rules
1. **No Test Outputs or Experimental Files in Root**:
   - Never write test outputs, intermediate audio snippets, temporary transcription files, experimental requirements/configs, or debug artifacts directly into the project root directory (`.`).
2. **Dedicated Folders for Artifacts & Experiments**:
   - **Test & Debug Artifacts**: All test-generated files (e.g. `test_*.wav`, `test_*.mp4`, sample transcripts, benchmark audio clips) MUST strictly be saved in [`tests/test_artifacts/`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/tests/test_artifacts/).
   - **Experimental Scratch & Configs**: Temporary experiment files, benchmark requirements (e.g. `requirements.<experiment>.txt`), one-off scratch scripts, and exploratory environment dumps MUST be placed in [`scratch/`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/scratch/) or [`tests/test_artifacts/`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/tests/test_artifacts/).
   - The project root (`.`) must strictly be reserved for core production pipelines, production `requirements.txt`, entrypoints, and documentation.

## Agent Session Handoff Logging Rules (MANDATORY FOR ALL AGENTS)
1. **Mandatory First Action**:
   - Every AI agent (Gemini, Antigravity, ChatGPT, Claude, Cline, Roo Code, Cursor, etc.) working in this codebase MUST first read the handoff history in [`handoffs/`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/) before beginning work.
2. **Log All Changes**:
   - Whatever changes, bugfixes, refactorings, or new features an agent implements, it MUST log the session details (timestamp, files modified, rationale, and outcome) into its designated handoff file in [`handoffs/`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/):
     - Gemini / Antigravity: [`handoffs/gemini_handoff.md`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/gemini_handoff.md)
     - ChatGPT: [`handoffs/chatgpt_handoff.md`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/chatgpt_handoff.md)
     - Cline: [`handoffs/cline_handoff.md`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/cline_handoff.md)
     - Roo Code: [`handoffs/roocode_handoff.md`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/roocode_handoff.md)
     - MiniMax: [`handoffs/minimax_handoff.md`](file:///c:/Users/rudra/PycharmProjects/douyindownloader/handoffs/minimax_handoff.md)
3. **New Agent Handoff Creation**:
   - If a new AI agent or assistant starts working in this project and does not have an existing handoff file in `handoffs/`, it MUST create its own `handoffs/<agent_name>_handoff.md` and document its work there.





