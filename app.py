from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from paddleocr import PaddleOCR
from PIL import Image, ImageOps
import os
import tempfile

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12 MB
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

# OCRモデルは起動時に1回だけロードする。CPU環境で動作。
ocr = PaddleOCR(
    lang='japan',
    device='cpu',
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
)

@app.get('/')
def home():
    return send_from_directory(BASE_DIR, 'index.html')

@app.get('/api/health')
def health():
    return jsonify({'ok': True, 'engine': 'PaddleOCR', 'language': 'japan'})

@app.post('/api/ocr')
def run_ocr():
    uploaded = request.files.get('image')
    if not uploaded or not uploaded.filename:
        return jsonify({'error': '画像ファイルが送信されていません。'}), 400
    ext = Path(uploaded.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': '対応画像形式は JPG / PNG / WEBP / BMP です。'}), 400

    temp_path = None
    try:
        # Pillowで画像を検証し、EXIFの回転情報を反映して一時ファイルに保存
        image = Image.open(uploaded.stream)
        image = ImageOps.exif_transpose(image).convert('RGB')
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            temp_path = tmp.name
        image.save(temp_path, format='JPEG', quality=95)

        results = ocr.predict(temp_path)
        lines = []
        for result in results:
            texts = result.get('rec_texts', [])
            scores = result.get('rec_scores', [])
            for i, text in enumerate(texts):
                text = str(text).strip()
                if not text:
                    continue
                score = float(scores[i]) if i < len(scores) else None
                lines.append({'text': text, 'confidence': round(score, 4) if score is not None else None})
        return jsonify({'lines': lines, 'text': '\n'.join(row['text'] for row in lines)})
    except Exception as exc:
        app.logger.exception('PaddleOCR failed')
        return jsonify({'error': f'画像解析中にエラーが発生しました: {type(exc).__name__}: {exc}'}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

if __name__ == '__main__':
    # LAN内のスマートフォンからアクセスできるよう全インターフェースで待ち受ける
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), debug=False)
