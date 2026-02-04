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
        self.window.geometry("1400x900")
        ctk.set_appearance_mode("dark")
        self.selected_faces = {}  # face_id -> label widget
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
        
        self.min_face_size = ctk.IntVar(value=30)
        size_frame = ctk.CTkFrame(left)
        size_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(size_frame, text="Min face size:").pack(side="left")
        ctk.CTkEntry(size_frame, textvariable=self.min_face_size, width=50).pack(side="left", padx=5)
        ctk.CTkLabel(size_frame, text="px").pack(side="left")
        
        ctk.CTkLabel(left, text="Face Detector:").pack(anchor="w", padx=10, pady=5)
        self.detector_var = ctk.StringVar(value="opencv")
        
        det_frame1 = ctk.CTkFrame(left)
        det_frame1.pack(fill="x", padx=10)
        ctk.CTkRadioButton(det_frame1, text="OpenCV", variable=self.detector_var, value="opencv").pack(side="left", padx=5)
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
        
        self.scan_status = ctk.CTkLabel(left, text="Ready", wraplength=300)
        self.scan_status.pack(pady=5)
        
        right = ctk.CTkFrame(self.tab_scan)
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(right, text="RESULTS", font=("Arial", 16, "bold")).pack(pady=10)
        
        stats_frame = ctk.CTkFrame(right)
        stats_frame.pack(fill="x", padx=20, pady=10)
        
        self.stat_labels = {}
        for key, label in [('total_photos', 'Total'), ('scanned', 'Scanned'), 
                           ('solo', 'Solo'), ('duo', 'Duo'),
                           ('group', 'Group'), ('no_faces', 'No Faces'), ('total_faces', 'Faces')]:
            f = ctk.CTkFrame(stats_frame)
            f.pack(fill="x", pady=2)
            ctk.CTkLabel(f, text=f"{label}:", width=150, anchor="w").pack(side="left")
            self.stat_labels[key] = ctk.CTkLabel(f, text="0", font=("Arial", 12, "bold"))
            self.stat_labels[key].pack(side="left")
        
        ctk.CTkButton(right, text="Refresh", command=self.refresh_stats).pack(pady=5)
        
        preview_btns = ctk.CTkFrame(right)
        preview_btns.pack(fill="x", padx=20, pady=10)
        for cat in ['solo', 'duo', 'group', 'no_faces']:
            ctk.CTkButton(preview_btns, text=cat.title(), 
                         command=lambda c=cat: self.preview_category(c), width=70).pack(side="left", padx=3)
        
        self.preview_scroll = ctk.CTkScrollableFrame(right, height=250)
        self.preview_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.refresh_stats()
    
    def add_folder(self):
        folder = filedialog.askdirectory()
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
            orig_w, orig_h = img.size
            scale = 1.0
            
            if self.resize_for_detection.get() and max(img.size) > 1200:
                scale = 1200 / max(img.size)
                img = img.resize((int(orig_w * scale), int(orig_h * scale)), Image.LANCZOS)
            
            temp_path = "temp_detect.jpg"
            img.save(temp_path, quality=95)
            
            detected = DeepFace.extract_faces(img_path=temp_path, detector_backend=detector, 
                                              enforce_detection=False, align=False)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            faces = []
            for face in detected:
                area = face['facial_area']
                conf = face.get('confidence', 0)
                if conf < 0.5:
                    continue
                
                x = max(0, int(area['x'] / scale))
                y = max(0, int(area['y'] / scale))
                w = min(int(area['w'] / scale), orig_w - x)
                h = min(int(area['h'] / scale), orig_h - y)
                
                if w >= min_size and h >= min_size:
                    faces.append({'x': x, 'y': y, 'w': w, 'h': h, 'confidence': conf, 'size': w * h})
            
            return faces
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
        for fid, path in folders:
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(exts):
                        fp = os.path.join(root, file)
                        try:
                            sz = os.path.getsize(fp)
                            if sz > 5000:
                                self.db.add_photo(fp, file, fid, sz)
                        except:
                            pass
        
        photos = self.db.get_unscanned_photos()
        total = len(photos)
        
        if total == 0:
            self.scan_status.configure(text="No new photos")
            self.refresh_stats()
            return
        
        for i, (pid, path, filename) in enumerate(photos):
            self.scan_progress.set((i + 1) / total)
            self.scan_status.configure(text=f"{i+1}/{total}")
            self.window.update()
            
            faces = self.detect_faces_in_image(path)
            fc = len(faces)
            cat = 'no_faces' if fc == 0 else 'solo' if fc == 1 else 'duo' if fc == 2 else 'group'
            
            for face in faces:
                self.db.add_face(pid, face['x'], face['y'], face['w'], face['h'], face['confidence'], face['size'])
            
            self.db.update_photo_scan(pid, fc, cat)
        
        self.scan_progress.set(1)
        self.scan_status.configure(text="Done!")
        self.refresh_stats()
        messagebox.showinfo("Done", f"Scanned {total} photos!")
    
    def preview_category(self, category):
        for w in self.preview_scroll.winfo_children():
            w.destroy()
        
        photos = self.db.get_photos_by_category(category)
        if not photos:
            ctk.CTkLabel(self.preview_scroll, text="None").pack(pady=20)
            return
        
        row = None
        for i, (pid, path, fn, fc) in enumerate(photos[:40]):
            if i % 4 == 0:
                row = ctk.CTkFrame(self.preview_scroll)
                row.pack(fill="x", pady=3)
            
            try:
                img = Image.open(path)
                faces = self.db.get_faces_for_photo(pid)
                if faces:
                    draw = ImageDraw.Draw(img)
                    for f in faces:
                        draw.rectangle([f[1], f[2], f[1]+f[3], f[2]+f[4]], outline="lime", width=2)
                img.thumbnail((120, 120))
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(row, image=photo, bg="#2b2b2b")
                lbl.image = photo
                lbl.pack(side="left", padx=2)
            except:
                pass
    
    def setup_cluster_tab(self):
        top = ctk.CTkFrame(self.tab_cluster)
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top, text="CLUSTER", font=("Arial", 18, "bold")).pack(side="left", padx=10)
        
        self.cluster_status = ctk.CTkLabel(top, text="")
        self.cluster_status.pack(side="right", padx=20)
        
        btn_frame = ctk.CTkFrame(self.tab_cluster)
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkButton(btn_frame, text="1. Extract", command=self.extract_embeddings, width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="2. Cluster", command=self.run_clustering, width=100, fg_color="green").pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Clear All", command=self.clear_clusters, width=80, fg_color="darkred").pack(side="left", padx=5)
        
        # Threshold
        ctk.CTkLabel(btn_frame, text="Similarity:").pack(side="left", padx=(20,5))
        self.threshold_var = ctk.DoubleVar(value=0.55)
        self.threshold_slider = ctk.CTkSlider(btn_frame, from_=0.3, to=0.9, variable=self.threshold_var, width=100)
        self.threshold_slider.pack(side="left", padx=5)
        self.threshold_label = ctk.CTkLabel(btn_frame, text="0.55", width=40)
        self.threshold_label.pack(side="left")
        self.threshold_slider.configure(command=lambda v: self.threshold_label.configure(text=f"{float(v):.2f}"))
        
        # Selection info and remove button
        self.selection_label = ctk.CTkLabel(btn_frame, text="Selected: 0", text_color="orange")
        self.selection_label.pack(side="right", padx=10)
        
        ctk.CTkButton(btn_frame, text="Remove Selected", command=self.remove_selected_faces, 
                     fg_color="orange", width=120).pack(side="right", padx=5)
        
        info = ctk.CTkLabel(self.tab_cluster, text="Click wrong faces to select (red border), then Remove Selected", text_color="yellow")
        info.pack(pady=5)
        
        self.cluster_scroll = ctk.CTkScrollableFrame(self.tab_cluster)
        self.cluster_scroll.pack(fill="both", expand=True, padx=10, pady=10)
    
    def extract_embeddings(self):
        if not DEEPFACE_AVAILABLE:
            return
        
        cursor = self.db.conn.cursor()
        cursor.execute('''SELECT f.id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NULL AND p.category = 'solo' ''')
        faces = cursor.fetchall()
        
        if not faces:
            messagebox.showinfo("Info", "Done! Click Cluster")
            return
        
        self.cluster_status.configure(text=f"0/{len(faces)}")
        self.window.update()
        
        for i, (fid, x, y, w, h, path) in enumerate(faces):
            self.cluster_status.configure(text=f"{i+1}/{len(faces)}")
            self.window.update()
            
            try:
                img = Image.open(path)
                iw, ih = img.size
                x, y = max(0, x), max(0, y)
                w, h = min(w, iw-x), min(h, ih-y)
                if w < 20 or h < 20:
                    continue
                
                pad = int(min(w, h) * 0.3)
                face_img = img.crop((max(0,x-pad), max(0,y-pad), min(iw,x+w+pad), min(ih,y+h+pad)))
                face_img = face_img.resize((160, 160))
                
                temp = "temp.jpg"
                face_img.save(temp, quality=95)
                result = DeepFace.represent(temp, model_name='Facenet', enforce_detection=False)
                if result:
                    self.db.update_face_embedding(fid, result[0]['embedding'])
                os.remove(temp)
            except:
                pass
        
        self.cluster_status.configure(text="Done!")
        messagebox.showinfo("Done", "Click Cluster now")
    
    def run_clustering(self):
        cursor = self.db.conn.cursor()
        cursor.execute('''SELECT f.id, f.embedding FROM faces f 
                         JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NOT NULL AND p.category = 'solo' ''')
        faces = cursor.fetchall()
        
        if len(faces) < 2:
            messagebox.showwarning("Warning", "Need faces! Run Extract first")
            return
        
        self.db.clear_clusters()
        self.selected_faces.clear()
        
        face_data = []
        for fid, emb_json in faces:
            try:
                face_data.append({'id': fid, 'embedding': np.array(json.loads(emb_json))})
            except:
                pass
        
        threshold = self.threshold_var.get()
        clusters = []
        
        for face in face_data:
            best_cluster, best_sim = None, -1
            for cluster in clusters:
                sims = [np.dot(face['embedding'], cf['embedding']) / 
                       (np.linalg.norm(face['embedding']) * np.linalg.norm(cf['embedding']))
                       for cf in cluster['faces']]
                avg = np.mean(sims) if sims else 0
                if avg > best_sim:
                    best_sim, best_cluster = avg, cluster
            
            if best_cluster and best_sim >= threshold:
                best_cluster['faces'].append(face)
            else:
                clusters.append({'faces': [face]})
        
        clusters.sort(key=lambda c: len(c['faces']), reverse=True)
        
        for cluster in clusters:
            cid = self.db.create_cluster()
            for face in cluster['faces']:
                self.db.update_face_cluster(face['id'], cid)
        
        self.show_clusters()
        messagebox.showinfo("Done", f"{len(clusters)} clusters")
    
    def clear_clusters(self):
        if messagebox.askyesno("Confirm", "Clear all?"):
            self.db.clear_clusters()
            self.selected_faces.clear()
            self.show_clusters()
    
    def on_face_click(self, face_id, frame):
        """Toggle face selection"""
        if face_id in self.selected_faces:
            del self.selected_faces[face_id]
            frame.configure(highlightbackground="#2b2b2b", highlightthickness=0)
        else:
            self.selected_faces[face_id] = frame
            frame.configure(highlightbackground="red", highlightthickness=3)
        
        self.selection_label.configure(text=f"Selected: {len(self.selected_faces)}")
    
    def remove_selected_faces(self):
        if not self.selected_faces:
            messagebox.showinfo("Info", "Click on wrong faces first!")
            return
        
        count = len(self.selected_faces)
        if messagebox.askyesno("Confirm", f"Remove {count} face(s)?"):
            cursor = self.db.conn.cursor()
            for fid in self.selected_faces:
                cursor.execute('UPDATE faces SET cluster_id = NULL, person_id = NULL WHERE id = ?', (fid,))
            self.db.conn.commit()
            
            self.selected_faces.clear()
            self.selection_label.configure(text="Selected: 0")
            self.show_clusters()
            self.cluster_status.configure(text=f"Removed {count}")
    
    def show_clusters(self):
        for w in self.cluster_scroll.winfo_children():
            w.destroy()
        
        clusters = self.db.get_all_clusters()
        if not clusters:
            ctk.CTkLabel(self.cluster_scroll, text="No clusters\n\n1. Extract\n2. Cluster").pack(pady=50)
            return
        
        for cid, name, fc, pid, count in clusters:
            if count == 0:
                continue
            
            frame = ctk.CTkFrame(self.cluster_scroll, fg_color="gray20")
            frame.pack(fill="x", pady=8, padx=10)
            
            header = ctk.CTkFrame(frame)
            header.pack(fill="x", padx=10, pady=5)
            
            color = "lime" if count >= 5 else "yellow" if count >= 3 else "gray"
            ctk.CTkLabel(header, text=f"#{cid} ({count})", text_color=color, font=("Arial", 12, "bold")).pack(side="left", padx=5)
            
            name_var = ctk.StringVar(value=name or "")
            ctk.CTkEntry(header, textvariable=name_var, width=140, placeholder_text="Name...").pack(side="left", padx=5)
            
            def save(c=cid, v=name_var):
                n = v.get().strip()
                if n:
                    p = self.db.add_person(n)
                    self.db.update_cluster_name(c, n)
                    self.db.update_cluster_person(c, p)
                    self.cluster_status.configure(text=f"Saved: {n}")
                    self.show_clusters()
            
            ctk.CTkButton(header, text="Save", width=50, command=save).pack(side="left", padx=5)
            if name:
                ctk.CTkLabel(header, text="✓", text_color="lime").pack(side="left")
            
            # Face thumbnails
            faces = self.db.get_faces_by_cluster(cid)
            thumb_frame = ctk.CTkFrame(frame)
            thumb_frame.pack(fill="x", padx=10, pady=5)
            
            for i, (fid, photo_id, x, y, w, h, path) in enumerate(faces[:14]):
                try:
                    img = Image.open(path)
                    iw, ih = img.size
                    x, y = max(0, min(x, iw-1)), max(0, min(y, ih-1))
                    w, h = max(10, min(w, iw-x)), max(10, min(h, ih-y))
                    
                    face_img = img.crop((x, y, x+w, y+h)).resize((60, 60))
                    photo = ImageTk.PhotoImage(face_img)
                    
                    # Create a frame for the face with border capability
                    face_frame = tk.Frame(thumb_frame, bg="#2b2b2b")
                    face_frame.pack(side="left", padx=2, pady=2)
                    
                    lbl = tk.Label(face_frame, image=photo, bg="#2b2b2b")
                    lbl.image = photo
                    lbl.pack()
                    
                    # Highlight if selected
                    if fid in self.selected_faces:
                        face_frame.configure(highlightbackground="red", highlightthickness=3)
                    
                    # Bind click
                    lbl.bind("<Button-1>", lambda e, f=fid, fr=face_frame: self.on_face_click(f, fr))
                    face_frame.bind("<Button-1>", lambda e, f=fid, fr=face_frame: self.on_face_click(f, fr))
                except:
                    pass
            
            if len(faces) > 14:
                ctk.CTkLabel(thumb_frame, text=f"+{len(faces)-14}").pack(side="left", padx=5)
    
    def setup_recognize_tab(self):
        top = ctk.CTkFrame(self.tab_recognize)
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top, text="FIND IN ALL PHOTOS", font=("Arial", 18, "bold")).pack(side="left", padx=10)
        self.recog_status = ctk.CTkLabel(top, text="")
        self.recog_status.pack(side="right", padx=20)
        
        ctk.CTkLabel(self.tab_recognize, text="Find named people in group/duo photos", text_color="yellow").pack(pady=5)
        
        btn_frame = ctk.CTkFrame(self.tab_recognize)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(btn_frame, text="1. Extract All", command=self.extract_all_embeddings, width=120).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="2. Find People", command=self.recognize_people, width=120, fg_color="green").pack(side="left", padx=5)
        
        ctk.CTkLabel(btn_frame, text="Match:").pack(side="left", padx=(20,5))
        self.recog_threshold = ctk.DoubleVar(value=0.55)
        ctk.CTkSlider(btn_frame, from_=0.4, to=0.8, variable=self.recog_threshold, width=100).pack(side="left", padx=5)
        
        self.recog_scroll = ctk.CTkScrollableFrame(self.tab_recognize)
        self.recog_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self.show_named_people()
    
    def extract_all_embeddings(self):
        if not DEEPFACE_AVAILABLE:
            return
        
        cursor = self.db.conn.cursor()
        cursor.execute('''SELECT f.id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.embedding IS NULL''')
        faces = cursor.fetchall()
        
        if not faces:
            messagebox.showinfo("Info", "Done! Click Find People")
            return
        
        for i, (fid, x, y, w, h, path) in enumerate(faces):
            self.recog_status.configure(text=f"{i+1}/{len(faces)}")
            self.window.update()
            
            try:
                img = Image.open(path)
                iw, ih = img.size
                x, y = max(0, x), max(0, y)
                w, h = min(w, iw-x), min(h, ih-y)
                if w < 20 or h < 20:
                    continue
                
                pad = int(min(w, h) * 0.3)
                face_img = img.crop((max(0,x-pad), max(0,y-pad), min(iw,x+w+pad), min(ih,y+h+pad)))
                face_img = face_img.resize((160, 160))
                
                temp = "temp.jpg"
                face_img.save(temp, quality=95)
                result = DeepFace.represent(temp, model_name='Facenet', enforce_detection=False)
                if result:
                    self.db.update_face_embedding(fid, result[0]['embedding'])
                os.remove(temp)
            except:
                pass
        
        self.recog_status.configure(text="Done!")
        messagebox.showinfo("Done", "Click Find People")
    
    def recognize_people(self):
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT id, name FROM people')
        people = cursor.fetchall()
        
        if not people:
            messagebox.showwarning("Warning", "Name clusters in Tab 2 first!")
            return
        
        person_embs = {}
        for pid, name in people:
            cursor.execute('SELECT embedding FROM faces WHERE person_id = ? AND embedding IS NOT NULL', (pid,))
            embs = [np.array(json.loads(e[0])) for e in cursor.fetchall()]
            if embs:
                person_embs[pid] = {'name': name, 'emb': np.mean(embs, axis=0)}
        
        if not person_embs:
            return
        
        cursor.execute('SELECT id, embedding FROM faces WHERE person_id IS NULL AND embedding IS NOT NULL')
        unassigned = cursor.fetchall()
        
        threshold = self.recog_threshold.get()
        matched = 0
        
        for fid, emb_json in unassigned:
            emb = np.array(json.loads(emb_json))
            best_pid, best_sim = None, -1
            
            for pid, data in person_embs.items():
                sim = np.dot(emb, data['emb']) / (np.linalg.norm(emb) * np.linalg.norm(data['emb']))
                if sim > best_sim:
                    best_sim, best_pid = sim, pid
            
            if best_pid and best_sim >= threshold:
                self.db.update_face_person(fid, best_pid)
                matched += 1
        
        self.recog_status.configure(text=f"Found {matched}!")
        self.show_named_people()
        messagebox.showinfo("Done", f"Found {matched} more faces!")
    
    def show_named_people(self):
        for w in self.recog_scroll.winfo_children():
            w.destroy()
        
        people = self.db.get_all_people()
        if not people:
            ctk.CTkLabel(self.recog_scroll, text="No named people\n\nName clusters in Tab 2!").pack(pady=50)
            return
        
        for pid, name, count in people:
            f = ctk.CTkFrame(self.recog_scroll, fg_color="gray25")
            f.pack(fill="x", pady=3, padx=10)
            ctk.CTkLabel(f, text=f"{name}: {count} photos").pack(side="left", padx=10, pady=5)
    
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
        self.review_menu.configure(values=["All"] + [p[1] for p in people])
        self.filter_review("All")
    
    def filter_review(self, choice):
        for w in self.review_scroll.winfo_children():
            w.destroy()
        
        people = self.db.get_all_people()
        if not people:
            ctk.CTkLabel(self.review_scroll, text="No people yet").pack(pady=50)
            return
        
        show = people if choice == "All" else [p for p in people if p[1] == choice]
        for pid, name, count in show:
            frame = ctk.CTkFrame(self.review_scroll, fg_color="gray20")
            frame.pack(fill="x", pady=8, padx=10)
            
            ctk.CTkLabel(frame, text=f"{name} ({count})", font=("Arial", 14, "bold")).pack(anchor="w", padx=10, pady=5)
            
            faces = self.db.get_faces_by_person(pid)
            thumb = ctk.CTkFrame(frame)
            thumb.pack(fill="x", padx=10, pady=5)
            
            for fid, photo_id, x, y, w, h, path in faces[:16]:
                try:
                    img = Image.open(path)
                    draw = ImageDraw.Draw(img)
                    draw.rectangle([x, y, x+w, y+h], outline="lime", width=2)
                    img.thumbnail((90, 90))
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(thumb, image=photo, bg="#2b2b2b")
                    lbl.image = photo
                    lbl.pack(side="left", padx=2)
                except:
                    pass
            
            if len(faces) > 16:
                ctk.CTkLabel(thumb, text=f"+{len(faces)-16}").pack(side="left", padx=5)
    
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
        
        self.org_status.configure(text=f"Done: {count} files")
        messagebox.showinfo("Done", f"Organized {count} photos!")
    
    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    app = PhotoAIApp()
    app.run()
