#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
srt_dub_translator.py
======================
Automated SRT Dubbing & Translation Pipeline (CLI & Module Wrapper).
Re-exports core functionality from the dubbing_studio package.
"""

from dubbing_studio.translator import (
    SYSTEM_PROMPT,
    DEFAULT_TARGET_LANGUAGE,
    parse_time,
    format_time,
    parse_srt,
    inject_constraints_into_srt,
    clean_and_verify_srt,
    SRTDubTranslator,
    translate_and_rewrite_srt,
)


def main():
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Automated SRT Dubbing & Translation Pipeline (Gemini SDK)"
    )
    parser.add_argument("input_srt", help="Path to input .srt file")
    parser.add_argument("-o", "--output", help="Path to output translated .srt file (optional)")
    parser.add_argument(
        "-l", "--lang",
        default=DEFAULT_TARGET_LANGUAGE,
        help="Target language / style (default: Hindi conversational Hinglish)"
    )
    parser.add_argument(
        "-m", "--model",
        default="gemini-3.8-flash",
        help="Gemini model name (default: gemini-3.8-flash)"
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=35,
        help="Max subtitle blocks per Gemini call (default: 35)"
    )
    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=0.4,
        help="Model temperature (default: 0.4)"
    )

    args = parser.parse_args()
    input_path = Path(args.input_srt)
    if not input_path.exists():
        print(f"Error: Input SRT file not found: {input_path}")
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_dubbed.srt"

    translator = SRTDubTranslator(model=args.model)
    verified_srt, report = translator.translate_and_rewrite_srt(
        srt_input=input_path,
        target_language=args.lang,
        batch_size=args.batch_size,
        temperature=args.temperature
    )

    output_path.write_text(verified_srt, encoding="utf-8")
    print(f"\n==========================================")
    print(f"Successfully generated dubbed SRT!")
    print(f"Output File: {output_path}")
    print(f"Total Blocks: {report['total_blocks']}")
    print(f"Oversized Blocks (> 1.25x limit): {report['oversized_count']}")
    if report["oversized_blocks"]:
        print("Blocks flagged for TTS compression:")
        for ob in report["oversized_blocks"]:
            print(f"  - Block #{ob['index']}: {ob['word_count']} words (Max: {ob['max_words']}, Atempo: ~{ob['recommended_atempo']}x)")
    print(f"==========================================\n")


if __name__ == "__main__":
    main()
