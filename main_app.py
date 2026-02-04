import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
import os
import numpy as np
import json
from database import Database

try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except:
    DEEPFACE_AVAILABLE = False

class PhotoAIApp:
    def __init__(self):
        self.db = Database()
        self.window = ctk.CTk()
        self.window.title("PhotoAI Organizer v2")
        self.window.geometry("1300x900")
        ctk.set_appearance_mode("dark")
        self.setup_tabs()
    
    def setup_tabs(self):
        self.tabview = ctk.CTkTabview(self.window)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.tab_scan = self.tabview.add("1. Scan")
        self.tab_cluster = self.tabview.add("2. Cluster")
        self.tab_recognize = self.tabview.add("3. Recognize")
        self.tab_review = self.tabview.add("4. Review")
        self.tab_organize = self.tabview.add("5. Organize")
        
        self.setup_scan_tab()
        self.setup_cluster_tab()
        self.setup_recognize_tab()
        self.setup_review_tab()
        self.setup_organize_tab()
    
    def setup_scan_tab(self):
        left = ctk.CTkFrame(self.tab_scan, width=350)
        left.pack(side="left", fill="y", padx=10, pady=10)
        left.pack_propagate(False)
        
        ctk.CTkLabel(left, text="SOURCE FOLDERS", font=("Arial", 16, "bold")).pack(pady=10)
        
        btn_frame = ctk.CTkFrame(left)
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkButton(btn_frame, text="Add Folder", command=self.add_folder, width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Remove", command=self.remove_folder, width=80, fg_color="gray").pack(side="left", padx=5)
        
        self.folder_listbox = tk.Listbox(left, height=6, bg="#2b2b2b", fg="white", font=("Arial", 10))
        self.folder_listbox.pack(fill="x", padx=10, pady=10)
        self.refresh_folder_list()
        
        ctk.CTkLabel(left, text="DETECTION SETTINGS", font=("Arial", 14, "bold")).pack(pady=10)
        
        self.min_face_size = ctk.IntVar(value=20)
        size_frame = ctk.CTkFrame(left)
        size_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(size_frame, text="Min face size:").pack(side="left")
        ctk.CTkEntry(size_frame, textvariable=self.min_face_size, width=50).pack(side="left", padx=5)
        ctk.CTkLabel(size_frame, text="px").pack(side="left")
        
        ctk.CTkLabel(left, text="Face Detector:").pack(anchor="w", padx=10, pady=5)
        self.detector_var = ctk.StringVar(value="opencv")
        
        det_frame1 = ctk.CTkFrame(left)
        det_frame1.pack(fill="x", padx=10)
        ctk.CTkRadioButton(det_frame1, text="OpenCV (fast)", variable=self.detector_var, value="opencv").pack(side="left", padx=5)
        ctk.CTkRadioButton(det_frame1, text="SSD", variable=self.detector_var, value="ssd").pack(side="left", padx=5)
        
        det_frame2 = ctk.CTkFrame(left)
        det_frame2.pack(fill="x", padx=10)
        ctk.CTkRadioButton(det_frame2, text="MTCNN", variable=self.detector_var, value="mtcnn").pack(side="left", padx=5)
        ctk.CTkRadioButton(det_frame2, text="RetinaFace", variable=self.detector_var, value="retinaface").pack(side="left", padx=5)
        
        self.resize_for_detection = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(left, text="Resize large images", variable=self.resize_for_detection).pack(anchor="w", padx=10, pady=10)
        
        ctk.CTkButton(left, text="SCAN ALL PHOTOS", command=self.scan_all_photos, 
                     font=("Arial", 14, "bold"), height=50, fg_color="green").pack(fill="x", padx=10, pady=15)
        
        self.scan_progress = ctk.CTkProgressBar(left, width=300)
        self.scan_progress.pack(pady=5)
        self.scan_progress.set(0)
        
        self.scan_status = ctk.CTkLabel(left, text="Ready to scan", wraplength=300)
        self.scan_status.pack(pady=5)
        
        right = ctk.CTkFrame(self.tab_scan)
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(right, text="SCAN RESULTS", font=("Arial", 16, "bold")).pack(pady=10)
        
        stats_frame = ctk.CTkFrame(right)
        stats_frame.pack(fill="x", padx=20, pady=10)
        
        self.stat_labels = {}
        for key, label in [('total_photos', 'Total Photos'), ('scanned', 'Scanned'), 
                           ('solo', 'Solo (1 face) - BEST'), ('duo', 'Duo (2 faces)'),
                           ('group', 'Group (3+)'), ('no_faces', 'No Faces'), ('total_faces', 'Total Faces')]:
            f = ctk.CTkFrame(stats_frame)
            f.pack(fill="x", pady=3)
            ctk.CTkLabel(f, text=f"{label}:", width=200, anchor="w", font=("Arial", 12)).pack(side="left")
            self.stat_labels[key] = ctk.CTkLabel(f, text="0", font=("Arial", 14, "bold"))
            self.stat_labels[key].pack(side="left")
        
        ctk.CTkButton(right, text="Refresh Stats", command=self.refresh_stats).pack(pady=10)
        
        ctk.CTkLabel(right, text="PREVIEW", font=("Arial", 14, "bold")).pack(pady=10)
        
        preview_btns = ctk.CTkFrame(right)
        preview_btns.pack(fill="x", padx=20)
        
        for cat in ['solo', 'duo', 'group', 'no_faces']:
            ctk.CTkButton(preview_btns, text=cat.replace('_', ' ').title(), 
                         command=lambda c=cat: self.preview_category(c), width=90).pack(side="left", padx=5)
        
        self.preview_scroll = ctk.CTkScrollableFrame(right, height=300)
        self.preview_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.refresh_stats()
    
    def add_folder(self):
        folder = filedialog.askdirectory(title="Select Folder")
        if folder:
            self.db.add_folder(folder, "source")
            self.refresh_folder_list()
    
    def remove_folder(self):
        sel = self.folder_listbox.curselection()
        if sel:
            item = self.folder_listbox.get(sel[0])
            fid = int(item.split("]")[0].replace("[", ""))
            self.db.remove_folder(fid)
            self.refresh_folder_list()
    
    def refresh_folder_list(self):
        self.folder_listbox.delete(0, tk.END)
        for fid, path in self.db.get_folders("source"):
            self.folder_listbox.insert(tk.END, f"[{fid}] {path}")
    
    def refresh_stats(self):
        stats = self.db.get_stats()
        for key in self.stat_labels:
            self.stat_labels[key].configure(text=str(stats.get(key, 0)))
    
    def detect_faces_in_image(self, path):
        detector = self.detector_var.get()
        min_size = self.min_face_size.get()
        
        try:
            img = Image.open(path)
            scale = 1.0
            
            if self.resize_for_detection.get():
                max_dim = 1200
                if max(img.size) > max_dim:
                    scale = max_dim / max(img.size)
                    new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
                    img = img.resize(new_size, Image.LANCZOS)
            
            temp_path = "temp_detect.jpg"
            img.save(temp_path, quality=95)
            
            detected = DeepFace.extract_faces(
                img_path=temp_path,
                detector_backend=detector,
                enforce_detection=False,
                align=False
            )
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            good_faces = []
            for face in detected:
                area = face['facial_area']
                x = int(area['x'] / scale)
                y = int(area['y'] / scale)
                w = int(area['w'] / scale)
                h = int(area['h'] / scale)
                
                if w >= min_size and h >= min_size:
                    good_faces.append({
                        'x': x, 'y': y, 'w': w, 'h': h,
                        'confidence': face.get('confidence', 0.5),
                        'size': w * h
                    })
            
            return good_faces
            
        except:
            return []
    
    def scan_all_photos(self):
        if not DEEPFACE_AVAILABLE:
            messagebox.showerror("Error", "DeepFace not installed!")
            return
        
        folders = self.db.get_folders("source")
        if not folders:
            messagebox.showwarning("Warning", "Add folders first!")
            return
        
        self.scan_status.configure(text="Finding photos...")
        self.window.update()
        
        exts = ('.jpg', '.jpeg', '.png', '.bmp')
        total_added = 0
        
        for fid, path in folders:
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(exts):
                        fp = os.path.join(root, file)
                        try:
                            sz = os.path.getsize(fp)
                            if sz > 5000:
                                if self.db.add_photo(fp, file, fid, sz):
                                    total_added += 1
                        except:
                            pass
        
        self.scan_status.configure(text=f"Found {total_added} new photos. Detecting...")
        self.window.update()
        
        photos = self.db.get_unscanned_photos()
        total = len(photos)
        
        if total == 0:
            self.scan_status.configure(text="No new photos to scan")
            self.refresh_stats()
            return
        
        for i, (pid, path, filename) in enumerate(photos):
            progress = (i + 1) / total
            self.scan_progress.set(progress)
            self.scan_status.configure(text=f"Scanning {i+1}/{total}...")
            self.window.update()
            
            faces = self.detect_faces_in_image(path)
            face_count = len(faces)
            
            if face_count == 0:
                category = 'no_faces'
            elif face_count == 1:
                category = 'solo'
            elif face_count == 2:
                category = 'duo'
            else:
                category = 'group'
            
            for face in faces:
                self.db.add_face(pid, face['x'], face['y'], face['w'], face['h'], 
                                face['confidence'], face['size'])
            
            self.db.update_photo_scan(pid, face_count, category)
        
        self.scan_progress.set(1)
        self.scan_status.configure(text=f"Done! Scanned {total} photos")
        self.refresh_stats()
        messagebox.showinfo("Done", f"Scanned {total} photos!\n\nGo to Tab 2 to cluster.")
    
    def preview_category(self, category):
        for w in self.preview_scroll.winfo_children():
            w.destroy()
        
        photos = self.db.get_photos_by_category(category)
        
        if not photos:
            ctk.CTkLabel(self.preview_scroll, text=f"No {category} photos").pack(pady=20)
            return
        
        ctk.CTkLabel(self.preview_scroll, text=f"{len(photos)} {category} photos", 
                    font=("Arial", 12, "bold")).pack(pady=5)
        
        row = None
        for i, (pid, path, fn, fc) in enumerate(photos[:50]):
            if i % 4 == 0:
                row = ctk.CTkFrame(self.preview_scroll)
                row.pack(fill="x", pady=5)
            
            item = ctk.CTkFrame(row, fg_color="gray25")
            item.pack(side="left", padx=5)
            
            try:
                img = Image.open(path)
                faces = self.db.get_faces_for_photo(pid)
                if faces:
                    draw = ImageDraw.Draw(img)
                    for face in faces:
                        fid, x, y, w, h, conf, cid, personid = face
                        draw.rectangle([x, y, x+w, y+h], outline="lime", width=3)
                
                img.thumbnail((150, 150))
                photo = ImageTk.PhotoImage(img)
                
                lbl = tk.Label(item, image=photo, bg="#2b2b2b")
                lbl.image = photo
                lbl.pack()
            except:
                ctk.CTkLabel(item, text="[Error]", width=150, height=150).pack()
            
            ctk.CTkLabel(item, text=f"{fc} face(s)", font=("Arial", 10)).pack()
    
    def setup_cluster_tab(self):
        top = ctk.CTkFrame(self.tab_cluster)
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top, text="STEP 1: CLUSTER SOLO PHOTOS", font=("Arial", 18, "bold")).pack(side="left", padx=10)
        
        self.cluster_status = ctk.CTkLabel(top, text="")
        self.cluster_status.pack(side="right", padx=20)
        
        btn_frame = ctk.CTkFrame(self.tab_cluster)
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkButton(btn_frame, text="1. Extract Embeddings", command=self.extract_embeddings, width=160).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="2. Run Clustering", command=self.run_clustering, width=140, fg_color="green").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Clear", command=self.clear_clusters, width=80, fg_color="darkred").pack(side="left", padx=10)
        
        threshold_frame = ctk.CTkFrame(btn_frame)
        threshold_frame.pack(side="left", padx=20)
        ctk.CTkLabel(threshold_frame, text="Similarity:").pack(side="left")
        self.threshold_var = ctk.DoubleVar(value=0.55)
        self.threshold_slider = ctk.CTkSlider(threshold_frame, from_=0.3, to=0.9, variable=self.threshold_var, width=120)
        self.threshold_slider.pack(side="left", padx=5)
        self.threshold_label = ctk.CTkLabel(threshold_frame, text="0.55")
        self.threshold_label.pack(side="left")
        self.threshold_slider.configure(command=lambda v: self.threshold_label.configure(text=f"{float(v):.2f}"))
        
        ctk.CTkLabel(btn_frame, text="Lower=stricter", text_color="gray").pack(side="left", padx=5)
        
        info = ctk.CTkLabel(self.tab_cluster, text="This clusters SOLO photos only (1 face per photo). Name each cluster, then go to Tab 3 to find more photos.", 
                           text_color="yellow", wraplength=800)
        info.pack(pady=5)
        
        self.cluster_scroll = ctk.CTkScrollableFrame(self.tab_cluster)
        self.cluster_scroll.pack(fill="both", expand=True, padx=10, pady=10)
    
    def extract_embeddings(self):
        if not DEEPFACE_AVAILABLE:
            messagebox.showerror("Error", "DeepFace not installed!")
            return
        
        cursor = self.db.conn.cursor()
        # ONLY solo photos
        cursor.execute('''SELECT f.id, f.photo_id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NULL AND p.category = 'solo' ''')
        
        faces = cursor.fetchall()
        total = len(faces)
        
        if total == 0:
            messagebox.showinfo("Info", "All done! Click 'Run Clustering'")
            return
        
        self.cluster_status.configure(text=f"Processing {total} faces...")
        self.window.update()
        
        extracted = 0
        for i, (fid, pid, x, y, w, h, path) in enumerate(faces):
            self.cluster_status.configure(text=f"Processing {i+1}/{total}...")
            self.window.update()
            
            try:
                img = Image.open(path)
                
                # Validate coordinates
                x = max(0, min(x, img.width - 1))
                y = max(0, min(y, img.height - 1))
                w = min(w, img.width - x)
                h = min(h, img.height - y)
                
                if w < 20 or h < 20:
                    continue
                
                pad = int(min(w, h) * 0.2)
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(img.width, x + w + pad)
                y2 = min(img.height, y + h + pad)
                
                face_img = img.crop((x1, y1, x2, y2))
                
                if face_img.width < 10 or face_img.height < 10:
                    continue
                    
                face_img = face_img.resize((160, 160))
                
                temp_path = "temp_emb.jpg"
                face_img.save(temp_path, quality=95)
                
                result = DeepFace.represent(temp_path, model_name='Facenet', enforce_detection=False)
                
                if result:
                    self.db.update_face_embedding(fid, result[0]['embedding'])
                    extracted += 1
                
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"Error: {e}")
                pass
        
        self.cluster_status.configure(text=f"Extracted {extracted}")
        messagebox.showinfo("Done", f"Extracted {extracted} embeddings.\n\nClick 'Run Clustering'")
    
    def run_clustering(self):
        cursor = self.db.conn.cursor()
        # ONLY solo photos
        cursor.execute('''SELECT f.id, f.embedding FROM faces f 
                         JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NOT NULL AND p.category = 'solo' ''')
        
        faces = cursor.fetchall()
        
        if len(faces) < 2:
            messagebox.showwarning("Warning", "Need at least 2 faces!\n\nRun 'Extract Embeddings' first.")
            return
        
        self.cluster_status.configure(text="Clustering...")
        self.window.update()
        
        self.db.clear_clusters()
        
        face_data = []
        for fid, emb_json in faces:
            try:
                emb = json.loads(emb_json)
                face_data.append({'id': fid, 'embedding': np.array(emb)})
            except:
                pass
        
        threshold = self.threshold_var.get()
        clusters = []
        
        for face in face_data:
            best_cluster = None
            best_sim = -1
            
            for cluster in clusters:
                sims = []
                for cf in cluster['faces']:
                    dot = np.dot(face['embedding'], cf['embedding'])
                    norm = np.linalg.norm(face['embedding']) * np.linalg.norm(cf['embedding'])
                    if norm > 0:
                        sims.append(dot / norm)
                
                if sims:
                    avg_sim = np.mean(sims)
                    if avg_sim > best_sim:
                        best_sim = avg_sim
                        best_cluster = cluster
            
            if best_cluster and best_sim >= threshold:
                best_cluster['faces'].append(face)
            else:
                clusters.append({'faces': [face]})
        
        clusters.sort(key=lambda c: len(c['faces']), reverse=True)
        
        for cluster in clusters:
            cluster_id = self.db.create_cluster()
            for face in cluster['faces']:
                self.db.update_face_cluster(face['id'], cluster_id)
        
        self.cluster_status.configure(text=f"{len(clusters)} clusters")
        self.show_clusters()
        
        large = sum(1 for c in clusters if len(c['faces']) >= 3)
        messagebox.showinfo("Done", f"{len(clusters)} groups found!\n{large} have 3+ faces\n\nName clusters, then go to Tab 3!")
    
    def clear_clusters(self):
        if messagebox.askyesno("Confirm", "Clear all clusters?"):
            self.db.clear_clusters()
            self.show_clusters()
    
    def show_clusters(self):
        for w in self.cluster_scroll.winfo_children():
            w.destroy()
        
        clusters = self.db.get_all_clusters()
        
        if not clusters:
            ctk.CTkLabel(self.cluster_scroll, text="No clusters.\n\n1. Extract Embeddings\n2. Run Clustering", 
                        font=("Arial", 14)).pack(pady=50)
            return
        
        large = sum(1 for c in clusters if c[4] >= 3)
        ctk.CTkLabel(self.cluster_scroll, text=f"{len(clusters)} clusters | {large} with 3+ faces",
                    font=("Arial", 12, "bold")).pack(pady=10)
        
        for cid, name, fc, pid, count in clusters:
            if count == 0:
                continue
            
            frame = ctk.CTkFrame(self.cluster_scroll, fg_color="gray20")
            frame.pack(fill="x", pady=10, padx=10)
            
            header = ctk.CTkFrame(frame)
            header.pack(fill="x", padx=10, pady=5)
            
            color = "lime" if count >= 5 else "yellow" if count >= 3 else "gray"
            stars = "★★★" if count >= 5 else "★★" if count >= 3 else "★" if count >= 2 else ""
            
            ctk.CTkLabel(header, text=f"{stars} #{cid}", font=("Arial", 12, "bold")).pack(side="left", padx=5)
            ctk.CTkLabel(header, text=f"({count})", text_color=color, font=("Arial", 12, "bold")).pack(side="left", padx=5)
            
            name_var = ctk.StringVar(value=name or "")
            ctk.CTkEntry(header, textvariable=name_var, width=150, placeholder_text="Name...").pack(side="left", padx=10)
            
            def save(c=cid, v=name_var):
                n = v.get().strip()
                if n:
                    pid = self.db.add_person(n)
                    self.db.update_cluster_name(c, n)
                    self.db.update_cluster_person(c, pid)
                    self.cluster_status.configure(text=f"Saved: {n}")
                    self.show_clusters()
            
            ctk.CTkButton(header, text="Save", width=60, command=save).pack(side="left", padx=5)
            
            if name:
                ctk.CTkLabel(header, text="✓", text_color="lime", font=("Arial", 16)).pack(side="left")
            
            # Show face thumbnails
            faces = self.db.get_faces_by_cluster(cid)
            thumb = ctk.CTkFrame(frame)
            thumb.pack(fill="x", padx=10, pady=5)
            
            for i, (fid, photo_id, x, y, w, h, path) in enumerate(faces[:12]):
                try:
                    img = Image.open(path)
                    
                    # Validate and fix coordinates
                    x = max(0, min(x, img.width - 1))
                    y = max(0, min(y, img.height - 1))
                    w = min(w, img.width - x)
                    h = min(h, img.height - y)
                    
                    if w < 10 or h < 10:
                        continue
                    
                    face_img = img.crop((x, y, x+w, y+h))
                    face_img = face_img.resize((70, 70))
                    photo = ImageTk.PhotoImage(face_img)
                    
                    lbl = tk.Label(thumb, image=photo, bg="#2b2b2b")
                    lbl.image = photo
                    lbl.pack(side="left", padx=2)
                except:
                    pass
            
            if len(faces) > 12:
                ctk.CTkLabel(thumb, text=f"+{len(faces)-12}").pack(side="left", padx=5)
    
    def setup_recognize_tab(self):
        """Tab 3: Use named people to find them in ALL photos"""
        top = ctk.CTkFrame(self.tab_recognize)
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top, text="STEP 2: FIND PEOPLE IN ALL PHOTOS", font=("Arial", 18, "bold")).pack(side="left", padx=10)
        
        self.recog_status = ctk.CTkLabel(top, text="")
        self.recog_status.pack(side="right", padx=20)
        
        info = ctk.CTkLabel(self.tab_recognize, 
                           text="This will search GROUP and DUO photos for people you've named in Tab 2.\nFirst, name at least one cluster in Tab 2!", 
                           text_color="yellow", wraplength=800)
        info.pack(pady=10)
        
        btn_frame = ctk.CTkFrame(self.tab_recognize)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(btn_frame, text="1. Extract ALL Face Embeddings", command=self.extract_all_embeddings, width=220).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="2. Find Named People", command=self.recognize_people, width=180, fg_color="green").pack(side="left", padx=10)
        
        threshold_frame = ctk.CTkFrame(btn_frame)
        threshold_frame.pack(side="left", padx=20)
        ctk.CTkLabel(threshold_frame, text="Match threshold:").pack(side="left")
        self.recog_threshold = ctk.DoubleVar(value=0.55)
        ctk.CTkSlider(threshold_frame, from_=0.4, to=0.8, variable=self.recog_threshold, width=100).pack(side="left", padx=5)
        self.recog_thresh_label = ctk.CTkLabel(threshold_frame, text="0.55")
        self.recog_thresh_label.pack(side="left")
        
        self.recog_scroll = ctk.CTkScrollableFrame(self.tab_recognize)
        self.recog_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.show_named_people()
    
    def extract_all_embeddings(self):
        """Extract embeddings from ALL faces (group, duo) that don't have them yet"""
        if not DEEPFACE_AVAILABLE:
            messagebox.showerror("Error", "DeepFace not installed!")
            return
        
        cursor = self.db.conn.cursor()
        cursor.execute('''SELECT f.id, f.photo_id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NULL''')
        
        faces = cursor.fetchall()
        total = len(faces)
        
        if total == 0:
            messagebox.showinfo("Info", "All faces have embeddings!\n\nClick 'Find Named People'")
            return
        
        self.recog_status.configure(text=f"Processing {total} faces...")
        self.window.update()
        
        extracted = 0
        for i, (fid, pid, x, y, w, h, path) in enumerate(faces):
            self.recog_status.configure(text=f"Processing {i+1}/{total}...")
            self.window.update()
            
            try:
                img = Image.open(path)
                
                x = max(0, min(x, img.width - 1))
                y = max(0, min(y, img.height - 1))
                w = min(w, img.width - x)
                h = min(h, img.height - y)
                
                if w < 20 or h < 20:
                    continue
                
                pad = int(min(w, h) * 0.2)
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(img.width, x + w + pad)
                y2 = min(img.height, y + h + pad)
                
                face_img = img.crop((x1, y1, x2, y2))
                
                if face_img.width < 10 or face_img.height < 10:
                    continue
                    
                face_img = face_img.resize((160, 160))
                
                temp_path = "temp_emb.jpg"
                face_img.save(temp_path, quality=95)
                
                result = DeepFace.represent(temp_path, model_name='Facenet', enforce_detection=False)
                
                if result:
                    self.db.update_face_embedding(fid, result[0]['embedding'])
                    extracted += 1
                
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
        
        self.recog_status.configure(text=f"Extracted {extracted}")
        messagebox.showinfo("Done", f"Extracted {extracted} embeddings.\n\nNow click 'Find Named People'")
    
    def recognize_people(self):
        """Match unnamed faces to named people"""
        cursor = self.db.conn.cursor()
        
        # Get all named people and their face embeddings
        cursor.execute('''SELECT p.id, p.name FROM people p''')
        people = cursor.fetchall()
        
        if not people:
            messagebox.showwarning("Warning", "No named people!\n\nGo to Tab 2 and name some clusters first.")
            return
        
        # Build person embeddings (average of all their faces)
        person_embeddings = {}
        for person_id, name in people:
            cursor.execute('''SELECT f.embedding FROM faces f WHERE f.person_id = ? AND f.embedding IS NOT NULL''', (person_id,))
            embs = cursor.fetchall()
            if embs:
                embeddings = [np.array(json.loads(e[0])) for e in embs]
                person_embeddings[person_id] = {
                    'name': name,
                    'embedding': np.mean(embeddings, axis=0)
                }
        
        if not person_embeddings:
            messagebox.showwarning("Warning", "Named people have no embeddings!")
            return
        
        # Get all unassigned faces with embeddings
        cursor.execute('''SELECT f.id, f.embedding FROM faces f WHERE f.person_id IS NULL AND f.embedding IS NOT NULL''')
        unassigned = cursor.fetchall()
        
        if not unassigned:
            messagebox.showinfo("Info", "No unassigned faces to match!")
            return
        
        self.recog_status.configure(text=f"Matching {len(unassigned)} faces...")
        self.window.update()
        
        threshold = self.recog_threshold.get()
        matched = 0
        
        for fid, emb_json in unassigned:
            try:
                emb = np.array(json.loads(emb_json))
                
                best_person = None
                best_sim = -1
                
                for person_id, data in person_embeddings.items():
                    dot = np.dot(emb, data['embedding'])
                    norm = np.linalg.norm(emb) * np.linalg.norm(data['embedding'])
                    if norm > 0:
                        sim = dot / norm
                        if sim > best_sim:
                            best_sim = sim
                            best_person = person_id
                
                if best_person and best_sim >= threshold:
                    self.db.update_face_person(fid, best_person)
                    matched += 1
            except:
                pass
        
        self.recog_status.configure(text=f"Matched {matched} faces!")
        self.show_named_people()
        messagebox.showinfo("Done", f"Found {matched} additional faces!\n\nGo to Tab 4 to review.")
    
    def show_named_people(self):
        for w in self.recog_scroll.winfo_children():
            w.destroy()
        
        people = self.db.get_all_people()
        
        if not people:
            ctk.CTkLabel(self.recog_scroll, text="No named people yet.\n\nGo to Tab 2 and name some clusters!",
                        font=("Arial", 14)).pack(pady=50)
            return
        
        ctk.CTkLabel(self.recog_scroll, text="Named People (will search for these):",
                    font=("Arial", 14, "bold")).pack(pady=10)
        
        for pid, name, count in people:
            frame = ctk.CTkFrame(self.recog_scroll, fg_color="gray25")
            frame.pack(fill="x", pady=5, padx=10)
            ctk.CTkLabel(frame, text=f"{name}: {count} photos", font=("Arial", 12)).pack(side="left", padx=10, pady=5)
    
    def setup_review_tab(self):
        top = ctk.CTkFrame(self.tab_review)
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top, text="Filter:").pack(side="left", padx=10)
        
        self.review_filter = ctk.StringVar(value="All")
        self.review_menu = ctk.CTkOptionMenu(top, variable=self.review_filter, values=["All"], command=self.filter_review)
        self.review_menu.pack(side="left", padx=5)
        
        ctk.CTkButton(top, text="Refresh", command=self.refresh_review).pack(side="left", padx=10)
        
        self.review_scroll = ctk.CTkScrollableFrame(self.tab_review)
        self.review_scroll.pack(fill="both", expand=True, padx=10, pady=10)
    
    def refresh_review(self):
        people = self.db.get_all_people()
        names = ["All"] + [p[1] for p in people]
        self.review_menu.configure(values=names)
        self.filter_review("All")
    
    def filter_review(self, choice):
        for w in self.review_scroll.winfo_children():
            w.destroy()
        
        people = self.db.get_all_people()
        
        if not people:
            ctk.CTkLabel(self.review_scroll, text="No people yet.\n\nName clusters in Tab 2!",
                        font=("Arial", 14)).pack(pady=50)
            return
        
        if choice == "All":
            for p in people:
                self.show_person(p[0], p[1], p[2])
        else:
            for p in people:
                if p[1] == choice:
                    self.show_person(p[0], p[1], p[2])
                    break
    
    def show_person(self, person_id, name, count):
        frame = ctk.CTkFrame(self.review_scroll, fg_color="gray20")
        frame.pack(fill="x", pady=10, padx=10)
        
        ctk.CTkLabel(frame, text=f"{name} ({count})", font=("Arial", 14, "bold")).pack(anchor="w", padx=10, pady=5)
        
        faces = self.db.get_faces_by_person(person_id)
        thumb = ctk.CTkFrame(frame)
        thumb.pack(fill="x", padx=10, pady=5)
        
        for i, (fid, photo_id, x, y, w, h, path) in enumerate(faces[:15]):
            try:
                img = Image.open(path)
                draw = ImageDraw.Draw(img)
                draw.rectangle([x, y, x+w, y+h], outline="lime", width=3)
                img.thumbnail((120, 120))
                photo = ImageTk.PhotoImage(img)
                
                lbl = tk.Label(thumb, image=photo, bg="#2b2b2b")
                lbl.image = photo
                lbl.pack(side="left", padx=2)
            except:
                pass
        
        if len(faces) > 15:
            ctk.CTkLabel(thumb, text=f"+{len(faces)-15}").pack(side="left", padx=10)
    
    def setup_organize_tab(self):
        ctk.CTkLabel(self.tab_organize, text="ORGANIZE", font=("Arial", 18, "bold")).pack(pady=20)
        
        options = ctk.CTkFrame(self.tab_organize)
        options.pack(fill="x", padx=20, pady=10)
        
        self.org_mode = ctk.StringVar(value="people")
        modes = ctk.CTkFrame(options)
        modes.pack(fill="x", pady=5)
        ctk.CTkRadioButton(modes, text="By People", variable=self.org_mode, value="people").pack(side="left", padx=20)
        ctk.CTkRadioButton(modes, text="By Category", variable=self.org_mode, value="category").pack(side="left", padx=20)
        
        self.use_shortcuts = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options, text="Use shortcuts", variable=self.use_shortcuts).pack(anchor="w", pady=10)
        
        folder_frame = ctk.CTkFrame(options)
        folder_frame.pack(fill="x", pady=10)
        ctk.CTkButton(folder_frame, text="Set Output", command=self.set_output).pack(side="left", padx=5)
        self.output_label = ctk.CTkLabel(folder_frame, text="Not set", text_color="gray")
        self.output_label.pack(side="left", padx=10)
        self.output_folder = None
        
        ctk.CTkButton(options, text="ORGANIZE NOW", command=self.organize,
                     font=("Arial", 14, "bold"), height=50, fg_color="green").pack(fill="x", pady=20)
        
        self.org_status = ctk.CTkLabel(options, text="")
        self.org_status.pack(pady=10)
    
    def set_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.output_label.configure(text=folder, text_color="lime")
    
    def organize(self):
        if not self.output_folder:
            messagebox.showwarning("Warning", "Set output folder!")
            return
        
        import shutil, subprocess
        
        mode = self.org_mode.get()
        shortcuts = self.use_shortcuts.get()
        count = 0
        
        if mode == "people":
            for pid, name, c in self.db.get_all_people():
                if c == 0:
                    continue
                
                folder = os.path.join(self.output_folder, name)
                os.makedirs(folder, exist_ok=True)
                
                seen = set()
                for fid, photo_id, x, y, w, h, path in self.db.get_faces_by_person(pid):
                    if photo_id in seen:
                        continue
                    seen.add(photo_id)
                    
                    fn = os.path.basename(path)
                    if shortcuts:
                        sp = os.path.join(folder, fn + ".lnk")
                        if not os.path.exists(sp):
                            try:
                                ps = f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{sp}");$s.TargetPath="{path}";$s.Save()'
                                subprocess.run(['powershell', '-Command', ps], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                count += 1
                            except:
                                pass
                    else:
                        dst = os.path.join(folder, fn)
                        if not os.path.exists(dst):
                            shutil.copy2(path, dst)
                            count += 1
        else:
            for cat in ['solo', 'duo', 'group', 'no_faces']:
                photos = self.db.get_photos_by_category(cat)
                if not photos:
                    continue
                
                folder = os.path.join(self.output_folder, cat)
                os.makedirs(folder, exist_ok=True)
                
                for pid, path, fn, fc in photos:
                    if shortcuts:
                        sp = os.path.join(folder, fn + ".lnk")
                        if not os.path.exists(sp):
                            try:
                                ps = f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{sp}");$s.TargetPath="{path}";$s.Save()'
                                subprocess.run(['powershell', '-Command', ps], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                count += 1
                            except:
                                pass
                    else:
                        dst = os.path.join(folder, fn)
                        if not os.path.exists(dst):
                            shutil.copy2(path, dst)
                            count += 1
        
        self.org_status.configure(text=f"Created {count} files!")
        messagebox.showinfo("Done", f"Organized {count} photos!")
    
    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    app = PhotoAIApp()
    app.run()
