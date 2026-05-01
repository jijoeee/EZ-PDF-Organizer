import os
import re
import threading
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as messagebox
import customtkinter as ctk
import fitz  # PyMuPDF
from PIL import Image, ImageTk
from tkinterdnd2 import TkinterDnD, DND_FILES

# internal version 1.5
# ==========================================
# 1. CORE UTILITY FUNCTIONS
# ==========================================

def format_size(size_bytes):
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"

def parse_page_ranges(range_str, total_pages):
    ranges = []
    if not range_str.strip(): return ranges
    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            s, e = part.split('-')
            ranges.append((int(s), int(e)))
        else:
            ranges.append((int(part), int(part)))
    for s, e in ranges:
        if s < 1 or e > total_pages or s > e:
            raise ValueError(f"Invalid range: {s}-{e}")
    return ranges

def generate_thumbnail(pdf_path, page_index=0, width=160, height=190):
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_index]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        pil_original = img.copy()
        img.thumbnail((width, height), Image.Resampling.LANCZOS)
        doc.close()
        return ImageTk.PhotoImage(img), pil_original
    except Exception:
        return None, None

# ==========================================
# 2. CORE PDF OPERATIONS
# ==========================================

def merge_pdfs(ordered_file_list, output_path):
    doc = fitz.open()
    for pdf_path in ordered_file_list:
        with fitz.open(pdf_path) as src:
            doc.insert_pdf(src)
    doc.save(output_path)
    doc.close()

def split_pdf(input_path, output_base_path, mode, ranges_str=None):
    src = fitz.open(input_path)
    base_dir = os.path.dirname(output_base_path)
    base_name = os.path.splitext(os.path.basename(output_base_path))[0]
    count = 0
    if mode == "extract_all":
        for i in range(len(src)):
            doc = fitz.open()
            doc.insert_pdf(src, from_page=i, to_page=i)
            doc.save(os.path.join(base_dir, f"{base_name}_{i+1:03d}.pdf"))
            doc.close()
            count += 1
    else:
        ranges = parse_page_ranges(ranges_str, len(src))
        for s, e in ranges:
            doc = fitz.open()
            doc.insert_pdf(src, from_page=s-1, to_page=e-1)
            suffix = f"{s}" if s == e else f"{s}-{e}"
            doc.save(os.path.join(base_dir, f"{base_name}_{suffix}.pdf"))
            doc.close()
            count += 1
    src.close()
    return count

def reorder_pdf(input_path, output_path, reordered_index_list):
    src = fitz.open(input_path)
    doc = fitz.open()
    for idx in reordered_index_list:
        doc.insert_pdf(src, from_page=idx, to_page=idx)
    doc.save(output_path)
    doc.close()
    src.close()

def rotate_pdf(input_path, output_path, rotations_dict):
    doc = fitz.open(input_path)
    for i, angle in rotations_dict.items():
        if angle != 0:
            page = doc[i]
            page.set_rotation((page.rotation + angle) % 360)
    doc.save(output_path)
    doc.close()

def compress_pdf(input_path, output_path, level):
    doc = fitz.open(input_path)
    if level == "Low":
        doc.save(output_path, deflate=False, garbage=0)
    elif level == "Medium":
        doc.save(output_path, deflate=True, garbage=3, clean=True)
    elif level == "High":
        new_doc = fitz.open()
        for page in doc:
            mat = fitz.Matrix(96/72, 96/72)
            pix = page.get_pixmap(matrix=mat)
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
        new_doc.save(output_path, deflate=True, garbage=4, clean=True)
        new_doc.close()
    doc.close()

def delete_pages(input_path, output_path, pages_to_delete):
    doc = fitz.open(input_path)
    for i in sorted(pages_to_delete, reverse=True):
        doc.delete_page(i)
    doc.save(output_path)
    doc.close()

# ==========================================
# 3. GUI COMPONENTS
# ==========================================

class DropZone(ctk.CTkFrame):
    def __init__(self, master, on_files_selected, multi=True):
        super().__init__(master, fg_color="#F5F5F5", corner_radius=0)
        self.on_files_selected = on_files_selected
        self.multi = multi
        
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(container, text="📄", font=("Arial", 60)).pack(pady=10)
        btn = ctk.CTkButton(container, text="Select PDF files" if multi else "Select PDF file", 
                            width=280, height=52, font=("Arial", 16, "bold"), 
                            fg_color="#2CC985", hover_color="#24a66d", command=self.browse)
        btn.pack(pady=10)
        ctk.CTkLabel(container, text="or drop PDFs here", font=("Arial", 14), text_color="#A0A0A0").pack()

    def browse(self):
        if self.multi:
            paths = fd.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
            if paths: self.on_files_selected(list(paths))
        else:
            path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf")])
            if path: self.on_files_selected([path])

class PDFCardGrid(ctk.CTkScrollableFrame):
    def __init__(self, master, app, mode="files", on_change=None, selection_color="#2CC985"):
        super().__init__(master, fg_color="#F5F5F5", orientation="vertical")
        self.app = app
        self.mode = mode 
        self.on_change = on_change
        self.selection_color = selection_color
        
        self.items = [] 
        self.cards = [] 
        self.last_cols = 0
        
        # Loading Progress Bar
        self.prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.prog_lbl = ctk.CTkLabel(self.prog_frame, text="Loading pages...", font=("Arial", 12, "bold"), text_color="#1F6AA5")
        self.prog_lbl.pack(side="left", padx=10)
        self.prog_bar = ctk.CTkProgressBar(self.prog_frame, progress_color="#2CC985")
        self.prog_bar.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        
        # Drop Indicator Line (Now Invisible)
        self.drop_indicator = ctk.CTkFrame(self, width=4, height=240, fg_color="transparent", corner_radius=2)

        # Floating Action Buttons
        self.fab_frame = ctk.CTkFrame(self.master, fg_color="transparent", bg_color="transparent")
        if self.mode == "files":
            self.btn_add = ctk.CTkButton(self.fab_frame, text="+", width=48, height=48, corner_radius=24, 
                                         font=("Arial", 24, "bold"), fg_color="#2CC985", hover_color="#24a66d", command=self.add_files)
            self.btn_add.pack(side="right", padx=10)
            self.btn_sort = ctk.CTkButton(self.fab_frame, text="↓A-Z", width=40, height=40, corner_radius=20, 
                                          fg_color="#A0A0A0", hover_color="#808080", command=self.sort_items)
            self.btn_sort.pack(side="right", padx=10)

        self.drag_item = None
        self.drag_moved = False
        self.start_x = 0
        self.start_y = 0
        self.drag_window = None
        
        self.bind("<Configure>", self.on_resize, add="+")
        
        # --- ADD THESE 4 LINES ---
        self.app.bind("<Left>", lambda e: self.move_selected_items("left"), add="+")
        self.app.bind("<Right>", lambda e: self.move_selected_items("right"), add="+")
        self.app.bind("<Up>", lambda e: self.move_selected_items("up"), add="+")
        self.app.bind("<Down>", lambda e: self.move_selected_items("down"), add="+")

    def get_cols(self):
        try:
            # Measure the main app window minus the sidebar (220px) and padding
            w = self.app.winfo_width() - 260
        except Exception:
            w = 900
            
        if w < 100: w = 900
        
        # Calculate how many fit, but set a STRICT LIMIT of 5 per row
        cols = max(1, w // 180)
        return min(cols, 5)
    
    def move_selected_items(self, direction):
        # 1. Ignore if this tab is not the one currently visible on screen
        if not self.winfo_ismapped(): return
        
        # 2. Ignore if the user is typing in a text box (like the "Page ranges" box)
        focus = self.app.focus_get()
        if focus and "entry" in str(focus).lower(): return

        # 3. Only allow moving in Tabs where drag-and-drop/reordering is enabled
        if self.mode not in ["files", "pages_reorder"]: return

        sel_indices = [i for i, item in enumerate(self.items) if item['selected']]
        if not sel_indices: return

        cols = self.get_cols()
        offset = 0
        if direction == "left": offset = -1
        elif direction == "right": offset = 1
        elif direction == "up": offset = -cols
        elif direction == "down": offset = cols

        # If moving forward, we process from right-to-left so items don't overwrite each other
        if offset > 0:
            sel_indices.reverse()

        # Block the move if it pushes the leading card completely off the grid boundaries
        if offset < 0 and sel_indices[0] + offset < 0: return 
        if offset > 0 and sel_indices[0] + offset >= len(self.items): return 

        # Perform the swaps
        for i in sel_indices:
            new_idx = i + offset
            
            item = self.items.pop(i)
            card = self.cards.pop(i)
            
            self.items.insert(new_idx, item)
            self.cards.insert(new_idx, card)
            
        self.layout_cards()
        if self.on_change: self.on_change()
        
        # --- AUTO-SCROLL TO FOLLOW SELECTION ---
        # Because we reverse the list for downward movement, sel_indices[0] 
        # ALWAYS represents the leading edge of the moving block of cards!
        leading_idx = sel_indices[0] + offset
        if 0 <= leading_idx < len(self.cards):
            self.scroll_to_view(self.cards[leading_idx])

    def scroll_to_view(self, card):
        # 1. Force the app to calculate the new grid layout immediately
        self.update_idletasks() 
        
        # 2. Get the hidden canvas that CustomTkinter uses for scrolling
        canvas = getattr(self, "_parent_canvas", None)
        if not canvas: return
        
        bbox = canvas.bbox("all")
        if not bbox: return
        
        frame_h = bbox[3]  # Total scrollable height
        canvas_h = canvas.winfo_height()  # Height of your visible window
        
        if frame_h <= canvas_h: return  # No need to scroll if everything fits
        
        top, bottom = canvas.yview()
        visible_top = top * frame_h
        visible_bottom = bottom * frame_h
        
        card_y = card.winfo_y()
        card_h = card.winfo_height()
        
        padding = 20 # Give it a little visual breathing room
        
        # If the card is slipping below the bottom edge...
        if (card_y + card_h + padding) > visible_bottom:
            new_top = (card_y + card_h + padding - canvas_h) / frame_h
            canvas.yview_moveto(new_top)
            
        # If the card is slipping above the top edge...
        elif (card_y - padding) < visible_top:
            new_top = max(0, (card_y - padding) / frame_h)
            canvas.yview_moveto(new_top)

    def pack_fabs(self):
        if self.mode == "files" and self.items:
            self.fab_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
        else:
            self.fab_frame.place_forget()

    def load_files(self, paths):
        for p in paths:
            self.items.append({'path': p, 'page': 0, 'thumb': None, 'pil_img': None, 'rotation': 0, 'selected': False, 'name': os.path.basename(p)})
        self.create_cards()
        self.load_thumbnails_async()

    def load_pages(self, path, total_pages):
        self.items = [{'path': path, 'page': i, 'thumb': None, 'pil_img': None, 'rotation': 0, 'selected': False, 'name': f"Page {i+1}"} for i in range(total_pages)]
        self.create_cards()
        self.load_thumbnails_async()

    def create_cards(self):
        for c in self.cards: c.destroy()
        self.cards.clear()
        
        for item in self.items:
            card = ctk.CTkFrame(self, width=160, height=240, corner_radius=8, fg_color="#FFFFFF", border_width=2)
            card.grid_propagate(False)
            card.configure(border_color=self.selection_color if item['selected'] else "#FFFFFF")
            
            lbl = ctk.CTkLabel(card, text="Loading...", text_color="#A0A0A0")
            lbl.place(relx=0.5, rely=0.45, anchor="center")
            
            name_disp = item['name']
            if len(name_disp) > 55: name_disp = name_disp[:52] + "..."
            name_lbl = ctk.CTkLabel(card, text=name_disp, font=("Arial", 11), text_color="#555555", wraplength=145, justify="center")
            name_lbl.place(relx=0.5, rely=0.81, anchor="n")
            
            self._bind_events(card)
            self._bind_events(lbl)
            self._bind_events(name_lbl)
            
            self.cards.append(card)
            
        self.layout_cards()
        self.pack_fabs()

    def load_thumbnails_async(self):
        total = len(self.items)
        if total == 0: return
        
        self.prog_bar.set(0)
        self.prog_lbl.configure(text="Loading 0%...")
        
        self.prog_frame.grid(row=0, column=0, columnspan=5, sticky="ew", padx=10, pady=10)
        
        def worker():
            for i, item in enumerate(self.items):
                try:
                    doc = fitz.open(item['path'])
                    page = doc[item['page']]
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat)
                    mode = "RGBA" if pix.alpha else "RGB"
                    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                    pil_orig = img.copy()
                    
                    img.thumbnail((140, 190), Image.Resampling.LANCZOS)
                    doc.close()
                    
                    self.app.after(0, lambda idx=i, image=img, orig=pil_orig: self.apply_image_to_card(idx, image, orig))
                except Exception:
                    pass
                
                pct = int(((i + 1) / total) * 100)
                self.app.after(0, lambda val=(i + 1) / total: self.prog_bar.set(val))
                self.app.after(0, lambda txt=f"Loading {pct}%...": self.prog_lbl.configure(text=txt))
                
            self.app.after(0, self.prog_frame.grid_forget)
            
        threading.Thread(target=worker, daemon=True).start()

    def apply_image_to_card(self, i, img, pil_orig):
        if i < len(self.items):
            self.items[i]['pil_img'] = pil_orig
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
            self.items[i]['thumb'] = ctk_img
            
            card = self.cards[i]
            for w in card.winfo_children():
                if isinstance(w, ctk.CTkLabel) and w.cget("text") == "Loading...":
                    w.destroy()
            
            img_lbl = ctk.CTkLabel(card, image=ctk_img, text="")
            img_lbl.place(relx=0.5, rely=0.45, anchor="center")
            self._bind_events(img_lbl)

    def on_resize(self, event=None):
        cols = self.get_cols()
        if cols != self.last_cols:
            self.last_cols = cols
            self.layout_cards()

    def layout_cards(self):
        cols = self.get_cols()
        for card in self.cards:
            card.grid_forget()
            
        for i, card in enumerate(self.cards):
            row, col = divmod(i, cols)
            card.grid(row=row + 1, column=col, padx=10, pady=10)

    def update_card_visuals(self):
        for i, card in enumerate(self.cards):
            card.configure(border_color=self.selection_color if self.items[i]['selected'] else "#FFFFFF")

    def _find_card_index(self, widget):
        curr = widget
        while curr and curr != self:
            if curr in self.cards:
                return self.cards.index(curr)
            curr = curr.master
        return None

    def _bind_events(self, widget):
        widget.bind("<ButtonPress-1>", self.on_press)
        if self.mode in ["files", "pages_reorder"]:
            widget.bind("<B1-Motion>", self.on_drag)
        widget.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        idx = self._find_card_index(event.widget)
        if idx is not None:
            self.drag_item = idx
            self.drag_moved = False
            # Record exact starting coordinates for the threshold check
            self.start_x = event.x_root
            self.start_y = event.y_root

    def on_drag(self, event):
        if self.mode not in ["files", "pages_reorder"]: return
        if self.drag_item is None: return
        
        # Check if the mouse has moved more than 5 pixels
        if abs(event.x_root - self.start_x) > 5 or abs(event.y_root - self.start_y) > 5:
            self.drag_moved = True

        # Prevent dragging visuals if the item hasn't been selected yet
        if not self.items[self.drag_item]['selected']:
            return
            
        # Prevent dragging visuals if we haven't crossed the 5-pixel movement threshold
        if not self.drag_moved:
            return
        
        if not self.drag_window:
            self.drag_window = tk.Toplevel(self)
            self.drag_window.overrideredirect(True)
            self.drag_window.attributes('-topmost', True)
            card_copy = ctk.CTkFrame(self.drag_window, width=160, height=240, fg_color="#FFFFFF")
            card_copy.pack()
            if self.items[self.drag_item].get('thumb'):
                ctk.CTkLabel(card_copy, image=self.items[self.drag_item]['thumb'], text="", fg_color="transparent").place(relx=0.5, rely=0.45, anchor="center")
        
        x, y = event.x_root - 80, event.y_root - 110
        self.drag_window.geometry(f"160x240+{x}+{y}")
        
        mx, my = event.x_root, event.y_root
        
        # Find the geometrically closest card to eliminate "dead zones" in the grid
        closest_idx = len(self.items)
        min_dist = float('inf')
        is_right_half = False
        
        for i, card in enumerate(self.cards):
            cx, cy = card.winfo_rootx(), card.winfo_rooty()
            cw, ch = card.winfo_width(), card.winfo_height()
            
            # Center point of this card
            card_mid_x = cx + cw / 2
            card_mid_y = cy + ch / 2
            
            # Calculate distance from mouse to card center
            dist = (mx - card_mid_x)**2 + (my - card_mid_y)**2
            if dist < min_dist:
                min_dist = dist
                closest_idx = i
                is_right_half = (mx >= card_mid_x)
                
        # Snap the blue line to the closest card boundary visually
        if min_dist < 40000: # Approx 200px threshold so it doesn't snap if mouse is very far away
            card = self.cards[closest_idx]
            if is_right_half:
                self.current_drop_target = closest_idx + 1
                ind_x = card.winfo_x() + card.winfo_width() + 4
            else:
                self.current_drop_target = closest_idx
                ind_x = card.winfo_x() - 8
            ind_y = card.winfo_y()
        else:
            # Default to the end if mouse is far outside the entire grid area
            self.current_drop_target = len(self.items)
            if self.cards:
                card = self.cards[-1]
                ind_x = card.winfo_x() + card.winfo_width() + 4
                ind_y = card.winfo_y()
            else:
                ind_x, ind_y = 10, 10
                
        # The line drawing code has been completely removed!

    def on_release(self, event):
        # The line hiding code has been removed!
        
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None

        if self.drag_item is None: 
            return

        # If it was just a click (mouse didn't move past threshold)
        if not self.drag_moved:
            self.items[self.drag_item]['selected'] = not self.items[self.drag_item]['selected']
            self.update_card_visuals()
            if self.on_change: self.on_change()
        else:
            # It was a drag. Ensure the item is selected AND we have a target before dropping
            if self.items[self.drag_item]['selected'] and hasattr(self, 'current_drop_target'):
                target_idx = self.current_drop_target
                dragged_item = self.items[self.drag_item]

                selected_items, selected_cards = [], []
                for i in reversed(range(len(self.items))):
                    if self.items[i]['selected']:
                        selected_items.insert(0, self.items.pop(i))
                        selected_cards.insert(0, self.cards.pop(i))
                        if i < target_idx:
                            target_idx -= 1
                
                target_idx = min(target_idx, len(self.items))
                for si, sc in zip(reversed(selected_items), reversed(selected_cards)):
                    self.items.insert(target_idx, si)
                    self.cards.insert(target_idx, sc)
                
                self.layout_cards()
                if self.on_change: self.on_change()

        self.drag_item = None
        self.drag_moved = False

    def add_files(self):
        paths = fd.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if paths: self.load_files(list(paths))

    def sort_items(self):
        combined = list(zip(self.items, self.cards))
        def natural_keys(pair):
            text = pair[0]['name']
            return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]
            
        combined.sort(key=natural_keys)
        self.items, self.cards = zip(*combined)
        self.items, self.cards = list(self.items), list(self.cards)
        self.layout_cards()

    def toggle_all(self, state):
        for item in self.items: item['selected'] = state
        self.update_card_visuals()
        if self.on_change: self.on_change()


# ==========================================
# 4. TAB IMPLEMENTATIONS
# ==========================================

class BaseTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.in_path = ""
        
        self.main_area = ctk.CTkFrame(self, fg_color="#F5F5F5", corner_radius=0)
        self.main_area.pack(side="left", fill="both", expand=True)
        
        self.top_ctrl = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.btn_clear_files = ctk.CTkButton(self.top_ctrl, text="Clear Files", border_width=1, border_color="#E05252", 
                                             fg_color="transparent", text_color="#E05252", hover_color="#FFEBEE", command=self.reset_tab)
        
        self.sidebar = ctk.CTkFrame(self, width=220, fg_color="#FFFFFF", corner_radius=0)
        self.sidebar.pack_propagate(False)
        self.sidebar.pack(side="right", fill="y")
        
        self.prog = ctk.CTkProgressBar(self.sidebar, progress_color="#2CC985")
        self.prog.set(0)

    def has_unsaved_work(self):
        return self.in_path != ""

    def reset_tab(self):
        self.in_path = ""
        
        if hasattr(self, 'preview_frame'):
            for w in self.preview_frame.winfo_children(): w.destroy()
            self.preview_frame.pack_forget()
            
        if hasattr(self, 'card_grid'):
            self.card_grid.items.clear()
            for c in self.card_grid.cards: c.destroy()
            self.card_grid.cards.clear()
            self.card_grid.pack_forget()
            
        self.top_ctrl.pack_forget()
        
        if hasattr(self, 'result_frame'):
            for w in self.result_frame.winfo_children(): w.destroy()
            
        if hasattr(self, 'lbl_range'):
            self.lbl_range.configure(text="Page ranges (x - y):")
            self.range_var.set("")
            
        if hasattr(self, 'lbl_summ'):
            self.lbl_summ.configure(text="Selected: 0 pages")
            
        if hasattr(self, 'lbl_target'):
            self.lbl_target.configure(text="Target: All pages")
            
        self.drop_zone.pack(fill="both", expand=True)
        self.prog.pack_forget()


class TabMerge(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.drop_zone = DropZone(self.main_area, self.on_files_added)
        self.drop_zone.pack(fill="both", expand=True)
        
        self.btn_clear_files.pack(side="right", padx=15)
        
        self.card_grid = PDFCardGrid(self.main_area, self.app, mode="files")
        self.setup_sidebar()

    def has_unsaved_work(self):
        return len(self.card_grid.items) > 0

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#E3F2FD", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Drag and drop the cards\nto change the merge order.", text_color="#1F6AA5", justify="left").pack(padx=10, pady=10)
        
        self.btn_action = ctk.CTkButton(self.sidebar, text="Merge PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", hover_color="#24a66d", command=self.run_action)
        self.btn_action.pack(fill="x", padx=15, pady=20)
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_files_added(self, paths):
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=5)
        self.card_grid.pack(fill="both", expand=True)
        self.card_grid.load_files(paths)

    def run_action(self):
        if len(self.card_grid.items) < 2: return self.app.update_status("❌ Need at least 2 files.")
        
        out_path = fd.asksaveasfilename(title="Save Merged PDF", defaultextension=".pdf", initialfile="merged_output.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return

        self.btn_action.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        threading.Thread(target=self._task, args=(out_path,), daemon=True).start()

    def _task(self, out_path):
        try:
            paths = [item['path'] for item in self.card_grid.items]
            merge_pdfs(paths, out_path)
            self.app.update_status("✅ Merge complete!")
            self.app.show_success_sidebar(self.result_frame, f"Merged {len(paths)} files", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_action.configure(state="normal")


class TabSplit(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.drop_zone = DropZone(self.main_area, self.on_file_added, multi=False)
        self.drop_zone.pack(fill="both", expand=True)
        self.btn_clear_files.pack(side="right", padx=15)
        self.preview_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.setup_sidebar()

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#E3F2FD", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Choose how you want\nto split your PDF.", text_color="#1F6AA5", justify="left").pack(padx=10, pady=10)
        
        self.mode_var = ctk.StringVar(value="extract_all")
        ctk.CTkRadioButton(self.sidebar, text="Extract All Pages", variable=self.mode_var, value="extract_all", text_color="#333333").pack(anchor="w", padx=15, pady=5)
        ctk.CTkRadioButton(self.sidebar, text="By Page Range", variable=self.mode_var, value="range", text_color="#333333").pack(anchor="w", padx=15, pady=5)
        
        self.lbl_range = ctk.CTkLabel(self.sidebar, text="Page ranges (x - y):", text_color="#333333", font=("Arial", 12, "bold"))
        self.lbl_range.pack(anchor="w", padx=15, pady=(10,0))
        
        self.range_var = ctk.StringVar()
        ctk.CTkEntry(self.sidebar, textvariable=self.range_var, placeholder_text="e.g. 1-3, 4-6").pack(fill="x", padx=15)
        
        self.btn_action = ctk.CTkButton(self.sidebar, text="Split PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", hover_color="#24a66d", command=self.run_action)
        self.btn_action.pack(fill="x", padx=15, pady=20)
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_file_added(self, paths):
        self.in_path = paths[0]
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=5)
        self.preview_frame.pack(expand=True)
        
        doc = fitz.open(self.in_path)
        total = len(doc)
        self.lbl_range.configure(text=f"Page ranges (1 - {total}):")
        
        for w in self.preview_frame.winfo_children(): w.destroy()
        ctk.CTkLabel(self.preview_frame, text="📄", font=("Arial", 80)).pack(pady=10)
        ctk.CTkLabel(self.preview_frame, text=os.path.basename(self.in_path), font=("Arial", 16, "bold"), text_color="#333333").pack()
        ctk.CTkLabel(self.preview_frame, text=f"{total} pages", text_color="#555555").pack()
        doc.close()

    def run_action(self):
        if not self.in_path: return
        
        out_path = fd.asksaveasfilename(title="Save Split PDFs", defaultextension=".pdf", initialfile="split_result.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return

        self.btn_action.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        threading.Thread(target=self._task, args=(out_path,), daemon=True).start()

    def _task(self, out_path):
        try:
            c = split_pdf(self.in_path, out_path, self.mode_var.get(), self.range_var.get())
            self.app.update_status(f"✅ Split complete! {c} files created.")
            self.app.show_success_sidebar(self.result_frame, f"Split into {c} files", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_action.configure(state="normal")


class TabReorder(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.drop_zone = DropZone(self.main_area, self.on_file_added, multi=False)
        self.drop_zone.pack(fill="both", expand=True)
        
        ctk.CTkButton(self.top_ctrl, text="Select All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(True)).pack(side="left", padx=(15, 5))
        ctk.CTkButton(self.top_ctrl, text="Deselect All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(False)).pack(side="left", padx=5)
        self.btn_clear_files.pack(side="right", padx=(5, 15))
        ctk.CTkButton(self.top_ctrl, text="Reset Order", fg_color="transparent", border_width=1, border_color="#E05252", text_color="#E05252", command=self.reset_order).pack(side="right", padx=5)
        
        self.card_grid = PDFCardGrid(self.main_area, self.app, mode="pages_reorder")
        self.setup_sidebar()

    def reset_order(self):
        combined = list(zip(self.card_grid.items, self.card_grid.cards))
        combined.sort(key=lambda x: x[0]['page'])
        self.card_grid.items, self.card_grid.cards = zip(*combined)
        self.card_grid.items, self.card_grid.cards = list(self.card_grid.items), list(self.card_grid.cards)
        self.card_grid.layout_cards()
        self.app.update_status("Order reset.")

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#E3F2FD", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Drag pages to change\ntheir order. Multi-select\nsupported.", text_color="#1F6AA5", justify="left").pack(padx=10, pady=10)
        
        self.btn_action = ctk.CTkButton(self.sidebar, text="Save PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", command=self.run_action)
        self.btn_action.pack(fill="x", padx=15, pady=20)
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_file_added(self, paths):
        self.in_path = paths[0]
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=10)
        self.card_grid.pack(fill="both", expand=True)
        doc = fitz.open(self.in_path)
        self.card_grid.load_pages(self.in_path, len(doc))
        doc.close()

    def run_action(self):
        if not self.in_path: return
        
        out_path = fd.asksaveasfilename(title="Save Reordered PDF", defaultextension=".pdf", initialfile="reordered.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return

        self.btn_action.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        threading.Thread(target=self._task, args=(out_path,), daemon=True).start()

    def _task(self, out_path):
        try:
            indices = [item['page'] for item in self.card_grid.items]
            reorder_pdf(self.in_path, out_path, indices)
            self.app.update_status("✅ Pages reordered and saved.")
            self.app.show_success_sidebar(self.result_frame, "Saved new order", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_action.configure(state="normal")


class TabRotate(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.drop_zone = DropZone(self.main_area, self.on_file_added, multi=False)
        self.drop_zone.pack(fill="both", expand=True)
        
        ctk.CTkButton(self.top_ctrl, text="Select All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(True)).pack(side="left", padx=(15, 5))
        ctk.CTkButton(self.top_ctrl, text="Deselect All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(False)).pack(side="left", padx=5)
        self.btn_clear_files.pack(side="right", padx=(5, 15))
        ctk.CTkButton(self.top_ctrl, text="Reset Rotations", fg_color="transparent", border_width=1, border_color="#E05252", text_color="#E05252", command=self.reset_rotations).pack(side="right", padx=5)
        
        self.card_grid = PDFCardGrid(self.main_area, self.app, mode="pages", on_change=self.update_summary)
        self.setup_sidebar()

    def reset_rotations(self):
        for i, item in enumerate(self.card_grid.items):
            item['rotation'] = 0
            if item['pil_img']:
                pil_copy = item['pil_img'].copy()
                pil_copy.thumbnail((140, 190), Image.Resampling.LANCZOS)
                self.card_grid.apply_image_to_card(i, pil_copy, item['pil_img'])
        self.app.update_status("Rotations reset.")

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#E3F2FD", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Select pages to rotate.\nUnselected = rotate all.", text_color="#1F6AA5", justify="left").pack(padx=10, pady=10)
        
        self.lbl_target = ctk.CTkLabel(self.sidebar, text="Target: All pages", font=("Arial", 12, "bold"), text_color="#333333")
        self.lbl_target.pack(anchor="w", padx=15, pady=(5,5))
        
        self.rot_var = ctk.IntVar(value=90)
        rot_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        rot_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkRadioButton(rot_frame, text="↻ 90°", variable=self.rot_var, value=90, text_color="#333333").pack(anchor="w", pady=2)
        ctk.CTkRadioButton(rot_frame, text="↺ 90°", variable=self.rot_var, value=270, text_color="#333333").pack(anchor="w", pady=2)
        ctk.CTkRadioButton(rot_frame, text="180°", variable=self.rot_var, value=180, text_color="#333333").pack(anchor="w", pady=2)
        
        self.btn_preview = ctk.CTkButton(self.sidebar, text="Rotate Preview", height=40, font=("Arial", 14), fg_color="#1F6AA5", command=self.run_preview)
        self.btn_preview.pack(fill="x", padx=15, pady=(15,5))

        self.btn_save = ctk.CTkButton(self.sidebar, text="Save PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", command=self.run_save)
        self.btn_save.pack(fill="x", padx=15, pady=5)
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_file_added(self, paths):
        self.in_path = paths[0]
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=10)
        self.card_grid.pack(fill="both", expand=True)
        doc = fitz.open(self.in_path)
        self.card_grid.load_pages(self.in_path, len(doc))
        doc.close()

    def update_summary(self):
        sel = sum(1 for item in self.card_grid.items if item['selected'])
        if sel == 0:
            self.lbl_target.configure(text="Target: All pages")
        else:
            self.lbl_target.configure(text=f"Target: {sel} selected pages")

    def run_preview(self):
        angle = self.rot_var.get()
        sel_count = sum(1 for item in self.card_grid.items if item['selected'])
        
        for i, item in enumerate(self.card_grid.items):
            if sel_count == 0 or item['selected']:
                item['rotation'] = (item.get('rotation', 0) + angle) % 360
                if item['pil_img']:
                    rot_pil = item['pil_img'].rotate(-item['rotation'], expand=True)
                    rot_pil.thumbnail((140, 190), Image.Resampling.LANCZOS)
                    self.card_grid.apply_image_to_card(i, rot_pil, item['pil_img'])

    def run_save(self):
        if not self.in_path: return
        
        out_path = fd.asksaveasfilename(title="Save Rotated PDF", defaultextension=".pdf", initialfile="rotated.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return

        self.btn_save.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        
        rotations = {item['page']: item.get('rotation', 0) for item in self.card_grid.items}
        threading.Thread(target=self._task, args=(out_path, rotations), daemon=True).start()

    def _task(self, out_path, rotations):
        try:
            rotate_pdf(self.in_path, out_path, rotations)
            self.app.update_status("✅ Rotation saved.")
            self.app.show_success_sidebar(self.result_frame, "Saved Successfully", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_save.configure(state="normal")


class TabCompress(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.drop_zone = DropZone(self.main_area, self.on_file_added, multi=False)
        self.drop_zone.pack(fill="both", expand=True)
        self.btn_clear_files.pack(side="right", padx=15)
        self.preview_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.setup_sidebar()

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#E3F2FD", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Smaller file size is ideal\nfor sending via email.", text_color="#1F6AA5", justify="left").pack(padx=10, pady=10)
        
        self.lvl_var = ctk.StringVar(value="Medium")
        for lvl in ["Low", "Medium", "High"]:
            ctk.CTkRadioButton(self.sidebar, text=lvl, variable=self.lvl_var, value=lvl, text_color="#333333").pack(anchor="w", padx=15, pady=5)
            
        self.btn_action = ctk.CTkButton(self.sidebar, text="Compress PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", command=self.run_action)
        self.btn_action.pack(fill="x", padx=15, pady=20)
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_file_added(self, paths):
        self.in_path = paths[0]
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=5)
        self.preview_frame.pack(expand=True)
        sz = format_size(os.path.getsize(self.in_path))
        for w in self.preview_frame.winfo_children(): w.destroy()
        ctk.CTkLabel(self.preview_frame, text="🗜️", font=("Arial", 80)).pack(pady=10)
        ctk.CTkLabel(self.preview_frame, text=os.path.basename(self.in_path), font=("Arial", 16, "bold"), text_color="#333333").pack()
        ctk.CTkLabel(self.preview_frame, text=f"Original size: {sz}", text_color="#555555").pack()

    def run_action(self):
        if not self.in_path: return
        
        out_path = fd.asksaveasfilename(title="Save Compressed PDF", defaultextension=".pdf", initialfile="compressed.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return

        self.btn_action.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        threading.Thread(target=self._task, args=(out_path,), daemon=True).start()

    def _task(self, out_path):
        try:
            compress_pdf(self.in_path, out_path, self.lvl_var.get())
            orig, new = os.path.getsize(self.in_path), os.path.getsize(out_path)
            pct = int((1 - new/orig)*100) if orig > 0 else 0
            self.app.update_status(f"✅ Compressed: {format_size(orig)} → {format_size(new)} (-{pct}%)")
            self.app.show_success_sidebar(self.result_frame, f"Saved {pct}% space", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_action.configure(state="normal")


class TabDelete(BaseTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.original_page_count = 0
        self.drop_zone = DropZone(self.main_area, self.on_file_added, multi=False)
        self.drop_zone.pack(fill="both", expand=True)
        
        ctk.CTkButton(self.top_ctrl, text="Select All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(True)).pack(side="left", padx=(15, 5))
        ctk.CTkButton(self.top_ctrl, text="Deselect All", fg_color="transparent", border_width=1, border_color="#1F6AA5", text_color="#1F6AA5", command=lambda: self.card_grid.toggle_all(False)).pack(side="left", padx=5)
        self.btn_clear_files.pack(side="right", padx=(5, 15))
        
        self.card_grid = PDFCardGrid(self.main_area, self.app, mode="pages", on_change=self.update_summary, selection_color="#E05252")
        self.setup_sidebar()

    def setup_sidebar(self):
        tip = ctk.CTkFrame(self.sidebar, fg_color="#FFEBEE", corner_radius=8)
        tip.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(tip, text="ℹ️ Select pages to remove.\nOriginal file is unchanged.", text_color="#C62828", justify="left").pack(padx=10, pady=10)
        
        self.lbl_summ = ctk.CTkLabel(self.sidebar, text="Selected: 0 pages", font=("Arial", 12, "bold"), text_color="#333333")
        self.lbl_summ.pack(anchor="w", padx=15, pady=(5,5))
        
        # New Delete Button
        self.btn_delete = ctk.CTkButton(self.sidebar, text="🗑 Delete Selected", height=40, font=("Arial", 14, "bold"), fg_color="#E05252", hover_color="#c0392b", command=self.remove_selected_from_ui)
        self.btn_delete.pack(fill="x", padx=15, pady=(15, 5))

        # Re-styled Save Button
        self.btn_action = ctk.CTkButton(self.sidebar, text="Save PDF →", height=52, font=("Arial", 16, "bold"), fg_color="#2CC985", hover_color="#24a66d", command=self.run_action)
        self.btn_action.pack(fill="x", padx=15, pady=(5, 20))
        
        self.result_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.result_frame.pack(fill="both", expand=True, padx=0, pady=5)

    def on_file_added(self, paths):
        self.in_path = paths[0]
        self.drop_zone.pack_forget()
        self.top_ctrl.pack(fill="x", pady=10)
        self.card_grid.pack(fill="both", expand=True)
        doc = fitz.open(self.in_path)
        
        # Track the original page count so we know what is missing later
        self.original_page_count = len(doc) 
        self.card_grid.load_pages(self.in_path, len(doc))
        doc.close()

    def update_summary(self):
        sel = sum(1 for item in self.card_grid.items if item['selected'])
        self.lbl_summ.configure(text=f"Selected: {sel} pages")

    def remove_selected_from_ui(self):
        # Find which items are currently highlighted in red
        sel_indices = [i for i, item in enumerate(self.card_grid.items) if item['selected']]
        
        if not sel_indices: 
            return self.app.update_status("❌ Select at least 1 page to delete.")
        if len(sel_indices) == len(self.card_grid.items): 
            return self.app.update_status("❌ Cannot delete all pages.")
        
        # Pop them from the grid completely (in reverse so we don't mess up list indexing!)
        for i in reversed(sel_indices):
            self.card_grid.items.pop(i)
            card = self.card_grid.cards.pop(i)
            card.destroy()
            
        # Re-draw the grid
        self.card_grid.layout_cards()
        self.update_summary()
        self.app.update_status(f"🗑 {len(sel_indices)} pages removed from view. Click Save PDF when done.")

    def run_action(self):
        # Figure out which pages are physically missing from the UI vs the original file
        remaining = set(item['page'] for item in self.card_grid.items)
        original = set(range(self.original_page_count))
        already_deleted_from_ui = list(original - remaining)
        
        # Also grab any pages that are currently highlighted red but haven't been "deleted" yet
        currently_selected = [item['page'] for item in self.card_grid.items if item['selected']]
        
        # Combine them to get the final list of pages to cut from the PDF
        final_to_delete = list(set(already_deleted_from_ui + currently_selected))

        if not final_to_delete: return self.app.update_status("❌ No pages deleted yet.")
        if len(final_to_delete) == self.original_page_count: return self.app.update_status("❌ Cannot delete all pages.")
        
        out_path = fd.asksaveasfilename(title="Save Edited PDF", defaultextension=".pdf", initialfile="edited.pdf", filetypes=[("PDF", "*.pdf")])
        if not out_path: return
        
        self.btn_action.configure(state="disabled")
        self.btn_delete.configure(state="disabled")
        self.prog.pack(fill="x", padx=15)
        self.prog.start()
        threading.Thread(target=self._task, args=(out_path, final_to_delete,), daemon=True).start()

    def _task(self, out_path, sel):
        try:
            delete_pages(self.in_path, out_path, sel)
            self.app.update_status(f"✅ {len(sel)} pages deleted. Saved.")
            self.app.show_success_sidebar(self.result_frame, f"Deleted {len(sel)} pages", out_path)
        except Exception as e:
            self.app.update_status(f"❌ Error: {str(e)}")
        finally:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_action.configure(state="normal")
            self.btn_delete.configure(state="normal")


# ==========================================
# 5. MAIN APPLICATION WINDOW
# ==========================================

class Tk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class EZPDFApp(Tk):
    def __init__(self):
        super().__init__()
        self.title("EZ PDF Organizer  |  AutoKerja")
        self.geometry("1150x750")
        self.minsize(900, 600)
        self.configure(fg_color="#F0F0F0")
        
        # Top Bar
        top_bar = ctk.CTkFrame(self, fg_color="#FFFFFF", height=60, corner_radius=0)
        top_bar.pack(fill="x", side="top")
        
        ctk.CTkLabel(top_bar, text="EZ PDF Organizer", font=("Arial", 18, "bold"), text_color="#333333").pack(side="left", padx=(20,5), pady=15)
        ctk.CTkLabel(top_bar, text="by AutoKerja", font=("Arial", 11), text_color="#A0A0A0").pack(side="left", pady=18)
        
        ctk.CTkButton(top_bar, text="About", width=50, fg_color="transparent", text_color="#A0A0A0", hover_color="#F0F0F0", command=self.show_about).pack(side="right", padx=20)

        # Tab Navigation
        self.tab_container = ctk.CTkFrame(self, fg_color="#FFFFFF", height=50, corner_radius=0)
        self.tab_container.pack(fill="x", pady=(0, 2))
        
        self.frames = {}
        self.buttons = {}
        tabs = ["📁 Merge PDF", "✂ Split PDF", "⮀ Reorder Pages", "↻ Rotate Pages", "🗜 Compress PDF", "🗑 Delete Pages"]
        
        for t in tabs:
            btn = ctk.CTkButton(self.tab_container, text=t, fg_color="transparent", text_color="#808080", 
                                font=("Arial", 13), hover_color="#F5F5F5", border_width=1, border_color="#DDDDDD", corner_radius=6,
                                command=lambda name=t: self.show_tab(name))
            btn.pack(side="left", padx=6, pady=8)
            self.buttons[t] = btn
            
        self.frames["📁 Merge PDF"] = TabMerge(self, self)
        self.frames["✂ Split PDF"] = TabSplit(self, self)
        self.frames["⮀ Reorder Pages"] = TabReorder(self, self)
        self.frames["↻ Rotate Pages"] = TabRotate(self, self)
        self.frames["🗜 Compress PDF"] = TabCompress(self, self)
        self.frames["🗑 Delete Pages"] = TabDelete(self, self)
        
        # Status Bar
        self.status_bar = ctk.CTkFrame(self, fg_color="#E0E0E0", height=28, corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_label = ctk.CTkLabel(self.status_bar, text="Ready.", font=("Arial", 11, "italic"), text_color="#555555")
        self.status_label.pack(side="left", padx=12)

        self.current_tab = None
        self.show_tab(tabs[0])
        
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.handle_global_drop)

    def show_tab(self, name):
        if self.current_tab and self.current_tab != name:
            current_frame = self.frames[self.current_tab]
            if current_frame.has_unsaved_work():
                if messagebox.askyesno("Unsaved Work", f"You have files loaded in {self.current_tab}.\nSwitching tabs will reset it. Continue?"):
                    current_frame.reset_tab()
                else:
                    return
        
        self.current_tab = name
        
        for btn_name, btn in self.buttons.items():
            btn.configure(text_color="#808080", font=("Arial", 13), fg_color="transparent", border_color="#DDDDDD")
        self.buttons[name].configure(text_color="#2CC985", font=("Arial", 13, "bold"), fg_color="#F0F9F5", border_color="#2CC985")
        
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill="both", expand=True)

    def handle_global_drop(self, event):
        paths = self.splitlist(event.data)
        pdf_paths = [p for p in paths if p.lower().endswith(".pdf")]
        if not pdf_paths:
            self.update_status("❌ Error: Only .pdf files are accepted.")
            return
        
        for frame in self.frames.values():
            if frame.winfo_ismapped():
                if hasattr(frame, 'on_file_added'): frame.on_file_added(pdf_paths)
                elif hasattr(frame, 'on_files_added'): frame.on_files_added(pdf_paths)

    def update_status(self, msg):
        self.status_label.configure(text=msg)

    def show_success_sidebar(self, parent_frame, msg, out_path):
        succ = ctk.CTkFrame(parent_frame, fg_color="#E8F5E9", corner_radius=8)
        succ.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(succ, text=f"✅ {msg}", text_color="#2E7D32", font=("Arial", 12, "bold")).pack(pady=10)
        
        if os.path.isdir(out_path):
            cmd = lambda p=out_path: os.startfile(p)
        else:
            cmd = lambda p=out_path: os.startfile(os.path.dirname(p))
            
        ctk.CTkButton(succ, text="Open Folder", fg_color="#FFFFFF", text_color="#333333", border_width=1, border_color="#CCCCCC", hover_color="#F0F0F0", command=cmd).pack(fill="x", padx=10, pady=(0,10))

    def show_about(self):
        messagebox.showinfo("About", "EZ PDF Organizer v1.0\nby AutoKerja\n\n100% Offline PDF Tool\nYour files never leave your PC.\n\n© 2026 AutoKerja")

# ==========================================
# 6. APP EXECUTION
# ==========================================

if __name__ == "__main__":
    app = EZPDFApp()
    app.mainloop()
