from typing import List, Optional

class DjVuLayer:
    """Represents a single layer of a DjVu page (e.g., foreground, background)."""
    def __init__(self, layer_type: str, image_data: bytes):
        self.layer_type = layer_type
        self.image_data = image_data

class DjVuPage:
    """Represents a single page within a DjVu document."""
    def __init__(self, page_num: int):
        self.page_num = page_num
        self.layers: List[DjVuLayer] = []

    def add_layer(self, layer: DjVuLayer):
        """Adds a layer to the page."""
        self.layers.append(layer)

class DjVuDocument:
    """Represents a full DjVu document."""
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.pages: List[DjVuPage] = []

    def add_page(self, page: DjVuPage):
        """Adds a page to the document."""
        self.pages.append(page)
