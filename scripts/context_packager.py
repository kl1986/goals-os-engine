import argparse
import glob
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def get_category(filepath: Path) -> str:
    path_str = str(filepath).lower()
    parts = path_str.split(os.sep)
    if any('adr' in part for part in parts):
        return '_adrs_context.md'
    elif any('ticket' in part or 'issue' in part for part in parts):
        return '_tickets_context.md'
    else:
        return '_code_context.md'

def bundle_context(file_patterns: list[str], output_dir: str = 'scratch'):
    output_path = Path(output_dir)
    
    # Expand globs
    files_to_process = set()
    for pattern in file_patterns:
        # glob.glob handles the pattern
        matched = glob.glob(pattern, recursive=True)
        for m in matched:
            p = Path(m)
            if p.is_file():
                files_to_process.add(p)
                
    if not files_to_process:
        logging.warning("No files found to process.")
        return

    output_path.mkdir(parents=True, exist_ok=True)

    from collections import defaultdict
    categorized_files = defaultdict(list)

    for filepath in files_to_process:
        cat = get_category(filepath)
        categorized_files[cat].append(filepath)

    for cat_file, files in categorized_files.items():
        if not files:
            continue
            
        out_file_path = output_path / cat_file
        try:
            with open(out_file_path, 'w', encoding='utf-8') as out_f:
                for fpath in sorted(files):
                    try:
                        with open(fpath, 'r', encoding='utf-8') as in_f:
                            content = in_f.read()
                        out_f.write(f"# File: {fpath}\n\n")
                        out_f.write(content)
                        out_f.write("\n\n")
                    except Exception as e:
                        logging.warning(f"Could not read {fpath}: {e}")
            logging.info(f"Created {out_file_path} with {len(files)} files.")
        except Exception as e:
            logging.error(f"Failed to write to {out_file_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Context bundler for NotebookLM.")
    parser.add_argument('patterns', nargs='*', help='File paths or globs to process')
    parser.add_argument('--out-dir', default='scratch', help='Output directory (default: scratch)')
    
    args = parser.parse_args()
    
    if not args.patterns:
        parser.print_help()
        sys.exit(0)
        
    bundle_context(args.patterns, args.out_dir)

if __name__ == '__main__':
    main()
