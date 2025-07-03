from flask import Flask, render_template, request, send_file, url_for
from PIL import Image, ExifTags
from PyPDF2 import PdfReader
import docx
import io
import uuid

app = Flask(__name__)

SUPPORTED_FORMATS = {
    "Images": ["jpg", "jpeg", "png"],
    "Documents": ["pdf", "docx"]
}

TEMP_FILES = {}

def convert_to_degrees(value):
    d = value[0][0] / value[0][1]
    m = value[1][0] / value[1][1]
    s = value[2][0] / value[2][1]
    return d + (m / 60.0) + (s / 3600.0)

def parse_gps_info(gps_info):
    gps_data = {}
    for key in gps_info:
        name = ExifTags.GPSTAGS.get(key, key)
        gps_data[name] = gps_info[key]

    if 'GPSLatitude' in gps_data and 'GPSLatitudeRef' in gps_data and \
       'GPSLongitude' in gps_data and 'GPSLongitudeRef' in gps_data:
        lat = convert_to_degrees(gps_data['GPSLatitude'])
        if gps_data['GPSLatitudeRef'] != 'N':
            lat = -lat
        lon = convert_to_degrees(gps_data['GPSLongitude'])
        if gps_data['GPSLongitudeRef'] != 'E':
            lon = -lon
        gps_data['Latitude'] = lat
        gps_data['Longitude'] = lon
    return gps_data

def is_readable(value):
    if isinstance(value, bytes):
        return False
    if isinstance(value, str):
        if any(ord(c) < 32 and c not in '\r\n\t' for c in value):
            return False
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (tuple, list, dict)):
        return True
    return False

def simplify_value(value):
    if isinstance(value, dict):
        return {str(k): simplify_value(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [simplify_value(i) for i in value]
    elif isinstance(value, bytes):
        return "Binary data hidden"
    else:
        return str(value)

def clean_metadata(info):
    result = {}
    for tag_id, value in info.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        if tag == 'GPSInfo' and isinstance(value, dict):
            gps_parsed = parse_gps_info(value)
            result[tag] = simplify_value(gps_parsed)
        else:
            if is_readable(value):
                result[tag] = simplify_value(value)
            else:
                result[tag] = "Binary data hidden"
    return result

def get_image_metadata(file):
    file.seek(0)
    image = Image.open(file)
    info = image._getexif()
    if not info:
        return None
    return clean_metadata(info)

def remove_image_metadata(file):
    file.seek(0)
    image = Image.open(file)
    data = list(image.getdata())
    clean_image = Image.new(image.mode, image.size)
    clean_image.putdata(data)
    byte_io = io.BytesIO()
    clean_image.save(byte_io, format=image.format)
    byte_io.seek(0)
    return byte_io

def get_pdf_metadata(file):
    file.seek(0)
    try:
        reader = PdfReader(file)
        info = reader.metadata
        if not info:
            return None
        result = {}
        for key, value in info.items():
            result[str(key)] = str(value)
        return result
    except:
        return None

def get_docx_metadata(file):
    file.seek(0)
    try:
        doc = docx.Document(file)
        core_properties = doc.core_properties
        result = {}
        for prop in dir(core_properties):
            if not prop.startswith('_') and not callable(getattr(core_properties, prop)):
                value = getattr(core_properties, prop)
                if value:
                    result[prop] = str(value)
        if result:
            return result
        return None
    except:
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    metadata = {}
    cleaned_file = None
    cleaned_filename = None
    file_type = None
    download_key = None

    if request.method == 'POST':
        uploaded_file = request.files['file']
        if uploaded_file:
            filename = uploaded_file.filename.lower()
            ext = filename.split('.')[-1]

            if ext in SUPPORTED_FORMATS["Images"]:
                file_type = "image"
                metadata["Image Metadata"] = get_image_metadata(uploaded_file)
                uploaded_file.seek(0)
                cleaned_file = remove_image_metadata(uploaded_file)
                cleaned_filename = f"cleaned_{filename}"

                key = str(uuid.uuid4())
                TEMP_FILES[key] = (cleaned_file, cleaned_filename)
                download_key = key

            elif ext == "pdf":
                file_type = "pdf"
                metadata["PDF Metadata"] = get_pdf_metadata(uploaded_file)

            elif ext == "docx":
                file_type = "docx"
                metadata["DOCX Metadata"] = get_docx_metadata(uploaded_file)

            else:
                metadata = {"Error": "Unsupported file format."}

    return render_template("index.html",
                           metadata=metadata,
                           cleaned_file=cleaned_file,
                           cleaned_filename=cleaned_filename,
                           file_type=file_type,
                           supported_formats=SUPPORTED_FORMATS,
                           download_key=download_key)

@app.route('/download/<key>')
def download(key):
    if key not in TEMP_FILES:
        return "File not found or expired.", 404
    byte_io, filename = TEMP_FILES.pop(key)
    byte_io.seek(0)
    return send_file(byte_io,
                     download_name=filename,
                     as_attachment=True,
                     mimetype='image/jpeg')

if __name__ == '__main__':
    app.run(debug=True)
