import os
import json
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import hashlib
import threading
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
handler = RotatingFileHandler('uploader.log', maxBytes=10000000, backupCount=5)
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
app.logger.addHandler(handler)

# 配置上传文件的存储路径
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
CHUNK_FOLDER = os.path.join(UPLOAD_FOLDER, 'chunks')
Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
Path(CHUNK_FOLDER).mkdir(parents=True, exist_ok=True)

# 上传配置
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 每个分片最大5MB
ALLOWED_EXTENSIONS = {'*'}  # 允许所有文件类型

# 用于存储上传进度的字典
upload_progress = {}
upload_locks = {}

def allowed_file(filename):
    """检查文件类型是否允许上传"""
    if '*' in ALLOWED_EXTENSIONS:
        return True
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_hash(file_path):
    """计算文件的MD5哈希值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def merge_chunks(filename, total_chunks):
    """合并文件分片"""
    try:
        final_path = os.path.join(UPLOAD_FOLDER, filename)
        with open(final_path, 'wb') as final_file:
            for i in range(total_chunks):
                chunk_path = os.path.join(CHUNK_FOLDER, f"{filename}_{i}")
                if os.path.exists(chunk_path):
                    with open(chunk_path, 'rb') as chunk:
                        final_file.write(chunk.read())
                    os.remove(chunk_path)  # 合并后删除分片
                else:
                    raise Exception(f"Missing chunk {i}")
        
        # 计算并返回文件哈希值
        file_hash = get_file_hash(final_path)
        return True, file_hash
    except Exception as e:
        app.logger.error(f"Error merging chunks for {filename}: {str(e)}")
        return False, str(e)

@app.route('/upload/chunk', methods=['POST'])
def upload_chunk():
    """处理文件分片上传"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        chunk_number = int(request.form['chunk'])
        total_chunks = int(request.form['total_chunks'])
        filename = secure_filename(request.form['filename'])
        
        if file and allowed_file(filename):
            # 获取或创建文件锁
            if filename not in upload_locks:
                upload_locks[filename] = threading.Lock()
            
            with upload_locks[filename]:
                # 保存分片
                chunk_path = os.path.join(CHUNK_FOLDER, f"{filename}_{chunk_number}")
                file.save(chunk_path)
                
                # 更新上传进度
                if filename not in upload_progress:
                    upload_progress[filename] = {'uploaded_chunks': set(), 'total_chunks': total_chunks}
                upload_progress[filename]['uploaded_chunks'].add(chunk_number)
                
                current_progress = len(upload_progress[filename]['uploaded_chunks'])
                
                # 检查是否所有分片都已上传
                if current_progress == total_chunks:
                    success, result = merge_chunks(filename, total_chunks)
                    if success:
                        # 清理进度信息
                        del upload_progress[filename]
                        del upload_locks[filename]
                        return jsonify({
                            'status': 'complete',
                            'filename': filename,
                            'hash': result
                        })
                    else:
                        return jsonify({'error': f'Failed to merge chunks: {result}'}), 500
                
                return jsonify({
                    'status': 'chunk_uploaded',
                    'chunk': chunk_number,
                    'progress': (current_progress / total_chunks) * 100
                })
        
        return jsonify({'error': 'Invalid file type'}), 400
    
    except Exception as e:
        app.logger.error(f"Error in upload_chunk: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload/status/<filename>')
def get_upload_status(filename):
    """获取文件上传进度"""
    if filename in upload_progress:
        current_progress = len(upload_progress[filename]['uploaded_chunks'])
        total_chunks = upload_progress[filename]['total_chunks']
        return jsonify({
            'status': 'in_progress',
            'progress': (current_progress / total_chunks) * 100,
            'uploaded_chunks': list(upload_progress[filename]['uploaded_chunks']),
            'total_chunks': total_chunks
        })
    return jsonify({'status': 'not_found'}), 404

@app.route('/upload/verify', methods=['POST'])
def verify_upload():
    """验证已上传的文件"""
    try:
        data = request.get_json()
        filename = secure_filename(data.get('filename'))
        client_hash = data.get('hash')
        
        if not filename or not client_hash:
            return jsonify({'error': 'Missing filename or hash'}), 400
        
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        server_hash = get_file_hash(file_path)
        if server_hash == client_hash:
            return jsonify({'status': 'verified', 'hash': server_hash})
        else:
            # 如果哈希值不匹配，删除文件
            os.remove(file_path)
            return jsonify({'error': 'Hash mismatch', 'server_hash': server_hash}), 400
            
    except Exception as e:
        app.logger.error(f"Error in verify_upload: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
