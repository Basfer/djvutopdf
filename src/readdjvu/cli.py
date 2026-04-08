import argparse
import os
from .parser import DjVuParser

def main():
    """Main function to run the CLI."""
    parser = argparse.ArgumentParser(
        description="A tool to parse DjVu files and extract pages and layers."
    )
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to the input DjVu file."
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Path to the directory where output will be saved."
    )
    parser.add_argument(
        "--create-pdf", "-p",
        action="store_true",
        help="Create a PDF from the extracted pages."
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=os.cpu_count(),
        help="Number of threads to use for parallel processing."
    )
    parser.add_argument(
        "--keep-pages", "-k",
        action="store_true",
        help="Keep the individual page directories after processing."
    )
    parser.add_argument(
        "--extract-text", "-x",
        action="store_true",
        help="Extract the text layer from each page."
    )
    args = parser.parse_args()

    # If creating PDF, automatically extract text layer
    if args.create_pdf and not args.extract_text:
        args.extract_text = True
        print("Enabling text extraction for PDF creation...")

    # Ensure output directory exists
    os.makedirs(args.output_dir, exist_ok=True)

    try:
        # Instantiate the parser
        djvu_parser = DjVuParser()
        # Run the parsing process
        djvu_parser.parse(args.input_file, args.output_dir, args.create_pdf, args.threads, args.keep_pages, args.extract_text)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Error: {e}")
        # Exit with a non-zero code to indicate failure
        exit(1)

if __name__ == '__main__':
    main()
