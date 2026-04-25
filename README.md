# EZ PDF Organizer
EZ PDF Organizer is a modern, fast, and 100% offline desktop application designed to make managing PDF files effortless. Inspired by ilovePDF website and built for AutoKerja product, it features a sleek drag-and-drop interface and visual page management, ensuring your sensitive documents never leave your local machine.

<img width="2293" height="1543" alt="image" src="https://github.com/user-attachments/assets/fd636787-84bc-45a4-8a07-96da53ff692e" />

<img width="2193" height="1548" alt="image" src="https://github.com/user-attachments/assets/982bc55b-5981-4d7a-a8af-43c434c09d85" />


## Features

* **📁 Merge PDFs:** Drag and drop multiple PDF files to combine them. Easily rearrange the file order before saving.
* **✂️ Split PDFs:** Extract every page into individual files or extract specific page ranges (e.g., 1-3, 4-6).
* **⮀ Reorder Pages:** Visually rearrange pages within a PDF. Drag and drop cards, or select pages and use the keyboard arrow keys for rapid sorting with auto-scroll tracking.
* **↻ Rotate Pages:** Rotate specific pages or entire documents by 90°, 180°, or 270° with a live visual preview.
* **🗜️ Compress PDFs:** Reduce file sizes for easy emailing with Low, Medium, and High compression profiles.
* **🗑️ Delete Pages:** Visually remove unwanted pages from the grid before saving a clean, final PDF.

## Privacy & Security

**100% Offline:** EZ PDF Organizer runs entirely on your local machine. No internet connection is required, no cloud processing is used, and your files are never uploaded to any external servers.

## Installation

**1. Clone the repository:**
git clone https://github.com/jijoeee/EZ-PDF-Organizer.git
cd ez-pdf-organizer

**2. Install dependencies:**
Make sure you have Python installed. Then, install the required libraries using pip:
pip install -r requirements.txt

**3. Run the application:**
python main.py

## Usage

* **Drag & Drop:** You can drag PDF files directly from your file explorer into the application window to load them instantly.
* **Keyboard Navigation (Reorder & Delete Tabs):** Click a page to select it, then use the **Up, Down, Left, and Right Arrow Keys** to quickly move it around the document. 
* **Multi-Select:** You can highlight multiple pages at once in the Reorder, Rotate, and Delete tabs to apply bulk actions.

## Built With

* **Python:** The core logic language.
* **CustomTkinter:** For the modern, dark/light mode compatible UI.
* **PyMuPDF (fitz):** For high-speed PDF processing and rendering.
* **Pillow:** For image and thumbnail manipulation.
* **TkinterDnD2:** For native OS drag-and-drop support.

## License

© 2026 AutoKerja. All rights reserved.
