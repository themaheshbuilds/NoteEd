import io
# pyrefly: ignore [missing-import]
import fitz

class PDFService:
    @staticmethod
    def extract_pages_as_images(file_bytes, max_pages=10):
        """
        Extracts pages of a PDF document as PNG image bytes.
        Returns a list of tuples: (page_number, image_bytes)
        """
        pages = []
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = min(len(doc), max_pages)
            
            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                # Render page to a pixmap (using high resolution 150 DPI)
                zoom = 150 / 72
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convert pixmap to PNG bytes
                img_bytes = pix.tobytes("png")
                pages.append((page_num + 1, img_bytes))
                
            doc.close()
        except Exception as e:
            print(f"Error extracting PDF pages: {e}")
        
        return pages

