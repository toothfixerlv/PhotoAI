import sqlite3
from datetime import datetime
import json

class Database:
    def __init__(self, db_path="photoai_v2.db"):
        self.conn = sqlite3.connect(db_path)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                folder_type TEXT,
                added_date TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                filename TEXT,
                folder_id INTEGER,
                size INTEGER,
                width INTEGER,
                height INTEGER,
                date_taken TEXT,
                date_added TEXT,
                face_count INTEGER DEFAULT 0,
                category TEXT DEFAULT 'unscanned',
                scanned INTEGER DEFAULT 0,
                FOREIGN KEY (folder_id) REFERENCES folders(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY,
                photo_id INTEGER,
                x INTEGER,
                y INTEGER,
                width INTEGER,
                height INTEGER,
                confidence REAL,
                face_size INTEGER,
                embedding TEXT,
                cluster_id INTEGER,
                person_id INTEGER,
                FOREIGN KEY (photo_id) REFERENCES photos(id),
                FOREIGN KEY (person_id) REFERENCES people(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY,
                name TEXT,
                face_count INTEGER DEFAULT 0,
                avg_embedding TEXT,
                person_id INTEGER,
                created_date TEXT,
                FOREIGN KEY (person_id) REFERENCES people(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE,
                face_count INTEGER DEFAULT 0,
                created_date TEXT
            )
        ''')
        
        self.conn.commit()
    
    def add_folder(self, path, folder_type="source"):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO folders (path, folder_type, added_date) VALUES (?, ?, ?)',
                          (path, folder_type, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute('SELECT id FROM folders WHERE path = ?', (path,))
            return cursor.fetchone()[0]
    
    def get_folders(self, folder_type=None):
        cursor = self.conn.cursor()
        if folder_type:
            cursor.execute('SELECT id, path FROM folders WHERE folder_type = ?', (folder_type,))
        else:
            cursor.execute('SELECT id, path, folder_type FROM folders')
        return cursor.fetchall()
    
    def remove_folder(self, folder_id):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM faces WHERE photo_id IN (SELECT id FROM photos WHERE folder_id = ?)', (folder_id,))
        cursor.execute('DELETE FROM photos WHERE folder_id = ?', (folder_id,))
        cursor.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
        self.conn.commit()
    
    def add_photo(self, path, filename, folder_id, size, width=0, height=0):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''INSERT INTO photos 
                (path, filename, folder_id, size, width, height, date_added)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (path, filename, folder_id, size, width, height, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None
    
    def get_all_photos(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, path, filename, category, face_count, scanned FROM photos')
        return cursor.fetchall()
    
    def get_unscanned_photos(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, path, filename FROM photos WHERE scanned = 0')
        return cursor.fetchall()
    
    def get_photos_by_category(self, category):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, path, filename, face_count FROM photos WHERE category = ?', (category,))
        return cursor.fetchall()
    
    def update_photo_scan(self, photo_id, face_count, category):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE photos SET face_count = ?, category = ?, scanned = 1 WHERE id = ?',
                      (face_count, category, photo_id))
        self.conn.commit()
    
    def get_photo_count(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM photos')
        return cursor.fetchone()[0]
    
    def get_category_counts(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT category, COUNT(*) FROM photos GROUP BY category')
        return dict(cursor.fetchall())
    
    def add_face(self, photo_id, x, y, width, height, confidence=0, face_size=0, embedding=None):
        cursor = self.conn.cursor()
        emb_json = json.dumps(embedding) if embedding else None
        cursor.execute('''INSERT INTO faces 
            (photo_id, x, y, width, height, confidence, face_size, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (photo_id, x, y, width, height, confidence, face_size, emb_json))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_faces_for_photo(self, photo_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT id, x, y, width, height, confidence, cluster_id, person_id 
                         FROM faces WHERE photo_id = ?''', (photo_id,))
        return cursor.fetchall()
    
    def update_face_cluster(self, face_id, cluster_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE faces SET cluster_id = ? WHERE id = ?', (cluster_id, face_id))
        self.conn.commit()
    
    def update_face_person(self, face_id, person_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE faces SET person_id = ? WHERE id = ?', (person_id, face_id))
        self.conn.commit()
    
    def update_face_embedding(self, face_id, embedding):
        cursor = self.conn.cursor()
        emb_json = json.dumps(embedding) if embedding else None
        cursor.execute('UPDATE faces SET embedding = ? WHERE id = ?', (emb_json, face_id))
        self.conn.commit()
    
    def get_faces_by_cluster(self, cluster_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT f.id, f.photo_id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.cluster_id = ?''', (cluster_id,))
        return cursor.fetchall()
    
    def get_faces_by_person(self, person_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT f.id, f.photo_id, f.x, f.y, f.width, f.height, p.path
                         FROM faces f JOIN photos p ON f.photo_id = p.id
                         WHERE f.person_id = ?''', (person_id,))
        return cursor.fetchall()
    
    def create_cluster(self, avg_embedding=None):
        cursor = self.conn.cursor()
        emb_json = json.dumps(avg_embedding) if avg_embedding else None
        cursor.execute('INSERT INTO clusters (avg_embedding, created_date) VALUES (?, ?)',
                      (emb_json, datetime.now().isoformat()))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_all_clusters(self):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT c.id, c.name, c.face_count, c.person_id,
                         (SELECT COUNT(*) FROM faces WHERE cluster_id = c.id) as actual_count
                         FROM clusters c ORDER BY actual_count DESC''')
        return cursor.fetchall()
    
    def update_cluster_name(self, cluster_id, name):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE clusters SET name = ? WHERE id = ?', (name, cluster_id))
        self.conn.commit()
    
    def update_cluster_person(self, cluster_id, person_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE clusters SET person_id = ? WHERE id = ?', (person_id, cluster_id))
        cursor.execute('UPDATE faces SET person_id = ? WHERE cluster_id = ?', (person_id, cluster_id))
        self.conn.commit()
    
    def clear_clusters(self):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE faces SET cluster_id = NULL')
        cursor.execute('DELETE FROM clusters')
        self.conn.commit()
    
    def add_person(self, name):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO people (name, created_date) VALUES (?, ?)',
                          (name, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute('SELECT id FROM people WHERE name = ?', (name,))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_all_people(self):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT p.id, p.name, 
                         (SELECT COUNT(*) FROM faces WHERE person_id = p.id) as face_count
                         FROM people p ORDER BY face_count DESC''')
        return cursor.fetchall()
    
    def get_stats(self):
        cursor = self.conn.cursor()
        stats = {}
        
        cursor.execute('SELECT COUNT(*) FROM photos')
        stats['total_photos'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM photos WHERE scanned = 1')
        stats['scanned'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM faces')
        stats['total_faces'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM clusters')
        stats['clusters'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM people')
        stats['people'] = cursor.fetchone()[0]
        
        cats = self.get_category_counts()
        stats['solo'] = cats.get('solo', 0)
        stats['duo'] = cats.get('duo', 0)
        stats['group'] = cats.get('group', 0)
        stats['no_faces'] = cats.get('no_faces', 0)
        
        return stats
