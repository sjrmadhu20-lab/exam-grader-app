import streamlit as st
import os
import io
import json
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps
import pandas as pd
from pypdf import PdfReader
import google.generativeai as genai

# --- PAGE CONFIG ---
st.set_page_config(page_title="Al Diyafah Exam Grader & Marker", layout="wide", page_icon="📝")

# --- INITIALIZE CLASS DATABASE (PERSISTENT ACROSS SCANS) ---
if "class_records" not in st.session_state:
    st.session_state["class_records"] = {}

# --- DOWNLOAD HANDWRITING FONT ---
FONT_PATH = "Caveat-Bold.ttf"
if not os.path.exists(FONT_PATH):
    try:
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/Caveat%5Bwght%5D.ttf"
        urllib.request.urlretrieve(font_url, FONT_PATH)
    except Exception:
        FONT_PATH = None

def get_font(size=44):
    if FONT_PATH and os.path.exists(FONT_PATH):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()
    return ImageFont.load_default()

# --- A4 NORMALIZATION & 2-PAGE SPREAD SPLITTER ---
A4_W, A4_H = 2480, 3508

def fit_to_a4(img):
    """Pads or fits an image into standard 300 DPI A4 portrait format (2480 x 3508)."""
    img_ratio = img.width / img.height
    a4_ratio = A4_W / A4_H
    
    if img_ratio > a4_ratio:
        new_w = A4_W
        new_h = int(A4_W / img_ratio)
    else:
        new_h = A4_H
        new_w = int(A4_H * img_ratio)
        
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))
    offset = ((A4_W - new_w) // 2, (A4_H - new_h) // 2)
    canvas.paste(resized, offset)
    return canvas

def split_and_order_pages(raw_images):
    """
    Unfolds 2-page spreads (Pages 2-3 and Pages 4-5),
    rotates them upright, and returns exactly 6 individual A4 pages in order.
    """
    # 1. Identify cover page (contains header text or index 0)
    pages_list = []
    
    for item in raw_images:
        img = ImageOps.exif_transpose(item["image"])
        w, h = img.size
        
        # If camera photographed a double-page spread sideways (height > width):
        if h > w * 1.15 and item["idx"] in [1, 2]:
            rotated = img.rotate(270, expand=True)
            rw, rh = rotated.size
            p_left = rotated.crop((0, 0, rw // 2, rh))
            p_right = rotated.crop((rw // 2, 0, rw, rh))
            pages_list.append(fit_to_a4(p_left))
            pages_list.append(fit_to_a4(p_right))
        # If photographed in landscape double-spread:
        elif w > h * 1.2:
            p_left = img.crop((0, 0, w // 2, h))
            p_right = img.crop((w // 2, 0, w, h))
            pages_list.append(fit_to_a4(p_left))
            pages_list.append(fit_to_a4(p_right))
        else:
            pages_list.append(fit_to_a4(img))
            
    return pages_list

# --- REALISTIC HANDWRITING MARKS ---
def draw_handwritten_text(draw, pos, text, size=46, color=(195, 25, 25, 240)):
    font = get_font(size)
    draw.text(pos, text, fill=color, font=font)

def draw_handwritten_circle_score(draw, x, y, score, color=(195, 25, 25, 240)):
    r = 34
    draw.arc([x - r, y - r, x + r + 6, y + r + 4], start=12, end=350, fill=color, width=4)
    draw_handwritten_text(draw, (x - 14, y - 28), str(score), size=44, color=color)

def annotate_cover_page(image, eval_result):
    """Fills only the first page score lines and summary table in red ink."""
