# ==============================================================================
# Project: OpenSeismo - Decentralized Edge-AI Earthquake Detection
# Copyright (c) 2026 OpenSeismo Project (FOSSEE Hackathon Submission)
# 
# This software is released under the MIT License.
# The hardware designs are released under the CC BY-SA 4.0 License.
# ==============================================================================
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import pymysql
import os

app = Flask(__name__)
app.secret_key = 'YOUR_SECRET_KEY_HERE'

# Database Config
DB_PASS = "YOUR_DB_PASSWORD"  
DB_PORT = 3307    

def get_db_connection():
    return pymysql.connect(
        host="localhost", 
        port=DB_PORT, 
        user="root", 
        password=DB_PASS, 
        database="openseismopi",
        cursorclass=pymysql.cursors.DictCursor
    )

# --- ROUTES ---

@app.route('/')
def dashboard():
    return render_template('index.html')

# --- API ENDPOINTS FOR LIVE DATA ---

@app.route('/api/seismic')
def api_seismic():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Fetch last 50 points for smooth scrolling
            cursor.execute("SELECT * FROM seismic_data ORDER BY id DESC LIMIT 50")
            data = cursor.fetchall()
            return jsonify(data[::-1]) # Reverse to chronological order
    finally:
        conn.close()

@app.route('/api/env')
def api_env():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM env_data ORDER BY id DESC LIMIT 50")
            return jsonify(cursor.fetchall())
    finally:
        conn.close()

@app.route('/api/gps')
def api_gps():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM gps_data ORDER BY id DESC LIMIT 50")
            return jsonify(cursor.fetchall())
    finally:
        conn.close()

@app.route('/api/mesh')
def api_mesh():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Get latest 50 mesh pings overall
            cursor.execute("SELECT * FROM mesh_data ORDER BY id DESC LIMIT 50")
            return jsonify(cursor.fetchall())
    finally:
        conn.close()

@app.route('/api/insights')
def api_insights():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as events FROM seismic_data WHERE is_event = 1")
            events = cursor.fetchone()['events']
            
            cursor.execute("SELECT MAX(sta_lta_ratio) as peak_ratio FROM mesh_data")
            peak = cursor.fetchone()['peak_ratio']
            
            return jsonify({
                "total_alerts": events,
                "peak_ratio": peak or 0.0,
                "system_status": "ACTIVE"
            })
    finally:
        conn.close()

if __name__ == '__main__':
    # Run securely on all interfaces for access from phone/other PCs on the network
    app.run(host='0.0.0.0', port=5000, debug=True)
