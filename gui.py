  # ==============================================================================
    # Project: OpenSeismo - Decentralized Edge-AI Earthquake Detection
    # Copyright (c) 2026 OpenSeismo Project (FOSSEE Hackathon Submission)
    #
    # This software is released under the MIT License.
    # The hardware designs are released under the CC BY-SA 4.0 License.
    #
    # Permission is hereby granted, free of charge, to any person obtaining a copy
    # of this software and associated documentation files (the "Software"), to deal
    # in the Software without restriction, including without limitation the rights
    # to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    # copies of the Software.
    # ==============================================================================
#

import tkinter as tk
import json
import os
import time

class EarthEarlyDetectionGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EARTH EARLY DETECTION")
        
        # Enterprise Fullscreen / Geometry
        self.root.geometry("800x480") 
        self.root.configure(bg="#0B0F19") 
        self.root.bind("<Escape>", lambda e: self.root.quit())
        
        # Fixed Enterprise Fonts (Smaller to prevent text cutoffs)
        self.title_font = ("Helvetica", 24, "bold")
        self.banner_font = ("Helvetica", 36, "bold")
        self.label_font = ("Helvetica", 10, "bold")
        self.value_font = ("Helvetica", 16, "bold")
        
        # Layout Frames
        self.header_frame = tk.Frame(root, bg="#111827", pady=5)
        self.header_frame.pack(fill=tk.X)
        
        self.title_label = tk.Label(self.header_frame, text="EARTH EARLY DETECTION", font=self.title_font, fg="#F9FAFB", bg="#111827")
        self.title_label.pack(side=tk.LEFT, padx=10)
        
        self.clock_label = tk.Label(self.header_frame, text="00:00:00", font=("Helvetica", 14, "bold"), fg="#9CA3AF", bg="#111827")
        self.clock_label.pack(side=tk.LEFT, padx=20)
        
        self.exit_btn = tk.Button(self.header_frame, text="✖ EXIT", font=("Helvetica", 12, "bold"), fg="white", bg="#DC2626", bd=0, padx=10, command=self.root.quit)
        self.exit_btn.pack(side=tk.RIGHT, padx=10)
        
        self.banner_frame = tk.Frame(root, bg="#059669", pady=10)
        self.banner_frame.pack(fill=tk.X)
        
        self.status_label = tk.Label(self.banner_frame, text="SYSTEM SAFE", font=self.banner_font, fg="white", bg="#059669")
        self.status_label.pack()
        
        # The Middle Grid (Telemetry)
        self.grid_frame = tk.Frame(root, bg="#0B0F19")
        self.grid_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.vars = {
            "local_ratio": tk.StringVar(value="0.00"),
            "lora_node": tk.StringVar(value="DISCONNECTED"),
            "lora_ratio": tk.StringVar(value="0.00"),
            "lora_rssi": tk.StringVar(value="0 dBm"),
            "network": tk.StringVar(value="OFFLINE"),
            "gps": tk.StringVar(value="ACQUIRING...")
        }
        
        self._build_grid_box(self.grid_frame, "MASTER RATIO (STA/LTA)", self.vars["local_ratio"], 0, 0)
        self._build_grid_box(self.grid_frame, "NETWORK STATUS", self.vars["network"], 0, 1)
        self._build_grid_box(self.grid_frame, "BASE LOCATION", self.vars["gps"], 0, 2)
        
        self._build_grid_box(self.grid_frame, "SLAVE NODE", self.vars["lora_node"], 1, 0)
        self._build_grid_box(self.grid_frame, "SLAVE RATIO", self.vars["lora_ratio"], 1, 1)
        self._build_grid_box(self.grid_frame, "SLAVE SIGNAL", self.vars["lora_rssi"], 1, 2)
        
        for i in range(3): self.grid_frame.grid_columnconfigure(i, weight=1)
        
        # Bottom Live Seismograph Canvas
        self.graph_frame = tk.Frame(root, bg="#0B0F19")
        self.graph_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.graph_title = tk.Label(self.graph_frame, text="🔴 LIVE MASTER SEISMOGRAPH (STA/LTA)", font=("Helvetica", 10, "bold"), fg="#9CA3AF", bg="#0B0F19")
        self.graph_title.pack(anchor="w")
        
        self.canvas = tk.Canvas(self.graph_frame, bg="#111827", bd=0, highlightthickness=1, highlightbackground="#374151")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.history = [1.0] * 120 # Hold 120 points for smooth scrolling
        
        self.update_telemetry()
        
    def _build_grid_box(self, parent, title, text_var, row, col):
        box = tk.Frame(parent, bg="#1F2937", bd=0)
        box.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
        
        lbl_title = tk.Label(box, text=title, font=self.label_font, fg="#9CA3AF", bg="#1F2937")
        lbl_title.pack(side=tk.TOP, pady=(5, 0))
        
        lbl_val = tk.Label(box, textvariable=text_var, font=self.value_font, fg="#F3F4F6", bg="#1F2937", wraplength=220)
        lbl_val.pack(side=tk.BOTTOM, expand=True, pady=(0, 5))

    def draw_graph(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1: return
        
        dx = w / (len(self.history) - 1)
        max_val = max(2.5, max(self.history) * 1.2) # Keep headroom
        
        points = []
        for i, val in enumerate(self.history):
            x = i * dx
            y = h - ((val / max_val) * h)
            points.extend([x, y])
            
        if len(points) >= 4:
            self.canvas.create_line(points, fill="#10B981", width=3, smooth=True)
            
        # Draw Danger Threshold Line (Assuming 2.0 is trigger)
        thresh_y = h - ((2.0 / max_val) * h)
        self.canvas.create_line(0, thresh_y, w, thresh_y, fill="#EF4444", dash=(4, 4), width=2)
        
    def update_telemetry(self):
        # Update clock
        self.clock_label.config(text=time.strftime("%H:%M:%S"))
        
        try:
            if os.path.exists('/dev/shm/seismic_state.json'):
                with open('/dev/shm/seismic_state.json', 'r') as f:
                    state = json.load(f)
                    
                local_ratio = state.get('local_ratio', 1.0)
                self.vars["local_ratio"].set(f"{local_ratio:.2f}")
                self.vars["lora_node"].set(state.get('lora_node', 'UNKNOWN'))
                self.vars["lora_ratio"].set(f"{state.get('lora_ratio', 0.0):.2f}")
                self.vars["lora_rssi"].set(f"{state.get('lora_rssi', 0)} dBm")
                self.vars["network"].set(state.get('network', 'OFFLINE'))
                self.vars["gps"].set(state.get('gps', 'ACQUIRING...'))
                
                # Append to Graph History
                self.history.append(local_ratio)
                if len(self.history) > 120:
                    self.history.pop(0)
                self.draw_graph()
                
                # Alert Colors
                if state.get("local_status") == "EARTHQUAKE!":
                    self.banner_frame.configure(bg="#DC2626")
                    self.status_label.configure(text="CRITICAL: EARTHQUAKE DETECTED!", bg="#DC2626")
                    self.root.configure(bg="#450a0a")
                else:
                    self.banner_frame.configure(bg="#059669")
                    self.status_label.configure(text="SYSTEM SAFE", bg="#059669")
                    self.root.configure(bg="#0B0F19")
        except Exception:
            pass
            
        self.root.after(100, self.update_telemetry)

if __name__ == "__main__":
    root = tk.Tk()
    app = EarthEarlyDetectionGUI(root)
    # Attempt to start in true fullscreen (perfect for Pi Touchscreens)
    try:
        root.attributes('-fullscreen', True)
    except:
        pass
    root.mainloop()
