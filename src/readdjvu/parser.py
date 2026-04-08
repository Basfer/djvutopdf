import os
import re
import json
import subprocess
import shutil
import time
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
from .document import DjVuDocument, DjVuPage


class DjvuTextElement:
    """Represents a single text element with coordinates from DJVU."""
    def __init__(self, text: str, xmin: int, ymin: int, xmax: int, ymax: int):
        self.text = text
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax


class DjvuPageText:
    """Represents all text elements for a single page."""
    def __init__(self, page_num: int, width: int, height: int):
        self.page_num = page_num
        self.width = width
        self.height = height
        self.elements: List[DjvuTextElement] = []

class DjVuParser:
    """Parses a DjVu file using the ddjvu tool from DjVuLibre."""

    def __init__(self):
        self._check_ddjvu_installed()
        self._check_djvused_installed()

    def _check_ddjvu_installed(self):
        """Checks if the 'ddjvu' command is accessible."""
        if not shutil.which("ddjvu"):
            raise RuntimeError(
                "The 'ddjvu' command was not found. "
                "Please ensure DjVuLibre is installed and in your system's PATH."
            )

    def _check_djvused_installed(self):
        """Checks if the 'djvused' command is accessible."""
        if not shutil.which("djvused"):
            raise RuntimeError(
                "The 'djvused' command was not found. "
                "Please ensure DjVuLibre is installed and in your system's PATH."
            )

    def get_page_count(self, file_path: str) -> int:
        """Gets the total number of pages in the DjVu file."""
        try:
            result = subprocess.run(
                ["djvused", "-e", "n", file_path],
                capture_output=True,
                text=True,
                check=True
            )
            return int(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise RuntimeError(
                f"Failed to get page count for {file_path}. "
                "Ensure 'djvused' is installed and in your PATH. "
                f"Error: {e}"
            )

    def _convert_pnm_to_png(self, pnm_path: str, png_path: str):
        """
        Converts a PNM file to PNG format.
        """
        if os.path.exists(pnm_path):
            try:
                with Image.open(pnm_path) as img:
                    img.save(png_path, "PNG")
            except Exception as e:
                print(f"Warning: Could not convert '{pnm_path}' to PNG. Error: {e}")
        else:
            print(f"Warning: PNM file not found at '{pnm_path}', skipping conversion.")

    def _parse_sexpr(self, text: str) -> Any:
        """
        Parses S-expression from djvused print-txt output.
        Returns nested lists/dicts structure.
        """
        text = text.strip()
        pos = [0]  # Use list for mutable reference
        
        def skip_whitespace():
            while pos[0] < len(text) and text[pos[0]] in ' \t\n\r':
                pos[0] += 1
        
        def parse_string():
            """Parse quoted string with escape sequences."""
            if pos[0] >= len(text) or text[pos[0]] != '"':
                return None
            pos[0] += 1  # skip opening quote
            result = []
            while pos[0] < len(text):
                ch = text[pos[0]]
                if ch == '\\':
                    pos[0] += 1
                    if pos[0] < len(text):
                        esc = text[pos[0]]
                        if esc == 'n':
                            result.append('\n')
                        elif esc == 't':
                            result.append('\t')
                        elif esc == 'r':
                            result.append('\r')
                        elif esc == '\\':
                            result.append('\\')
                        elif esc == '"':
                            result.append('"')
                        else:
                            result.append(esc)
                        pos[0] += 1
                elif ch == '"':
                    pos[0] += 1  # skip closing quote
                    return ''.join(result)
                else:
                    result.append(ch)
                    pos[0] += 1
            return ''.join(result)
        
        def parse_list():
            """Parse a parenthesized list."""
            if pos[0] >= len(text) or text[pos[0]] != '(':
                return None
            pos[0] += 1  # skip opening paren
            result = []
            
            while True:
                skip_whitespace()
                if pos[0] >= len(text):
                    break
                if text[pos[0]] == ')':
                    pos[0] += 1  # skip closing paren
                    break
                elif text[pos[0]] == '(':
                    result.append(parse_list())
                elif text[pos[0]] == '"':
                    result.append(parse_string())
                else:
                    # Parse atom (number or symbol)
                    start = pos[0]
                    while pos[0] < len(text) and text[pos[0]] not in ' \t\n\r()':
                        pos[0] += 1
                    atom = text[start:pos[0]]
                    # Try to convert to int
                    try:
                        atom = int(atom)
                    except ValueError:
                        pass
                    result.append(atom)
            
            return result
        
        return parse_list()
    
    def _extract_text_elements(self, sexpr_data: Any) -> List[DjvuTextElement]:
        """
        Extract text elements with coordinates from parsed S-expression.
        Traverses the hierarchy and extracts text from word/char level.
        """
        elements = []
        
        if not isinstance(sexpr_data, list):
            return elements
        
        def traverse(node):
            if not isinstance(node, list) or len(node) < 6:
                return
            
            # Check if this is a text element: (type xmin ymin xmax ymax "text")
            if (isinstance(node[0], str) and 
                isinstance(node[1], int) and isinstance(node[2], int) and
                isinstance(node[3], int) and isinstance(node[4], int) and
                isinstance(node[5], str)):
                
                elem_type = node[0]
                xmin, ymin, xmax, ymax = node[1], node[2], node[3], node[4]
                text = node[5]
                
                # Extract at word level for better accuracy
                if elem_type == 'word' and text.strip():
                    elements.append(DjvuTextElement(text, xmin, ymin, xmax, ymax))
                elif elem_type == 'line' and len(node) == 6 and text.strip():
                    # Fallback to line level if no words
                    elements.append(DjvuTextElement(text, xmin, ymin, xmax, ymax))
                return
            
            # Traverse children
            for child in node[1:]:  # Skip the type name at index 0
                if isinstance(child, list):
                    traverse(child)
        
        # Handle page-level structure: (page xmin ymin xmax ymax ...)
        if len(sexpr_data) > 0 and sexpr_data[0] == 'page':
            for child in sexpr_data[5:]:  # Skip page header
                if isinstance(child, list):
                    traverse(child)
        
        return elements
    
    def _extract_text(self, page_num: int, file_path: str, output_dir: str) -> Optional[DjvuPageText]:
        """
        Extracts the text layer of a single page.
        Returns DjvuPageText object with text elements and page dimensions.
        """
        page_dir = os.path.join(output_dir, f"page_{page_num:04d}")
        
        command = ["djvused", "-e", f"select {page_num}; print-txt", file_path]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
            raw_text = result.stdout
            
            # Save raw output for debugging
            with open(os.path.join(page_dir, "text_raw.txt"), "w", encoding="utf-8") as f:
                f.write(raw_text)
            
            # Parse S-expression
            parsed = self._parse_sexpr(raw_text)
            
            if parsed and isinstance(parsed, list) and len(parsed) >= 5:
                # Extract page dimensions from (page xmin ymin xmax ymax ...)
                if parsed[0] == 'page':
                    width = parsed[3] - parsed[1]  # xmax - xmin
                    height = parsed[4] - parsed[2]  # ymax - ymin
                    
                    # Extract text elements
                    elements = self._extract_text_elements(parsed)
                    
                    page_text = DjvuPageText(page_num, width, height)
                    page_text.elements = elements
                    
                    # Save as JSON for debugging
                    json_data = {
                        'page_num': page_num,
                        'width': width,
                        'height': height,
                        'elements': [
                            {
                                'text': elem.text,
                                'xmin': elem.xmin,
                                'ymin': elem.ymin,
                                'xmax': elem.xmax,
                                'ymax': elem.ymax
                            }
                            for elem in elements
                        ]
                    }
                    with open(os.path.join(page_dir, "text.json"), "w", encoding="utf-8") as f:
                        json.dump(json_data, f, ensure_ascii=False, indent=2)
                    
                    return page_text
            
            return None
            
        except subprocess.CalledProcessError as e:
            # It is common for pages to not have a text layer, so we just log this as a warning.
            print(f"Warning: djvused failed to process page {page_num}. This may be because the page has no text layer. Error: {e.stderr}")
            return None


    def _process_page(self, page_num: int, file_path: str, output_dir: str, extract_text: bool):
        """
        Processes a single page of the DjVu file.
        Returns tuple of (DjVuPage, Optional[DjvuPageText]).
        """
        page_dir = os.path.join(output_dir, f"page_{page_num:04d}")
        os.makedirs(page_dir, exist_ok=True)

        print(f"  - Extracting page {page_num} and its layers...")

        full_pnm_path = os.path.join(page_dir, "full.pnm")
        full_png_path = os.path.join(page_dir, "full.png")
        fg_pnm_path = os.path.join(page_dir, "foreground.pnm")
        fg_png_path = os.path.join(page_dir, "foreground.png")
        bg_pnm_path = os.path.join(page_dir, "background.pnm")
        bg_png_path = os.path.join(page_dir, "background.png")
        mask_pnm_path = os.path.join(page_dir, "mask.pnm")
        mask_png_path = os.path.join(page_dir, "mask.png")

        self._run_ddjvu(["-page", str(page_num), file_path, full_pnm_path])
        self._convert_pnm_to_png(full_pnm_path, full_png_path)

        self._run_ddjvu_layers(file_path, page_num, fg_pnm_path, bg_pnm_path, mask_pnm_path)
        self._convert_pnm_to_png(fg_pnm_path, fg_png_path)
        self._convert_pnm_to_png(bg_pnm_path, bg_png_path)
        self._convert_pnm_to_png(mask_pnm_path, mask_png_path)

        page_text = None
        if extract_text:
            page_text = self._extract_text(page_num, file_path, output_dir)

        return (DjVuPage(page_num=page_num), page_text)

    def parse(self, file_path: str, output_dir: str, create_pdf: bool = False, threads: int = os.cpu_count(), keep_pages: bool = False, extract_text: bool = False):
        """
        Parses the DjVu file, extracts each page and its layers into the output directory.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")

        page_count = self.get_page_count(file_path)
        doc = DjVuDocument(file_path)

        print(f"Found {page_count} pages. Processing with {threads} workers...")

        page_texts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(self._process_page, i, file_path, output_dir, extract_text) for i in range(1, page_count + 1)]
            for future in concurrent.futures.as_completed(futures):
                djvu_page, page_text = future.result()
                doc.add_page(djvu_page)
                if page_text:
                    page_texts.append(page_text)

        if create_pdf:
            self._create_pdf(output_dir, page_count, page_texts if extract_text else None)

        if not keep_pages:
            print("Cleaning up page directories...")
            for i in range(1, page_count + 1):
                page_dir = os.path.join(output_dir, f"page_{i:04d}")
                if os.path.exists(page_dir):
                    shutil.rmtree(page_dir)

        print(f"Processing complete. Output is in {output_dir}")
        return doc

    def _create_pdf(self, output_dir: str, page_count: int, page_texts: Optional[List[DjvuPageText]] = None):
        """
        Creates a PDF from the extracted page images with optional text layer.
        Converts DJVU coordinates (origin at bottom-left) to PDF coordinates (origin at top-left).
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("Warning: PyMuPDF not installed. Installing text layer requires PyMuPDF.")
            print("Install with: pip install PyMuPDF")
            # Fallback to basic PDF creation without text layer
            self._create_pdf_basic(output_dir, page_count)
            return
        
        print("Creating PDF with text layer...")
        
        # Collect images
        images = []
        for i in range(1, page_count + 1):
            image_path = os.path.join(output_dir, f"page_{i:04d}", "full.png")
            if os.path.exists(image_path):
                images.append((i, image_path))
        
        if not images:
            print("No images found, skipping PDF creation.")
            return
        
        # Create PDF with first image
        pdf_path = os.path.join(output_dir, "output.pdf")
        first_idx, first_path = images[0]
        first_page_text = None
        if page_texts:
            first_page_text = next((pt for pt in page_texts if pt.page_num == first_idx), None)
        
        # Open first image with PyMuPDF
        doc = fitz.open()
        self._add_page_to_pdf(doc, first_path, first_page_text)
        
        # Add remaining pages
        for idx, image_path in images[1:]:
            page_text = None
            if page_texts:
                page_text = next((pt for pt in page_texts if pt.page_num == idx), None)
            self._add_page_to_pdf(doc, image_path, page_text)
        
        # Save PDF
        doc.save(pdf_path)
        doc.close()
        print(f"PDF created at {pdf_path}")
    
    def _add_page_to_pdf(self, doc, image_path: str, page_text: Optional[DjvuPageText]):
        """
        Adds a single page to the PDF document with text layer if available.
        """
        import fitz
        
        # Get image dimensions (not used for scaling, only for reference)
        # We use DJVU page dimensions for coordinate transformation
        img = fitz.open(image_path)
        img.close()
        
        # Insert page with image - this will create page with default A4 size
        pdf_page = doc.new_page()
        pdf_page.insert_image(pdf_page.rect, filename=image_path)
        
        # Get actual image bbox in PDF coordinates
        image_info = pdf_page.get_image_info()
        if not image_info:
            return
        
        img_bbox = image_info[0]['bbox']
        img_x0, img_y0, img_x1, img_y1 = img_bbox
        img_width_pdf = img_x1 - img_x0
        img_height_pdf = img_y1 - img_y0
        
        # Add text layer if available
        if page_text and page_text.elements:
            # DJVU: origin at bottom-left
            # PDF: origin at top-left
            # Conversion: y_pdf = page_height - y_djvu
            
            # Use DJVU page dimensions for scaling (not PNG image dimensions)
            # because DJVU coordinates are relative to the original page size
            djvu_width = page_text.width
            djvu_height = page_text.height
            
            # Calculate scale factors from DJVU page coords to PDF image coords
            scale_x = img_width_pdf / djvu_width
            scale_y = img_height_pdf / djvu_height
            
            print(f"  DEBUG: DJVU size={djvu_width}x{djvu_height}, "
                  f"PDF image size={img_width_pdf:.1f}x{img_height_pdf:.1f}, "
                  f"scale={scale_x:.4f}x{scale_y:.4f}")
            
            for elem in page_text.elements:
                if not elem.text.strip():
                    continue
                
                # Convert coordinates from DJVU to PDF
                # DJVU: (xmin, ymin, xmax, ymax) with origin at bottom-left
                # PDF: (x0, y0, x1, y1) with origin at top-left
                # In PDF, y0 < y1 (y0 is top, y1 is bottom)
                
                # Scale coordinates using DJVU page dimensions
                x_scaled = elem.xmin * scale_x
                x_width_scaled = (elem.xmax - elem.xmin) * scale_x
                y_top_scaled = elem.ymax * scale_y  # Top edge in image coords (larger Y in DJVU)
                y_bottom_scaled = elem.ymin * scale_y  # Bottom edge in image coords (smaller Y in DJVU)
                
                # Convert to PDF coordinates (origin at top-left, Y grows downward)
                x0 = img_x0 + x_scaled
                x1 = img_x0 + x_scaled + x_width_scaled
                
                # In PDF: top has smaller Y, bottom has larger Y
                # DJVU ymax (top) -> PDF smaller Y
                # DJVU ymin (bottom) -> PDF larger Y
                y0 = img_y0 + (img_height_pdf - y_top_scaled)  # Top edge (smaller Y)
                y1 = img_y0 + (img_height_pdf - y_bottom_scaled)  # Bottom edge (larger Y)
                
                # Calculate font size based on box height
                box_height = y1 - y0
                # Use 90% of box height for better readability
                font_size = max(8, min(36, box_height * 0.9))
                
                # Insert text at the correct position
                # Text insertion point is at the baseline
                text_point = fitz.Point(x0, y0 + font_size * 0.85)
                
                # Debug output
                print(f"  Inserting '{elem.text[:20]}': pos=({text_point.x:.1f}, {text_point.y:.1f}), "
                      f"bbox=({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f}), fontsize={font_size:.1f}, "
                      f"page_size=({pdf_page.rect.width:.1f}x{pdf_page.rect.height:.1f})")
                
                # Insert text using TextWriter for better Unicode support
                import os
                arial_font = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf')
                
                if os.path.exists(arial_font):
                    # Use TextWriter with custom font for proper Cyrillic support
                    tw = fitz.TextWriter(pdf_page.rect)
                    font = fitz.Font(fontfile=arial_font)
                    tw.append(
                        text_point,
                        elem.text,
                        fontsize=font_size,
                        font=font
                    )
                    tw.write_text(pdf_page, opacity=1.0)
                else:
                    # Fallback to insert_text
                    pdf_page.insert_text(
                        text_point,
                        elem.text,
                        fontsize=font_size,
                        color=(0, 0, 1),
                        render_mode=0
                    )
    
    def _create_pdf_basic(self, output_dir: str, page_count: int):
        """
        Creates a PDF from the extracted page images without text layer (fallback method).
        """
        print("Creating PDF without text layer...")
        images = []
        for i in range(1, page_count + 1):
            image_path = os.path.join(output_dir, f"page_{i:04d}", "full.png")
            if os.path.exists(image_path):
                images.append(Image.open(image_path))

        if images:
            pdf_path = os.path.join(output_dir, "output.pdf")
            images[0].save(
                pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:]
            )
            print(f"PDF created at {pdf_path}")

    def _run_ddjvu(self, args: list):
        """Helper to run the main ddjvu command."""
        command = ["ddjvu"] + args
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            time.sleep(0.1)
        except subprocess.CalledProcessError as e:
            print(f"Warning: ddjvu failed to process a page. Command: {' '.join(command)}. Error: {e}")
            print(f"Stderr: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                "The 'ddjvu' command was not found. "
                "Please ensure DjVuLibre is installed and in your system's PATH."
            )

    def _run_ddjvu_layers(self, file_path: str, page_num: int, fg_path: str, bg_path: str, mask_path: str):
        """
        Uses ddjvu's specific layer extraction options to save individual layers.
        """
        layer_commands = {
            "foreground": ["ddjvu", "-page", str(page_num), "-foreground", file_path, fg_path],
            "background": ["ddjvu", "-page", str(page_num), "-background", file_path, bg_path],
            "mask": ["ddjvu", "-page", str(page_num), "-black", file_path, mask_path]
        }

        for layer, command in layer_commands.items():
            try:
                subprocess.run(command, capture_output=True, text=True)
                time.sleep(0.1)
            except Exception as e:
                print(f"Could not extract '{layer}' layer for page {page_num}. Error: {e}")

