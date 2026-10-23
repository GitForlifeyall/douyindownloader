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
       - `title`: High-CTR title with emojis and hashtags (e.g. `#shorts`)
       - `description`: Comma-separated keyword block + disclaimer (< 5,000 characters)
       - `tags`: Exactly 3 clean, broad, SEO-optimized tags (e.g. `["Oddly Satisfying", "ASMR", "<Topic>"]` or `["Animation", "3D Explained", "<Topic>"]`)
